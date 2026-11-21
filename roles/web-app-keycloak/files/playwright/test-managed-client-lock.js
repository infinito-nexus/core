const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvJsonList,
  gotoOnion,
  keycloakAdminToken,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");

const issuerBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.ISSUER_BASE_URL, "ISSUER_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = requireDotenvValue(process.env.SUPER_ADMIN_USERNAME, "SUPER_ADMIN_USERNAME");
const superAdminPassword = requireDotenvValue(process.env.SUPER_ADMIN_PASSWORD, "SUPER_ADMIN_PASSWORD");
const catalogue = JSON.parse(requireDotenvValue(process.env.PROFILE_LOCK_I18N_JSON, "PROFILE_LOCK_I18N_JSON"));
const locks = decodeDotenvJsonList(process.env.FIELD_LOCKS_JSON, "FIELD_LOCKS_JSON").filter((entry) => entry.record);

const ACTION = { timeout: resolveTimeout(30_000) };
const ADMIN_API = `${issuerBaseUrl}/admin/realms/${encodeURIComponent(realmName)}`;
const CONSOLE = `${issuerBaseUrl}/admin/master/console/#/${encodeURIComponent(realmName)}/clients`;
const ACCOUNT_CONSOLE = "account-console";
const PROBE_CLIENT_ID = "field-lock-probe";
const PROBE_URL = "https://field-lock-probe.example.org";
const BANNER = "#infinito-managed-fields";
const RENDERER = /\/infinito\/field-lock\.[0-9a-f]+\.js/;

async function adminHeaders(request) {
  const token = await keycloakAdminToken(request, issuerBaseUrl, superAdminUsername, superAdminPassword);
  return { Authorization: `Bearer ${token}` };
}

async function texts(page) {
  const tags = await page.evaluate(() => [document.documentElement.lang, navigator.language]);
  for (const raw of tags) {
    const tag = String(raw || "").toLowerCase();
    const entry = catalogue[tag] || catalogue[tag.split("-")[0]];
    if (entry) return entry;
  }
  return catalogue.en;
}

async function clientUuid(request, clientId) {
  const response = await request.get(`${ADMIN_API}/clients?clientId=${encodeURIComponent(clientId)}`, {
    headers: await adminHeaders(request),
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), `looking the client ${clientId} up must succeed`).toBe(200);
  const clients = await response.json();
  return clients.length ? clients[0].id : null;
}

async function removeProbeClient(request) {
  const id = await clientUuid(request, PROBE_CLIENT_ID);
  if (!id) return;
  const response = await request.delete(`${ADMIN_API}/clients/${id}`, {
    headers: await adminHeaders(request),
    timeout: resolveTimeout(30_000),
  });
  expect([204, 404], "removing the probe client must succeed").toContain(response.status());
}

async function createProbeClient(request) {
  await removeProbeClient(request);
  const response = await request.post(`${ADMIN_API}/clients`, {
    headers: { ...(await adminHeaders(request)), "Content-Type": "application/json" },
    data: {
      clientId: PROBE_CLIENT_ID,
      enabled: false,
      protocol: "openid-connect",
      publicClient: true,
      standardFlowEnabled: true,
      redirectUris: [`${PROBE_URL}/*`],
      webOrigins: [PROBE_URL],
      attributes: { "post.logout.redirect.uris": `${PROBE_URL}/*` },
    },
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "the super administrator must create the probe client").toBe(201);
  return clientUuid(request, PROBE_CLIENT_ID);
}

async function withConsole(browser, body) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => {
    if (RENDERER.test(String(error.stack || ""))) errors.push(String(error));
  });
  try {
    await gotoOnion(page, CONSOLE);
    await performKeycloakLoginForm(page, superAdminUsername, superAdminPassword);
    await body(page, context.request);
    expect(errors, "the injected lock renderer must not throw").toEqual([]);
  } finally {
    await context.close().catch(() => {});
  }
}

async function openClient(page, id, clientId) {
  await gotoOnion(page, `${CONSOLE}/${id}/settings`);
  await expect(page.locator("#clientId"), `the console must show the client ${clientId}`).toHaveValue(clientId, {
    timeout: resolveTimeout(60_000),
  });
}

async function expectLocked(page, entry, messages) {
  const controls = page.locator(entry.selector);
  await expect(controls.first(), `${entry.label} must render`).toBeVisible(ACTION);
  const count = await controls.count();
  for (let index = 0; index < count; index += 1) {
    await expect(controls.nth(index), `${entry.label} must be locked`).toHaveAttribute("aria-readonly", "true", ACTION);
    await expect(controls.nth(index), `${entry.label} must name its inventory path`).toHaveAttribute(
      "title",
      `${messages.managed} ${entry.path}`,
      ACTION,
    );
  }
  await expect(controls.and(page.locator("input")).first(), `${entry.label} must be read-only`).not.toBeEditable(ACTION);
  await expect(page.locator(BANNER), "the banner must list the managed field").toContainText(
    `${entry.label}: ${entry.path}`,
    ACTION,
  );
}

async function expectEditable(page, entry) {
  const controls = page.locator(entry.selector);
  await expect(controls.first(), `${entry.label} must render`).toBeVisible(ACTION);
  const count = await controls.count();
  for (let index = 0; index < count; index += 1) {
    await expect(controls.nth(index), `${entry.label} must stay unlocked`).not.toHaveAttribute("aria-readonly", "true");
  }
  await expect(controls.and(page.locator("input")).first(), `${entry.label} must stay editable`).toBeEditable(ACTION);
}

exports.register = function () {
  test.describe("keycloak managed client fields", () => {
    test("the deployment's client locks the URIs the deployment writes, and a confirmed double-click unlocks one", async ({
      browser,
    }) => {
      skipUnlessServiceEnabled("javascript");
      test.setTimeout(resolveTimeout(180_000));
      expect(locks.length, "FIELD_LOCKS_JSON must carry the fields of the client form").toBeGreaterThan(0);
      await withConsole(browser, async (page, request) => {
        const clientId = locks[0].record.values[0];
        await openClient(page, await clientUuid(request, clientId), clientId);
        const messages = await texts(page);
        await expect(page.locator(BANNER), "the banner must introduce the managed fields").toContainText(
          messages.banner,
          ACTION,
        );
        for (const entry of locks) {
          await expectLocked(page, entry, messages);
        }

        const [entry] = locks;
        const asked = page.waitForEvent("dialog", ACTION).then(async (dialog) => {
          const message = dialog.message();
          await dialog.accept();
          return message;
        });
        await page.locator(entry.selector).and(page.locator("input")).first().dblclick(ACTION);
        expect(await asked, "the unlock must ask the translated confirmation").toBe(messages.unlock);
        await expectEditable(page, entry);
      });
    });

    test("a client an admin created and the account console stay editable", async ({ browser }) => {
      skipUnlessServiceEnabled("javascript");
      test.setTimeout(resolveTimeout(180_000));
      await withConsole(browser, async (page, request) => {
        try {
          await openClient(page, await createProbeClient(request), PROBE_CLIENT_ID);
          for (const entry of locks) {
            await expectEditable(page, entry);
          }
          await openClient(page, await clientUuid(request, ACCOUNT_CONSOLE), ACCOUNT_CONSOLE);
          for (const entry of locks) {
            await expectEditable(page, entry);
          }
          await expect(page.locator(BANNER), "no banner on a client the deployment did not create").toHaveCount(0);
        } finally {
          await removeProbeClient(request);
        }
      });
    });
  });
};
