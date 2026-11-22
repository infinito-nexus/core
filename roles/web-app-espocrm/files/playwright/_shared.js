const { expect } = require("@playwright/test");

/**
 * Args:
 *   page: the page that just completed a login.
 *   timeout: milliseconds to wait, already resolved for the target.
 *   message: what the caller is waiting for, shown when the wait expires.
 */
async function awaitSession(page, timeout, message) {
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          Object.keys(localStorage).some((name) => /user-auth$/.test(name)),
        ),
      { timeout, message },
    )
    .toBe(true);
}

/**
 * Args:
 *   page: a page that holds an EspoCRM session in localStorage.
 *   method: HTTP verb of the API call.
 *   path: route below `api/v1/`.
 *   data: JSON body, or undefined for none.
 */
async function espoApi(page, method, path, data) {
  return page.evaluate(
    async ([verb, route, body]) => {
      const key = Object.keys(localStorage).find((name) => /user-auth$/.test(name));
      const raw = key ? localStorage.getItem(key) : "";
      const auth = raw.startsWith('"') ? JSON.parse(raw) : raw;
      const response = await fetch(`api/v1/${route}`, {
        method: verb,
        headers: {
          "Content-Type": "application/json",
          "Espo-Authorization": auth,
          "Espo-Authorization-By-Token": "true",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return {
        status: response.status,
        json: response.ok ? await response.json() : null,
        error: response.ok ? "" : response.headers.get("X-Status-Reason") || (await response.text()).slice(0, 200),
      };
    },
    [method, path, data],
  );
}

/**
 * Args:
 *   response: a Playwright response.
 * Returns:
 *   whether it answers the OIDC code exchange, the App/user call whose credentials are
 *   `**oidc:<code>`, and not a revalidation of the token stored in localStorage.
 */
function isOidcCodeExchange(response) {
  if (!response.url().includes("/api/v1/App/user")) return false;
  const credentials = response.request().headers()["espo-authorization"] || "";
  return Buffer.from(credentials, "base64").toString("utf8").startsWith("**oidc:");
}

module.exports = { awaitSession, espoApi, isOidcCodeExchange };
