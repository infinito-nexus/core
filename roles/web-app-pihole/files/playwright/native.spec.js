// @ts-check
// Scenario: Native admin login (Keycloak not enabled)
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
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.beforeEach(() => {
  test.skip(!!oidcIssuerUrl, "SSO is enabled — skipping native login tests");
  expect(piholeBaseUrl, "PIHOLE_BASE_URL must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
});

test("administrator: can log in natively to pihole", async ({ page }) => {
  const expectedPiholeBaseUrl = piholeBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedPiholeBaseUrl}/admin/login`);
  await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

  const passwordInput = page.getByRole("textbox", { name: /password/i });
  await passwordInput.waitFor({ state: "visible", timeout: 30_000 });
  await passwordInput.fill(adminPassword);
  // Pi-hole v6 login button text is "Log in (uses cookie)"
  await page.getByRole("button", { name: /log in|sign in/i }).click();

  await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
  await expect(page.locator("body")).toBeVisible();
  expect(page.url()).toContain("/admin");
});
