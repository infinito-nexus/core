const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  decodeDotenvQuotedValue,
  expectHstsWhenTls,
  ownResponseHeaders,
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  safeIsEnabled,
  waitForEmailInMailbox,
  webmailSsoLogin,
} = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const webmailBaseUrl = normalizeBaseUrl(decodeDotenvQuotedValue(process.env.WEBMAIL_BASE_URL || ""));
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const ssoEnabled = (process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true";

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("GitLab front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected GitLab response").toBeTruthy();
  expect(response.status(), "Expected GitLab front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the GitLab URL`
  ).toBe(true);
  expectHstsWhenTls(await ownResponseHeaders(response), appBaseUrl, "GitLab");
});

test("GitLab returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected GitLab front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`
  ).toBe(true);
});

require("./test-mcp-guest");
require("./test-integrations").register();
require("./test-design");

// Outbound mail. `templates/config/smtp_settings.rb.j2` derives ActionMailer's
// `tls:` from the provider's own declaration, and tls/starttls are mutually
// exclusive there: implicit TLS on 465, or STARTTLS on the relay port, never
// both. Getting it wrong does not fail the send — GitLab queues the mail and
// reports success — so the only proof is reading the message back out of the
// recipient's mailbox. GitLab only mails an address it knows, and the OmniAuth
// sign-in is what creates the account, so the persona logs in once before asking.
test("gitlab: a password-reset request is delivered to the recipient's mailbox", async ({ page }) => {
  test.skip(!safeIsEnabled("email"), "no mail provider in this deploy");
  test.skip(!ssoEnabled, "the administrator account is created by the first SSO login");
  test.skip(!webmailBaseUrl, "the active mail provider serves no webmail vhost to read from");
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  await runAdminFlow(page);

  await gotoOnion(page, `${appBaseUrl}/users/password/new`);
  await page.locator("input[type='email'], #user_email").first().fill(adminEmail);
  await page.locator("input[type='submit'], button[type='submit']").first().click();
  await expect(
    page.locator("body"),
    "GitLab must confirm it accepted the reset request"
  ).toContainText(/recovery link|password recovery|reset|instructions|receive/i, {
    timeout: resolveTimeout(30_000),
  });

  const mailbox = await page.context().newPage();
  try {
    await webmailSsoLogin(mailbox, adminUsername, adminPassword, webmailBaseUrl);
    const row = await waitForEmailInMailbox(mailbox, webmailBaseUrl, "password", resolveTimeout(120_000));
    await expect(row, "the reset mail must reach the mailbox").toBeVisible();
  } finally {
    await mailbox.close().catch(() => {});
  }
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → no admin or external flag, provider-synced profile → universal logout", async ({ page }) => {
  await runBiberFlow(page, {
    biberInteraction: async (interactivePage) => {
      const response = await interactivePage.request.get(`${appBaseUrl}/api/v4/user`, { timeout: resolveTimeout(30_000) });
      const body = await response.text();
      expect(response.ok(), `GET /api/v4/user must answer for biber, got ${response.status()}: ${body.slice(0, 300)}`).toBe(true);
      const self = JSON.parse(body);
      expect(self.is_admin === true, "the role group reconcile must leave biber without GitLab admin rights").toBe(false);
      expect(self.external, "the role group reconcile must leave biber outside the external role").toBe(false);

      await gotoOnion(interactivePage, `${appBaseUrl}/-/user_settings/profile`);
      await expect(
        interactivePage.locator("#user_name"),
        "sync_profile_attributes must make the provider-synced full name read-only",
      ).toHaveAttribute("readonly", "readonly", { timeout: resolveTimeout(30_000) });
    },
  });
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const link = interactivePage
        .getByRole("link", { name: /^admin(\s*area)?$/i })
        .first();
      await expect(link).toBeVisible({ timeout: resolveTimeout(30_000) });
      await link.click({ timeout: resolveTimeout(30_000) });
      await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
      await expect(interactivePage).toHaveURL(/\/admin/, {
        timeout: resolveTimeout(30_000),
      });
    },
  });
});
