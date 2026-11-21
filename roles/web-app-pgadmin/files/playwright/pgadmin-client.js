const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const MASTER_PASSWORD_CHECK_PATH = "/browser/master_password";
const MASTER_PASSWORD_PROMPT = /Set Master Password|Unlock Saved Passwords/;

/**
 * Build the headers pgAdmin's own client sends, since pgAdmin checks its CSRF token on GET requests too.
 *
 * Args:
 *   csrf: `{ header, token }` read from `window.pgAdmin.csrf_token_header` and `window.pgAdmin.csrf_token`.
 *   baseUrl: the pgAdmin base URL without a trailing slash; its browser page is the same-origin Referer the strict SSL check demands.
 *
 * Returns:
 *   The request headers.
 */
function csrfHeaders(csrf, baseUrl) {
  return { [csrf.header]: csrf.token, referer: `${baseUrl}/browser/` };
}

/**
 * Args:
 *   page: a Playwright page on pgAdmin's browser UI whose context carries the session.
 *   baseUrl: the pgAdmin base URL without a trailing slash.
 *
 * Returns:
 *   The Playwright API response, redirects not followed.
 */
async function requestUserList(page, baseUrl) {
  await page.waitForFunction(() => Boolean(window.pgAdmin && window.pgAdmin.csrf_token), null, {
    timeout: resolveTimeout(30_000),
  });
  const csrf = await page.evaluate(() => ({ header: window.pgAdmin.csrf_token_header, token: window.pgAdmin.csrf_token }));
  return page.request.get(`${baseUrl}/user_management/user/`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    headers: csrfHeaders(csrf, baseUrl),
  });
}

/**
 * Args:
 *   response: a Playwright response.
 *
 * Returns:
 *   Whether it answers the master password check pgAdmin posts once its browser UI has loaded.
 */
function isMasterPasswordCheck(response) {
  return response.request().method() === "POST" && new URL(response.url()).pathname.endsWith(MASTER_PASSWORD_CHECK_PATH);
}

/**
 * Args:
 *   body: the parsed JSON body of the master password check.
 *
 * Returns:
 *   Whether pgAdmin holds no encryption key for the account and so raises its master password dialog.
 */
function promptsForMasterPassword(body) {
  return Boolean(body && body.data && body.data.present === false);
}

/**
 * Listen for pgAdmin's master password check; call it before the sign-in that loads the browser UI.
 *
 * Args:
 *   page: the Playwright page that signs in.
 *
 * Returns:
 *   An async function that waits for the check and, when pgAdmin raised its dialog, leaves it with Cancel as an OAuth2 account without saved server passwords does, then waits until the dialog is gone.
 */
function watchMasterPasswordPrompt(page) {
  const check = page.waitForResponse(isMasterPasswordCheck, { timeout: resolveTimeout(120_000) });
  check.catch(() => {});
  return async () => {
    if (!promptsForMasterPassword(await (await check).json())) return;
    const dialog = page.getByRole("dialog").filter({ hasText: MASTER_PASSWORD_PROMPT });
    await expect(dialog, "pgAdmin MUST ask an account without an encryption key for a master password").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click({ timeout: resolveTimeout(10_000) });
    await expect(dialog, "Cancel MUST close the master password dialog").toBeHidden({ timeout: resolveTimeout(10_000) });
  };
}

module.exports = { csrfHeaders, isMasterPasswordCheck, promptsForMasterPassword, requestUserList, watchMasterPasswordPrompt };
