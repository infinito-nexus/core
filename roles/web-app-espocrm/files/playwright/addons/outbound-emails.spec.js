const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  clickOidcLoginLink,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLogin,
  safeIsEnabled,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const smtpHost = decodeDotenvQuotedValue(process.env.EMAIL_SMTP_HOST || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD || "");

test("addon outbound-emails: EspoCRM sends through the deployed Mailu SMTP host", async ({ page }) => {
  skipUnlessAddonEnabled("outbound-emails");
  skipUnlessServiceEnabled("email");
  test.setTimeout(resolveTimeout(240_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(smtpHost, "EMAIL_SMTP_HOST must be set when the email service is on").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();

  const expectedBase = appBaseUrl.replace(/\/$/, "");
  const oidcEnabled = safeIsEnabled("sso");

  await page.context().clearCookies();
  await gotoOnion(page, `${expectedBase}/`, { waitUntil: "domcontentloaded" });

  if (oidcEnabled) {
    expect(canonicalDomain, "CANONICAL_DOMAIN must be set when sso is on").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set when sso is on").toBeTruthy();
    let authPage = page;
    if (!page.url().includes("openid-connect/auth")) {
      const strictLogin = page
        .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i })
        .or(page.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i }))
        .first();
      const looseLogin = page
        .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
        .or(page.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
        .first();
      authPage = (await clickOidcLoginLink(page, strictLogin, looseLogin)) || page;
    }
    if (authPage.url().includes("openid-connect/auth")) {
      await performKeycloakLogin(authPage, adminUsername, adminPassword, canonicalDomain);
    }
  } else {
    test.skip(
      !adminNativePassword,
      "no native admin password: the role withholds it when LDAP owns authentication",
    );
    test.skip(
      safeIsEnabled("recaptcha"),
      "reCAPTCHA v3 guards the native login form with live keys a headless persona cannot satisfy",
    );
    const passwordField = page.locator("input[type='password']:visible").first();
    await passwordField.waitFor({ state: "visible", timeout: resolveTimeout(90_000) });
    await page.locator("input[name='username']:visible").first().fill(adminUsername);
    await passwordField.fill(adminNativePassword);
    await passwordField.press("Enter");
  }

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(120_000),
      message: "expected the EspoCRM login to land back on the application",
    })
    .toContain(expectedBase);

  await gotoOnion(page, `${expectedBase}/#Admin/outboundEmails`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });

  const smtpServerField = page.locator("[data-name='smtpServer'], input[name='smtpServer']").first();
  await expect(
    smtpServerField,
    "the Outbound Emails admin panel must render the SMTP server field; without it the login " +
      "did not reach an administrator surface and the assertion below would prove nothing",
  ).toBeAttached({ timeout: resolveTimeout(120_000) });

  const rendered =
    (await smtpServerField.inputValue().catch(() => null)) ??
    (await smtpServerField.innerText().catch(() => ""));

  expect(
    rendered,
    `EspoCRM's outbound mailer must carry the deployed Mailu host (${smtpHost}); another value ` +
      "means ESPOCRM_CONFIG_SMTP_SERVER never reached the app's own config",
  ).toContain(smtpHost);
});
