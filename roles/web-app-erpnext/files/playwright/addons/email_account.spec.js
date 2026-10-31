const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const smtpHost = decodeDotenvQuotedValue(process.env.EMAIL_SMTP_HOST || "");

const ACCOUNTS_ROUTE =
  '/api/resource/Email Account?limit_page_length=0&fields=["name","smtp_server","enable_outgoing"]';

test("addon email_account: ERPNext's outgoing account sends through the deployed Mailu SMTP host", async ({ page }) => {
  skipUnlessAddonEnabled("email_account");
  skipUnlessServiceEnabled("email");
  test.setTimeout(resolveTimeout(240_000));

  const { erpnextBaseUrl, adminNativePassword } = shared.env;
  expect(erpnextBaseUrl, "ERPNEXT_BASE_URL must be set").toBeTruthy();
  expect(smtpHost, "EMAIL_SMTP_HOST must be set when the email service is on").toBeTruthy();
  expect(adminNativePassword, "ADMIN_NATIVE_PASSWORD must be set").toBeTruthy();

  await page.context().clearCookies();
  await shared.signInViaErpnextLocal(page, "Administrator", adminNativePassword, "addon-email-account");

  const response = await page.request.get(`${erpnextBaseUrl}${ACCOUNTS_ROUTE}`, {
    timeout: resolveTimeout(60_000),
  });
  expect(
    response.status(),
    "the Email Account resource must answer for the signed-in administrator",
  ).toBeLessThan(400);

  const accounts = (await response.json()).data || [];
  const outgoing = accounts.filter((account) => Number(account.enable_outgoing) === 1);

  expect(
    outgoing.length,
    "Frappe must hold at least one outgoing Email Account; without it nothing in ERPNext can " +
      "send and the declared Mailu bridge is inert",
  ).toBeGreaterThan(0);
  expect(
    outgoing.map((account) => account.smtp_server),
    `an outgoing Email Account must name the deployed Mailu host (${smtpHost}); another value ` +
      "means the account was provisioned against a different transport",
  ).toContain(smtpHost);
});
