const { test, expect } = require("@playwright/test");

const { safeSkipUnlessEnabled } = require("./personas");
const { roundcubeSsoLogin, roundcubeLogout, waitForEmailInMailbox } = require("./webmail");
const {
  webmailBaseUrl,
  adminEmail,
  adminUsername,
  adminPassword,
  biberUsername,
  biberPassword,
} = require("./env");

// biber -> administrator send/receive through the Roundcube webmail UI.
// Login is via Keycloak SSO (Roundcube XOAUTH2 -> Stalwart), mirroring
// web-app-mailu. biber and the administrator are separate people: isolated
// browser contexts.
test("stalwart: biber sends to administrator, administrator receives it", async ({ browser }) => {
  safeSkipUnlessEnabled("sso");
  // Exception: the env template always renders these — a missing value is a
  // rendering regression and MUST fail, not silently skip the flagship scenario.
  expect(webmailBaseUrl, "WEBMAIL_BASE_URL must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const testSubject = `Playwright stalwart ${Date.now()}`;
  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });

  try {
    const biberPage = await biberContext.newPage();
    await roundcubeSsoLogin(biberPage, biberUsername, biberPassword);
    await biberPage.goto(`${webmailBaseUrl}/?_task=mail&_action=compose`);
    await biberPage.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await biberPage.locator("#_to, input[name='_to']").first().fill(adminEmail);
    await biberPage.locator("#compose-subject, input[name='_subject']").first().fill(testSubject);
    await biberPage.locator("#composebody, textarea[name='_message'], [contenteditable='true']").first()
      .fill("Hello Administrator, this is an automated Playwright test email.");
    await biberPage.locator(".formbuttons .send, button.send, a.send").first().click();
    // Exception: Roundcube (Elastic, framed) sends via AJAX and may stay on the
    // compose URL with only a toast; surface an SMTP error immediately, the
    // real proof of a successful send is receipt in the admin inbox below.
    const sendError = biberPage.locator("#messagestack .error, .toast .error, .toast-error").first();
    if (await sendError.isVisible({ timeout: 15_000 }).catch(() => false)) {
      throw new Error(`Roundcube reported a send error: ${await sendError.textContent()}`);
    }
    await roundcubeLogout(biberPage);

    const adminPage = await adminContext.newPage();
    await roundcubeSsoLogin(adminPage, adminUsername, adminPassword);
    const emailRow = await waitForEmailInMailbox(adminPage, webmailBaseUrl, testSubject, 90_000);
    await expect(emailRow).toBeVisible();
    await emailRow.click();
    await expect(
      adminPage.locator("#messagecontframe, #mailview-right, .message-part").first()
    ).toBeVisible({ timeout: 15_000 });
    await roundcubeLogout(adminPage);
  } finally {
    await biberContext.close().catch(() => {});
    await adminContext.close().catch(() => {});
  }
});
