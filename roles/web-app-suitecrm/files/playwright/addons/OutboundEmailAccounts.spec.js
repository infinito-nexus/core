const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  decodeDotenvQuoted,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const smtpHost = decodeDotenvQuoted(process.env.EMAIL_SMTP_HOST);
const adminUsername = decodeDotenvQuoted(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuoted(process.env.ADMIN_PASSWORD);

const MAILER_SETTINGS_ROUTE = "/legacy/index.php?module=EmailMan&action=config";

test("addon OutboundEmailAccounts: SuiteCRM's mailer points at the deployed Mailu SMTP host", async ({ page }) => {
  skipUnlessAddonEnabled("OutboundEmailAccounts");
  skipUnlessServiceEnabled("email");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(smtpHost, "EMAIL_SMTP_HOST must be set when the email service is on").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  await page.context().clearCookies();

  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  const session = await page.request.get(`${appBaseUrl}/session-status`, {
    timeout: resolveTimeout(30_000),
  });
  expect(session.status(), "session-status must answer after the login").toBeLessThan(400);
  expect(
    (await session.json()).active,
    "the mailer settings are an administrator surface, so the login must own a SuiteCRM session",
  ).toBe(true);

  const settings = await page.request.get(`${appBaseUrl}${MAILER_SETTINGS_ROUTE}`, {
    timeout: resolveTimeout(60_000),
  });
  expect(
    settings.status(),
    `the mailer settings page ${MAILER_SETTINGS_ROUTE} must answer for an administrator`,
  ).toBeLessThan(400);

  expect(
    await settings.text(),
    `SuiteCRM's outbound mailer must carry the deployed Mailu host (${smtpHost}); without it the ` +
      "addon declares the bridge while the app still sends through its own default transport",
  ).toContain(smtpHost);
});
