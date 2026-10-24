const { expect } = require("@playwright/test");

const { performKeycloakLoginForm, gotoOnion, waitForEmailInMailbox } = require("./personas");
const { webmailBaseUrl, expectedOidcAuthUrl } = require("./env");
const { resolveTimeout } = require("./timeouts");

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

/**
 * Args:
 *   page: Playwright page on a Roundcube view; resolves once its init ran and none of its requests is in flight.
 */
async function roundcubeSettled(page) {
  await page.waitForFunction(
    () => Boolean(window.rcmail && window.rcmail.loaded && window.jQuery && window.jQuery.active === 0),
    null,
    { timeout: resolveTimeout(30_000) },
  );
}

async function sendMail(page, recipient, subject, body) {
  await roundcubeSettled(page);
  await gotoOnion(page, `${webmailBaseUrl}/?_task=mail&_action=compose`);
  await roundcubeSettled(page);
  await page.locator("#_to, input[name='_to']").first().fill(recipient);
  await page.locator("#compose-subject, input[name='_subject']").first().fill(subject);
  await page.locator("#composebody, textarea[name='_message'], [contenteditable='true']").first().fill(body);
  await page.locator(".formbuttons .send, button.send, a.send").first().click();
  const sendError = page.locator("#messagestack .error, .toast .error, .toast-error").first();
  await expect
    .poll(
      async () => {
        if (await sendError.isVisible()) return `send error: ${await sendError.textContent()}`;
        return page.url().includes("_action=compose") ? "still composing" : "sent";
      },
      { timeout: resolveTimeout(30_000), message: `Roundcube must send the message to ${recipient}` },
    )
    .toBe("sent");
}

async function roundcubeLogout(page) {
  const logout = page.locator("a[href*='_task=logout'], a[href*='logout'], a.logout")
    .or(page.getByRole("link", { name: /logout|sign out/i }));
  await expect(logout.first(), "Roundcube logout control must be present").toBeVisible({
    timeout: resolveTimeout(10_000),
  });
  await logout.first().click();
}

module.exports = { roundcubeSsoLogin, roundcubeLogout, sendMail, waitForEmailInMailbox };
