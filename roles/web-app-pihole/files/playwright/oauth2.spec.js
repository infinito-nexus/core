// @ts-check
// Scenarios: SSO login for administrator and biber (Keycloak enabled)
const { test, expect } = require("@playwright/test");

test.use({ ignoreHTTPSErrors: true });

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) return value;
  if (!(value.startsWith('"') && value.endsWith('"'))) return value;
  const encoded = value.slice(1, -1);
  try { return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$"); }
  catch { return encoded.replace(/\$\$/g, "$"); }
}

const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const piholeBaseUrl = decodeDotenvQuotedValue(process.env.PIHOLE_BASE_URL);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

test.beforeEach(() => {
  test.skip(!oidcIssuerUrl, "SSO not enabled — skipping OAuth2 tests");
  expect(piholeBaseUrl, "PIHOLE_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
});

async function performOidcLogin(page, username, password) {
  await page.getByRole("textbox", { name: /username|email/i }).waitFor({ state: "visible", timeout: 60_000 });
  await page.getByRole("textbox", { name: /username|email/i }).fill(username);
  await page.getByRole("textbox", { name: /username|email/i }).press("Tab");
  await page.getByRole("textbox", { name: "Password" }).fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
}

test("administrator: can log in via SSO and access pihole", async ({ page }) => {
  const expectedOidcAuthUrl   = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedPiholeBaseUrl = piholeBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedPiholeBaseUrl}/`);
  await expect.poll(() => page.url(), { timeout: 30_000 }).toContain(expectedOidcAuthUrl);
  await performOidcLogin(page, adminUsername, adminPassword);
  await page.waitForLoadState("networkidle", { timeout: 60_000 }).catch(() => {});
  expect(page.url()).not.toContain(expectedOidcAuthUrl);
  await expect(page.locator("body")).toBeVisible();
});

test("biber: is denied access to pihole admin panel", async ({ page }) => {
  const expectedOidcAuthUrl   = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedPiholeBaseUrl = piholeBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedPiholeBaseUrl}/`);
  await expect.poll(() => page.url(), { timeout: 30_000 }).toContain(expectedOidcAuthUrl);
  await performOidcLogin(page, biberUsername, biberPassword);
  await page.waitForURL(url => !url.toString().includes("/oauth2/callback"), { timeout: 30_000 }).catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

  const bodyText = await page.locator("body").textContent({ timeout: 15_000 }).catch(() => "");
  const currentUrl = page.url();
  expect(
    bodyText.includes("403") || bodyText.toLowerCase().includes("forbidden") ||
    bodyText.toLowerCase().includes("access denied") || bodyText.toLowerCase().includes("you do not have permission") ||
    currentUrl.includes(expectedOidcAuthUrl) || currentUrl.includes("/oauth2/callback"),
    `Expected biber to be denied. URL: ${currentUrl}`
  ).toBeTruthy();
});

test("administrator: can log out via logout button", async ({ page }) => {
  const expectedOidcAuthUrl   = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedPiholeBaseUrl = piholeBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedPiholeBaseUrl}/admin/`);
  await expect.poll(() => page.url(), { timeout: 30_000 }).toContain(expectedOidcAuthUrl);
  await performOidcLogin(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: 60_000 }).toContain(expectedPiholeBaseUrl);
  await page.waitForURL(url => !url.toString().includes("/oauth2/callback"), { timeout: 30_000 }).catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

  await page.goto(`${expectedPiholeBaseUrl}/oauth2/sign_out?rd=${encodeURIComponent(oidcIssuerUrl.replace(/\/$/, "").concat("/protocol/openid-connect/logout"))}`);
  const confirmButton = page.locator("#kc-logout");
  await confirmButton.waitFor({ state: "visible", timeout: 30_000 });
  await confirmButton.click();
  await expect.poll(() => page.url(), { timeout: 30_000 }).not.toContain(`${expectedPiholeBaseUrl}/admin`);
});
