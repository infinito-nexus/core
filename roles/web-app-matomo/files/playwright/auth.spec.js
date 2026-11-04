const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  appBaseUrl,
  biberUsername,
  biberPassword,
  matomoOidcPlugin,
  attachDiagnostics,
  setupMatomoPage,
  loginAsAdmin,
  expectLoginForm,
  startOidcLogin,
  matomoApi,
} = require("./_shared");
const { expectNoCspViolations, gotoOnion, performKeycloakLoginForm } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  await setupMatomoPage(page);
});

test("matomo local administrator logs in and logs out", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  await loginAsAdmin(page);

  await expect(page.locator("body")).toContainText(/dashboard|websites|matomo/i, { timeout: resolveTimeout(60_000) });
  await expect(
    page.locator("body"),
    "Matomo MUST read the scheme from X-Forwarded-Proto and stop warning about a non secure connection",
  ).not.toContainText(/could only detect a non secure connection/i);

  await gotoOnion(page, `${appBaseUrl}/index.php?module=Login&action=logout`);

  await expect
    .poll(
      async () =>
        (await page
          .locator("input#login_form_login, input[name='form_login']")
          .first()
          .count()
          .catch(() => 0)) > 0,
      {
        timeout: resolveTimeout(60_000),
        message: "Expected Matomo login form to reappear after logout"
      }
    )
    .toBe(true);

  await expectNoCspViolations(page, diagnostics, "matomo administrator login");
});

test("guest: without SSO the Matomo login offers no Keycloak sign-in", async ({ page }) => {
  skipUnlessServiceDisabled("sso");

  await gotoOnion(page, `${appBaseUrl}/`);
  await expectLoginForm(page, "the anonymous Matomo front page MUST show the login form");
  await expect(
    page.locator(`form[action*='module=${matomoOidcPlugin}']`),
    `the ${matomoOidcPlugin} plugin MUST be inactive while SSO is off`,
  ).toHaveCount(0);
});

test("biber: the Keycloak login of an account without a Matomo role ends without a Matomo session or account", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();

  await startOidcLogin(page);
  await performKeycloakLoginForm(page, biberUsername, biberPassword);

  await gotoOnion(page, `${appBaseUrl}/index.php?module=CoreHome&action=index&idSite=1&period=day&date=yesterday`);
  await expectLoginForm(page, "biber holds no Matomo role, so the protected surface MUST still answer with the login form");
  await expect(page.locator("#secondNavBar, #dashboardWidgetsArea")).toHaveCount(0);

  const exists = await matomoApi(page.request, "UsersManager.userExists", { userLogin: biberUsername });
  expect(
    exists?.value ?? exists,
    `the deploy MUST NOT have provisioned a Matomo account for ${biberUsername}, who holds no Matomo role`,
  ).toBe(false);
});
