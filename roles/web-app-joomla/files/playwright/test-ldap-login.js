const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const joomlaBaseUrl = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.use({ ignoreHTTPSErrors: true });

// Log out via the universal logout endpoint. Every app's nginx vhost intercepts
// `location = /logout` and proxies it to web-svc-logout. Using `waitUntil: 'commit'`
// avoids ERR_ABORTED from the multi-domain redirect chain.
async function joomlaLogout(page, baseUrl) {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/logout`, { waitUntil: "commit" }).catch(() => {});
}

test("LDAP: Joomla core LDAP plugin authenticates the administrator at /administrator (LDAP variant)", async ({ page }) => {
  // In the LDAP variant (variant 1 of meta/variants.yml), the OIDC
  // service flag is off and Joomla's core LDAP authentication plugin
  // is the integrated login path against svc-db-openldap. This
  // scenario exercises that path.
  expect(joomlaBaseUrl, "JOOMLA_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  await page.context().clearCookies();
  skipUnlessServiceEnabled("ldap");
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedJoomlaBaseUrl}/administrator`, { waitUntil: "domcontentloaded" });

  const usernameField = page.locator("input[name='username']");
  const passwordField = page.locator("input[name='passwd']");
  await usernameField.waitFor({ state: "visible", timeout: 60_000 });
  await usernameField.fill(adminUsername);
  await passwordField.fill(adminPassword);
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator("button[type='submit'], input[type='submit']").first().click(),
  ]);

  // Body class on Joomla 5.x admin is `option-com_cpanel`; older releases used
  // `com_cpanel`. Match both, plus any `option-com_*` so first-login redirects
  // through `com_postinstall` don't false-fail the post-login assertion.
  const controlPanelMarker = page
    .locator("body.com_cpanel, body[class*='option-com_'], #sidebarmenu, nav[aria-label='Main menu'], a[href*='option=com_cpanel']")
    .first();
  // Race the success marker against Joomla's "Username and password do not
  // match" error. Without it, bad credentials make the test hang for the full
  // timeout per retry; with it, we fail fast with the actual error in the trace.
  const loginErrorAlert = page
    .locator(".alert-warning, .alert-danger, joomla-alert, [role='alert']")
    .filter({ hasText: /Username and password do not match|Login failed|invalid|incorrect/i })
    .first();
  await Promise.race([
    controlPanelMarker.waitFor({ state: "visible", timeout: 120_000 }),
    loginErrorAlert
      .waitFor({ state: "visible", timeout: 120_000 })
      .then(async () => {
        const errorText = (await loginErrorAlert.textContent().catch(() => "")) || "(unknown)";
        throw new Error(`Joomla rejected the admin login: ${errorText.trim()}`);
      }),
  ]);

  await joomlaLogout(page, expectedJoomlaBaseUrl);

  // After logout, /administrator must render the login form again rather than
  // the control panel.
  await page.goto(`${expectedJoomlaBaseUrl}/administrator`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await expect(page.locator("input[name='username']")).toBeVisible({ timeout: 15_000 });
});
