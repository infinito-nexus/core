const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  assertCspInjections,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
  safeIsEnabled,
} = require("./personas");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.FLOWISE_BASE_URL, "FLOWISE_BASE_URL"));
const SIGN_IN_SUBMIT = "form button[type='submit']";
const APP_SHELL = "main h1";

test.use({ ignoreHTTPSErrors: true });

function biberEnv() {
  return {
    oidcIssuerUrl: normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL")),
    username: requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME"),
    password: requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD"),
  };
}

function keycloakAdminEnv() {
  return {
    baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL")),
    realmName: requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME"),
    adminRealm: requireDotenvValue(process.env.KEYCLOAK_ADMIN_REALM, "KEYCLOAK_ADMIN_REALM"),
    adminClientId: requireDotenvValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID, "KEYCLOAK_ADMIN_CLI_CLIENT_ID"),
    username: requireDotenvValue(process.env.SUPER_ADMIN_USERNAME, "SUPER_ADMIN_USERNAME"),
    password: requireDotenvValue(process.env.SUPER_ADMIN_PASSWORD, "SUPER_ADMIN_PASSWORD"),
    mcpGroupPath: requireDotenvValue(process.env.RBAC_MCP_GROUP_PATH, "RBAC_MCP_GROUP_PATH"),
  };
}

function withDeadline(promise, ms, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms} ms`)), ms);
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

/**
 * Args:
 *   browser: Playwright browser; the Keycloak Admin REST calls run in a context of their own.
 *   username: Keycloak user that joins the web-app-flowise mcp role group for the duration of `body`.
 *   body: async callback run while the membership holds.
 */
async function withUserInMcpGroup(browser, username, body) {
  const admin = keycloakAdminEnv();
  const opts = { adminRealm: admin.adminRealm, adminClientId: admin.adminClientId };
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      adminCtx.request,
      admin.baseUrl,
      admin.realmName,
      admin.mcpGroupPath,
      username,
      admin.username,
      admin.password,
      opts,
    );
    await body();
  } finally {
    if (joined) {
      await withDeadline(
        keycloakRemoveUserFromGroupViaRest(
          adminCtx.request,
          admin.baseUrl,
          admin.realmName,
          admin.username,
          admin.password,
          admin.mcpGroupPath,
          username,
          opts,
        ),
        resolveTimeout(30_000),
        `Removing ${username} from ${admin.mcpGroupPath}`,
      ).catch((err) => console.warn(`Cleanup removal of ${username} from ${admin.mcpGroupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

/**
 * Args:
 *   page: Playwright page that ends on the Keycloak login form the oauth2-proxy gate sends an anonymous visitor to.
 *   oidcIssuerUrl: Keycloak issuer the gate redirects to.
 */
async function reachKeycloak(page, oidcIssuerUrl) {
  await page.context().clearCookies();
  await gotoOnion(page, `${baseUrl}/`);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected the oauth2-proxy gate to send an anonymous visitor to Keycloak",
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
}

test("biber: app → keycloak → oauth2 gate refuses biber without a flowise role group", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  const biber = biberEnv();

  const [callback] = await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname === "/oauth2/callback", {
      timeout: resolveTimeout(120_000),
    }),
    reachKeycloak(page, biber.oidcIssuerUrl).then(() => performKeycloakLoginForm(page, biber.username, biber.password)),
  ]);

  expect(
    callback.status(),
    "oauth2-proxy MUST refuse biber at /oauth2/callback: sso.oauth2.allowed_groups admits only the administrator and mcp role groups",
  ).toBe(403);
  expect(
    new URL(page.url()).pathname,
    `Expected biber to stay on the oauth2-proxy refusal, never on a Flowise page (at ${page.url()})`,
  ).toBe("/oauth2/callback");
});

test("biber: mcp role group → keycloak → Flowise sign-in without a Flowise account", async ({ browser, page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));
  const biber = biberEnv();

  await withUserInMcpGroup(browser, biber.username, async () => {
    await reachKeycloak(page, biber.oidcIssuerUrl);
    await performKeycloakLoginForm(page, biber.username, biber.password);

    await expect
      .poll(() => new URL(page.url()).pathname, {
        timeout: resolveTimeout(90_000),
        message: "Expected the gate to admit the mcp role group and Flowise to send biber to its own sign-in",
      })
      .toBe("/signin");
    expect(page.url(), "Expected biber back on Flowise after the Keycloak login").toContain(baseUrl);
    await expect(page.locator(SIGN_IN_SUBMIT), "Expected Flowise's own sign-in form behind the gate").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
    await expect(page.locator(APP_SHELL), "the mcp role grants no Flowise account, so the app shell MUST stay absent").toHaveCount(0);
    await assertCspInjections(page, { isEnabled: safeIsEnabled });

    const chatflows = await page.request.get(`${baseUrl}/api/v1/chatflows`, {
      headers: { "x-request-from": "internal" },
      timeout: resolveTimeout(30_000),
    });
    expect(
      chatflows.status(),
      "Flowise MUST refuse biber's chatflow list: passing the oauth2 gate grants no Flowise session",
    ).toBe(401);
  });
});
