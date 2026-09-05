const { test, expect } = require("@playwright/test");

const { safeSkipUnlessEnabled, gotoOnion } = require("./personas");
const { roundcubeSsoLogin, roundcubeLogout, waitForEmailInMailbox } = require("./webmail");
const {
  webmailBaseUrl,
  adminEmail,
  adminUsername,
  adminPassword,
  biberEmail,
  biberUsername,
  biberPassword,
} = require("./env");
const { resolveTimeout, isSplitRealmOidc } = require("./timeouts");

/** Compose and send one message, failing loudly if Roundcube reports a send error. */
async function sendMail(page, recipient, subject, body) {
  await gotoOnion(page, `${webmailBaseUrl}/?_task=mail&_action=compose`);
  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(15_000) }).catch(() => {});
  await page.locator("#_to, input[name='_to']").first().fill(recipient);
  await page.locator("#compose-subject, input[name='_subject']").first().fill(subject);
  await page.locator("#composebody, textarea[name='_message'], [contenteditable='true']").first().fill(body);
  await page.locator(".formbuttons .send, button.send, a.send").first().click();
  const sendError = page.locator("#messagestack .error, .toast .error, .toast-error").first();
  if (await sendError.isVisible().catch(() => false)) {
    throw new Error(`Roundcube reported a send error for ${recipient}: ${await sendError.textContent()}`);
  }
}

/** Open a delivered message and confirm its body renders. */
async function openMail(page, subject) {
  const row = await waitForEmailInMailbox(page, webmailBaseUrl, subject, resolveTimeout(90_000));
  await expect(row).toBeVisible();
  await row.click();
  await expect(
    page.locator("#messagecontframe, #mailview-right, .message-part").first()
  ).toBeVisible({ timeout: resolveTimeout(15_000) });
}

// Exception: opening a message leaves a jQuery UI dialog behind whose
// `.ui-widget-overlay` swallows the logout click; going back to the list drops it.
async function leaveOpenDialogs(page) {
  await gotoOnion(page, `${webmailBaseUrl}/?_task=mail&_mbox=INBOX`);
  await page
    .locator(".ui-widget-overlay")
    .first()
    .waitFor({ state: "detached", timeout: resolveTimeout(15_000) })
    .catch(() => {});
}

// biber <-> administrator round trip through the Roundcube webmail UI: biber writes to
// the administrator, the administrator reads it and writes back, and biber reads the
// answer. Login is via Keycloak SSO (Roundcube XOAUTH2 -> Stalwart), mirroring
// web-app-mailu. They are separate people: isolated browser contexts, and biber stays
// signed in so the answer lands in a session that never saw the outbound message.
test("stalwart: biber and the administrator exchange mail both ways", async ({ browser }) => {
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  safeSkipUnlessEnabled("sso");
  expect(webmailBaseUrl, "WEBMAIL_BASE_URL must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  expect(biberEmail, "BIBER_EMAIL must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const outbound = `Playwright stalwart ${Date.now()}`;
  const answer = `Playwright stalwart answer ${Date.now()}`;
  const proxyServer = process.env.PLAYWRIGHT_PROXY;
  const contextOptions = {
    ignoreHTTPSErrors: true,
    ...(proxyServer ? { proxy: { server: proxyServer } } : {}),
  };
  const biberContext = await browser.newContext(contextOptions);
  const adminContext = await browser.newContext(contextOptions);

  try {
    const biberPage = await biberContext.newPage();
    await roundcubeSsoLogin(biberPage, biberUsername, biberPassword);
    await sendMail(biberPage, adminEmail, outbound, "Hello Administrator, this is an automated Playwright test email.");

    const adminPage = await adminContext.newPage();
    await roundcubeSsoLogin(adminPage, adminUsername, adminPassword);
    await openMail(adminPage, outbound);
    await leaveOpenDialogs(adminPage);
    await sendMail(adminPage, biberEmail, answer, "Answer from the administrator, sent by the same Playwright run.");
    await roundcubeLogout(adminPage);

    await openMail(biberPage, answer);
    await leaveOpenDialogs(biberPage);
    await roundcubeLogout(biberPage);
  } finally {
    await biberContext.close().catch(() => {});
    await adminContext.close().catch(() => {});
  }
});
