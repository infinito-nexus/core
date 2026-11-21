const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceDisabled } = require("./service-gating");

const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

async function openLoginDialog(shared, page, roomName) {
  await gotoOnion(page, `${shared.env.appBaseUrl}/${roomName}`, { waitUntil: "domcontentloaded" });
  const join = page
    .locator('[data-testid="prejoin.joinMeeting"]')
    .or(page.getByRole("button", { name: /join meeting|beitreten/i }))
    .first();
  await expect(join, "the prejoin join control must render").toBeVisible({ timeout: resolveTimeout(60_000) });
  await join.click();
  const username = page.locator('input[name="username"], #login-dialog-username').first();
  await expect(username, "Jitsi MUST ask for credentials when prosody authenticates against LDAP").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  return username;
}

async function submitCredentials(page, usernameField, username, password) {
  await usernameField.fill(username);
  await page.locator('input[name="password"], #login-dialog-password').first().fill(password);
  await page.locator("#modal-dialog-ok-button").first().click();
}

exports.register = function (shared) {
  test("biber: prosody admits biber with the directory password over LDAP", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    const usernameField = await openLoginDialog(shared, page, "e2e-ldap-auth-room");
    await submitCredentials(page, usernameField, biberUsername, biberPassword);
    await expect(
      usernameField,
      "LDAP_FILTER MUST find biber by LDAP.USER.ATTRIBUTES.ID, so the login dialog closes",
    ).toBeHidden({ timeout: resolveTimeout(60_000) });
  });

  test("biber: prosody rejects biber with a wrong password over LDAP", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    const usernameField = await openLoginDialog(shared, page, "e2e-ldap-reject-room");
    await submitCredentials(page, usernameField, biberUsername, `${biberPassword}-wrong`);
    await page.waitForTimeout(resolveTimeout(5_000));
    await expect(
      page.locator('input[name="password"], #login-dialog-password').first(),
      "a wrong password MUST keep the login dialog open",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
  });
};
