const { expect } = require("@playwright/test");

const { performKeycloakLoginForm, gotoOnion } = require("./personas");
const { webmailBaseUrl, expectedOidcAuthUrl } = require("./env");
const { resolveTimeout } = require("./timeouts");

// Roundcube auto-redirects to Keycloak (oauth_login_redirect); drive the login
// form, then wait for the mail UI.
async function roundcubeSsoLogin(page, username, password) {
  await gotoOnion(page, `${webmailBaseUrl}/`);
  const ssoButton = page
    .getByRole("button", { name: /sso|single sign.?on|login with|openid/i })
    .or(page.getByRole("link", { name: /sso|single sign.?on|login with|openid/i }));
  if (await ssoButton.first().isVisible().catch(() => false)) {
    await ssoButton.first().click();
  }
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected redirect to Keycloak OIDC: ${expectedOidcAuthUrl}`,
    })
    .toContain(expectedOidcAuthUrl);
  await performKeycloakLoginForm(page, username, password);
  await page.locator("#messagelist, .compose, a[href*='_action=compose'], .toolbar").first()
    .waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
}

// Logout MUST exist and work — a missing control is a failure, not a skip.
async function roundcubeLogout(page) {
  const logout = page.locator("a[href*='_task=logout'], a[href*='logout'], a.logout")
    .or(page.getByRole("link", { name: /logout|sign out/i }));
  await expect(logout.first(), "Roundcube logout control must be present").toBeVisible({
    timeout: resolveTimeout(10_000),
  });
  await logout.first().click();
}

// Wait for a delivered mail in the recipient's mailbox — accept Inbox OR Junk (the
// .test env has no mail-auth DNS, so Stalwart files authenticated mail under Junk).
// Folders are switched by _mbox URL to avoid clicking a non-actionable folder link.
async function waitForEmailInMailbox(page, baseUrl, subjectText, timeout = resolveTimeout(90_000)) {
  const deadline = Date.now() + timeout;
  const mailboxes = ["INBOX", "Junk Mail"];
  const rowFor = () =>
    page.locator("#messagelist tbody tr, table.messagelist tbody tr").filter({ hasText: subjectText }).first();
  while (Date.now() < deadline) {
    for (const mbox of mailboxes) {
      await gotoOnion(page, `${baseUrl}/?_task=mail&_mbox=${encodeURIComponent(mbox)}`, {
        waitUntil: "domcontentloaded",
      }).catch(() => {});
      await page.waitForTimeout(resolveTimeout(2_000));
      if (await rowFor().isVisible().catch(() => false)) return rowFor();
    }
  }
  throw new Error(`Timed out waiting for email "${subjectText}" in ${mailboxes.join(" / ")}`);
}

module.exports = { roundcubeSsoLogin, roundcubeLogout, waitForEmailInMailbox };
