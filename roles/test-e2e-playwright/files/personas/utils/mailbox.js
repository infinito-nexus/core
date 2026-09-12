/**
 * Read a message back out of the recipient's mailbox, through the mail
 * provider's webmail.
 *
 * Outbound mail configuration fails in ways the sender never notices: an
 * implicit-TLS port announced as STARTTLS, AUTH offered on a listener that has
 * none, or a relay the application can reach but the provider rejects. In every
 * one of those the send call still returns success. The only proof that a
 * setting is right is the message arriving, so these helpers exist for any role
 * whose configuration decides how mail leaves it.
 *
 *   `webmailSsoLogin(page, username, password, baseUrl)`
 *     Drives the provider's webmail login. The webmail redirects to Keycloak on
 *     its own (`oauth_login_redirect`), so this only has to click an SSO control
 *     when one is rendered, then fill the Keycloak form. A caller that already
 *     holds a Keycloak session never sees a form — the redirect answers straight
 *     back into the mailbox — so the helper waits for whichever of the two
 *     surfaces arrives instead of hanging on the form.
 *
 *   `waitForEmailInMailbox(page, baseUrl, subject, timeout)`
 *     Polls INBOX and Junk for a message whose subject matches, and returns its
 *     row. Junk is not a fallback for a broken setup: a test domain publishes no
 *     mail-auth DNS, so a correctly delivered message is legitimately filed
 *     there. Folders are switched by `_mbox` URL, because clicking a folder link
 *     hangs when the row it points at is not actionable yet.
 */

const { performKeycloakLoginForm } = require("./keycloak");
const { gotoOnion } = require("./env");
const { resolveTimeout } = require("../../timeouts");

const MAIL_UI = "#messagelist, .compose, a[href*='_action=compose'], .toolbar";
const SSO_CONTROL = /sso|single sign.?on|login with|openid/i;

const MAILBOXES = ["INBOX", "Junk Mail"];

async function webmailSsoLogin(page, username, password, baseUrl) {
  await gotoOnion(page, `${baseUrl}/`);
  const ssoButton = page
    .getByRole("button", { name: SSO_CONTROL })
    .or(page.getByRole("link", { name: SSO_CONTROL }));
  if (await ssoButton.first().isVisible().catch(() => false)) {
    await ssoButton.first().click({ timeout: resolveTimeout(30_000) });
  }

  const mailUi = page.locator(MAIL_UI).first();
  const usernameField = page
    .getByRole("textbox", { name: /username|email/i })
    .or(page.locator("input[name='username'], input#username"))
    .first();

  await Promise.any([
    mailUi.waitFor({ state: "visible", timeout: resolveTimeout(60_000) }),
    usernameField.waitFor({ state: "visible", timeout: resolveTimeout(60_000) }),
  ]);
  if (await usernameField.isVisible().catch(() => false)) {
    await performKeycloakLoginForm(page, username, password);
  }
  await mailUi.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
}

function messageRow(page, subject) {
  return page
    .locator("#messagelist tbody tr, table.messagelist tbody tr")
    .filter({ hasText: subject })
    .first();
}

async function waitForEmailInMailbox(page, baseUrl, subject, timeout = resolveTimeout(90_000)) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const mailbox of MAILBOXES) {
      await gotoOnion(page, `${baseUrl}/?_task=mail&_mbox=${encodeURIComponent(mailbox)}`, {
        waitUntil: "domcontentloaded",
      }).catch(() => {});
      await page.waitForTimeout(resolveTimeout(2_000));
      if (await messageRow(page, subject).isVisible().catch(() => false)) {
        return messageRow(page, subject);
      }
    }
  }
  throw new Error(
    `Timed out waiting for a message matching "${subject}" in ${MAILBOXES.join(" / ")}`
  );
}

module.exports = { webmailSsoLogin, waitForEmailInMailbox };
