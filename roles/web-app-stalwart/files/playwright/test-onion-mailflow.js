const { test, expect } = require("@playwright/test");

const { safeSkipUnlessEnabled, gotoOnion } = require("./personas");
const { roundcubeSsoLogin, roundcubeLogout } = require("./webmail");
const { webmailBaseUrl, biberUsername, biberPassword } = require("./env");
const { resolveTimeout, isSplitRealmOidc } = require("./timeouts");

// Outbound .onion delivery from the user's side: biber addresses a recipient on a
// foreign onion and the message leaves as queued mail instead of bouncing.
//
// The lab has no external onion mail peer, so this asserts the routing decision
// rather than a remote receipt: with MtaRoute + MtaOutboundStrategy in place the
// recipient is accepted and queued to the tor-smtp relay, whereas an unrouted
// .onion domain has no MX and returns a delivery failure to the sender. The
// recipient domain is deliberately not a local domain — is_local_domain wins over
// the .onion match in the strategy, so a self-addressed onion would route 'local'
// and never reach the gateway.
const FOREIGN_ONION = "recipient@nexusprobe7xk3mjqzvhbnd4rlyugc2pfe6sotai5w.onion";

test("biber: a .onion recipient is accepted and routed through the Tor gateway", async ({ browser }) => {
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  safeSkipUnlessEnabled("tor");
  safeSkipUnlessEnabled("sso");
  expect(webmailBaseUrl, "WEBMAIL_BASE_URL must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  const testSubject = `Playwright onion route ${Date.now()}`;
  const proxyServer = process.env.PLAYWRIGHT_PROXY;
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    ...(proxyServer ? { proxy: { server: proxyServer } } : {}),
  });

  try {
    const page = await context.newPage();
    await roundcubeSsoLogin(page, biberUsername, biberPassword);
    await gotoOnion(page, `${webmailBaseUrl}/?_task=mail&_action=compose`);
    await page.waitForLoadState("networkidle", { timeout: resolveTimeout(15_000) }).catch(() => {});
    await page.locator("#_to, input[name='_to']").first().fill(FOREIGN_ONION);
    await page.locator("#compose-subject, input[name='_subject']").first().fill(testSubject);
    await page.locator("#composebody, textarea[name='_message'], [contenteditable='true']").first()
      .fill("Automated Playwright probe for the .onion outbound route.");
    await page.locator(".formbuttons .send, button.send, a.send").first().click();

    const sendError = page.locator("#messagestack .error, .toast .error, .toast-error").first();
    if (await sendError.isVisible().catch(() => false)) {
      throw new Error(`Stalwart refused the .onion recipient: ${await sendError.textContent()}`);
    }

    // Exception: the negative half carries the signal — an unrouted .onion has no MX,
    // so Stalwart would hand the sender a delivery failure instead of holding the
    // message for the relay. Landing in Sent proves nothing about routing, so the
    // assertion is the absence of that bounce rather than the presence of a copy.
    await gotoOnion(page, `${webmailBaseUrl}/?_task=mail&_mbox=INBOX`);
    await page.waitForTimeout(resolveTimeout(10_000));
    await gotoOnion(page, `${webmailBaseUrl}/?_task=mail&_mbox=INBOX`);
    await expect(
      page.locator("#messagelist").getByText(/undelivered|delivery status|delivery failure|mailer-daemon/i).first()
    ).toBeHidden({ timeout: resolveTimeout(15_000) });

    await roundcubeLogout(page);
  } finally {
    await context.close().catch(() => {});
  }
});
