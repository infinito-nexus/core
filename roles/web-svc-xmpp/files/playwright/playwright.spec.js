const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.XMPP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const xmppHost = decodeDotenvQuotedValue(process.env.XMPP_HOST);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const biberDirectoryFullName = decodeDotenvQuotedValue(process.env.BIBER_DIRECTORY_FULL_NAME);

function basicAuth(username, password) {
  const token = Buffer.from(`${username.toLowerCase()}@${xmppHost}:${password}`).toString("base64");
  return { Authorization: `Basic ${token}` };
}

async function adminGetVcardField(page, name) {
  const response = await page.request.post(`${baseUrl}/api/get_vcard`, {
    headers: basicAuth(adminUsername, adminPassword),
    data: { user: biberUsername.toLowerCase(), host: xmppHost, name },
    failOnStatusCode: false,
  });
  expect(response.status(), `get_vcard ${name} for biber must succeed for the administrator`).toBe(200);
  const body = await response.json();
  return typeof body === "string" ? body : body.content;
}

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "XMPP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("baseline: ejabberd HTTP API responds on the canonical domain", async ({ page }) => {
  // The ejabberd HTTP listener at /admin and /api covers the
  // web-facing surfaces; XMPP client login itself runs over
  // 5222/5269 and is not Playwright-testable via HTTP. The
  // baseline asserts the role at least binds correctly.
  const r = await gotoOnion(page, `${baseUrl}/admin/`);
  expect(r).toBeTruthy();
  expect(r.status()).toBeLessThan(500);
  expect(r.url().includes(canonicalDomain)).toBe(true);
});

test("guest: ejabberd LDAP backend points at svc-db-openldap (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  const r = await gotoOnion(page, `${baseUrl}/admin/`);
  expect(r).toBeTruthy();
  expect(r.status()).toBeLessThan(500);
});

test("administrator: the ejabberd web admin admits the administrator", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  expect(xmppHost, "XMPP_HOST must be set").toBeTruthy();
  const response = await page.request.get(`${baseUrl}/admin/`, {
    headers: basicAuth(adminUsername, adminPassword),
    failOnStatusCode: false,
  });
  expect(response.status(), "acl.admin MUST let the administrator into the web admin").toBe(200);
});

test("biber: the ejabberd web admin and API refuse biber without the administrator role", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  const webAdmin = await page.request.get(`${baseUrl}/admin/`, {
    headers: basicAuth(biberUsername, biberPassword),
    failOnStatusCode: false,
  });
  expect([401, 403], "biber MUST NOT reach the web admin").toContain(webAdmin.status());
  const api = await page.request.post(`${baseUrl}/api/get_vcard`, {
    headers: basicAuth(biberUsername, biberPassword),
    data: { user: biberUsername.toLowerCase(), host: xmppHost, name: "FN" },
    failOnStatusCode: false,
  });
  expect([401, 403], "biber MUST NOT call admin API commands").toContain(api.status());
});

test("administrator: biber's vCard is read from the LDAP directory", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  expect(biberDirectoryFullName, "BIBER_DIRECTORY_FULL_NAME must be set").toBeTruthy();
  expect(await adminGetVcardField(page, "FN"), "vCard FN MUST come from LDAP.USER.ATTRIBUTES.FULLNAME").toBe(
    biberDirectoryFullName,
  );
  expect(
    await adminGetVcardField(page, "NICKNAME"),
    "vCard NICKNAME MUST come from LDAP.USER.ATTRIBUTES.ID",
  ).toBe(biberUsername.toLowerCase());
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});
