const { test, expect } = require("@playwright/test");

const { safeSkipUnlessEnabled, gotoOnion, recordVideoOptions } = require("./personas");
const { roundcubeSsoLogin, roundcubeLogout, sendMail } = require("./webmail");
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

test("biber: a .onion recipient is accepted and routed through the Tor gateway", async ({ browser }, testInfo) => {
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  safeSkipUnlessEnabled("tor");
  safeSkipUnlessEnabled("sso");
  expect(webmailBaseUrl, "WEBMAIL_BASE_URL must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  const testSubject = `Playwright onion route ${Date.now()}`;
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    ...recordVideoOptions(testInfo),
  });

  try {
    const page = await context.newPage();
    await roundcubeSsoLogin(page, biberUsername, biberPassword);
    await sendMail(page, FOREIGN_ONION, testSubject, "Automated Playwright probe for the .onion outbound route.");

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
