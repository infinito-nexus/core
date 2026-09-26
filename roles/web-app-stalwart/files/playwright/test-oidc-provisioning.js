const { test, expect } = require("@playwright/test");

const { safeSkipUnlessEnabled, gotoOnion } = require("./personas");
const { isSplitRealmOidc, resolveTimeout } = require("./timeouts");
const { roundcubeSsoLogin, roundcubeLogout, sendMail, waitForEmailInMailbox } = require("./webmail");
const {
  webmailBaseUrl,
  mapacheEmail,
  mapacheUsername,
  mapachePassword,
  biberEmail,
  biberUsername,
  biberPassword,
} = require("./env");

// mapache is declared in web-app-keycloak/meta/users.yml with accounts:
// ["identity"] — the directory registers it, lookup('stalwart_users') filters
// it out, so Ansible never creates its mail account. Everything below is only
// reachable if services.sso.oidc.enable_user_creation provisions the account
// on first login, which is the path every user who arrives after the deploy
// takes.
test("stalwart: an OIDC user the deploy never provisioned can sign in", async ({ page }) => {
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  safeSkipUnlessEnabled("sso");

  expect(webmailBaseUrl, "WEBMAIL_BASE_URL must be set").toBeTruthy();
  expect(mapacheUsername, "MAPACHE_USERNAME must be set").toBeTruthy();
  expect(mapachePassword, "MAPACHE_PASSWORD must be set").toBeTruthy();

  await roundcubeSsoLogin(page, mapacheUsername, mapachePassword);

  await gotoOnion(page, `${webmailBaseUrl}/?_task=mail&_mbox=INBOX`);
  await expect(
    page.locator("#messagelist, .messagelist, [id*='messagelist']").first(),
    "a mailbox the mail server created on demand must render for the OIDC user",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });

  // An IMAP session opened against a missing account leaves Roundcube on its
  // own error surface instead of the mail task, so assert we are not there.
  await expect(
    page.locator(".error, #message.error, .boxerror"),
    "Roundcube must not surface an authentication or mailbox error",
  ).toHaveCount(0);

  await roundcubeLogout(page);
});

// Signing in only proves the directory accepted the credentials. Delivery
// proves the account Stalwart created is a real mailbox with a routable
// address, which is what email_by_username has to get right.
test("stalwart: the auto-provisioned OIDC user sends mail that reaches biber", async ({ browser }) => {
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  safeSkipUnlessEnabled("sso");

  expect(mapacheEmail, "MAPACHE_EMAIL must be set").toBeTruthy();
  expect(biberEmail, "BIBER_EMAIL must be set").toBeTruthy();

  const subject = `mapache-to-biber-${Date.now()}`;

  const senderContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const senderPage = await senderContext.newPage();
  try {
    await roundcubeSsoLogin(senderPage, mapacheUsername, mapachePassword);
    await sendMail(senderPage, biberEmail, subject, "Sent by an account nobody provisioned.");
  } finally {
    await senderContext.close();
  }

  const recipientContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const recipientPage = await recipientContext.newPage();
  try {
    await roundcubeSsoLogin(recipientPage, biberUsername, biberPassword);
    const row = await waitForEmailInMailbox(
      recipientPage,
      webmailBaseUrl,
      subject,
      resolveTimeout(90_000),
    );
    await expect(row, `biber must receive ${subject} from ${mapacheEmail}`).toBeVisible();
  } finally {
    await recipientContext.close();
  }
});
