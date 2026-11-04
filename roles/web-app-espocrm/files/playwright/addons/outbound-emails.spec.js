const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { awaitSession } = require("../_shared");
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
const smtpPort = decodeDotenvQuotedValue(process.env.EMAIL_SMTP_PORT || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD || "");

test("addon outbound-emails: EspoCRM sends through the deployed Mailu SMTP host", async ({ page }) => {
  skipUnlessAddonEnabled("outbound-emails");
  skipUnlessServiceEnabled("email");
  test.setTimeout(resolveTimeout(240_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(smtpHost, "EMAIL_SMTP_HOST must be set when the email service is on").toBeTruthy();
  expect(smtpPort, "EMAIL_SMTP_PORT must be set when the email service is on").toBeTruthy();
  expect(
    Number.isInteger(Number(smtpPort)) && Number(smtpPort) > 0,
    "EMAIL_SMTP_PORT must be a port number when the email service is on",
  ).toBe(true);
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

  await awaitSession(
    page,
    resolveTimeout(120_000),
    "the login must mint an EspoCRM session before the admin route is opened",
  );

  await gotoOnion(page, `${expectedBase}/#Admin/groupEmailAccounts`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });

  await expect(
    page.locator("[data-scope='InboundEmail'] tr.list-row").first(),
    "the Group Email Accounts admin page must list at least one account; an empty list or an " +
      "access-denied page means the login did not reach an administrator surface and the " +
      "assertions below would prove nothing",
  ).toBeAttached({ timeout: resolveTimeout(120_000) });

  const probe = await page.evaluate(async () => {
    const key = Object.keys(localStorage).find((name) => /user-auth$/.test(name));
    const token = key ? localStorage.getItem(key) : null;
    if (!token) {
      return { token: false };
    }
    const response = await fetch("api/v1/InboundEmail?maxSize=200", {
      headers: {
        "Espo-Authorization": token,
        "Espo-Authorization-By-Token": "true",
      },
    });
    if (!response.ok) {
      return { token: true, httpStatus: response.status };
    }
    const payload = await response.json();
    const record = (payload.list || []).find((entry) => entry.isSystem === true);
    return {
      token: true,
      httpStatus: response.status,
      account: record
        ? {
            status: record.status,
            useSmtp: record.useSmtp,
            smtpHost: record.smtpHost,
            smtpPort: record.smtpPort,
            smtpAuth: record.smtpAuth,
          }
        : null,
    };
  });

  expect(
    probe.token,
    "the authenticated session must leave EspoCRM's auth token in localStorage for the API read",
  ).toBe(true);

  expect(
    probe.httpStatus,
    "InboundEmail is an admin-only scope, so anything but 200 means the session that reached " +
      "the admin page is not an administrator's",
  ).toBe(200);

  expect(
    probe.account,
    "EspoCRM must hold a group email account it reports as the system one; isSystem is true " +
      "only for the record whose address is outboundEmailFromAddress, which is exactly the row " +
      "Sender::applyGlobal resolves through SendingAccountProvider::getSystem() since 9.1; " +
      "config.smtpServer is no longer read on send",
  ).not.toBeNull();

  expect(
    probe.account.status,
    "the system group email account must be Active; getSystem() filters on that status",
  ).toBe("Active");

  expect(
    probe.account.useSmtp,
    "the system group email account must have SMTP enabled; getSystem() filters on that flag",
  ).toBe(true);

  expect(
    probe.account.smtpHost,
    `the system group email account must carry the deployed mail host (${smtpHost}); another ` +
      "value means the role never provisioned it from the deployed mail service",
  ).toBe(smtpHost);

  expect(
    probe.account.smtpPort,
    `the system group email account must carry the deployed submission port (${smtpPort}); a ` +
      'null port makes getSmtpParams() throw NoSmtp("Empty port.") on every send',
  ).toBe(Number(smtpPort));

  expect(
    probe.account.smtpAuth,
    "the system group email account must authenticate; the deployed mail service rejects an " +
      "unauthenticated submission",
  ).toBe(true);
});
