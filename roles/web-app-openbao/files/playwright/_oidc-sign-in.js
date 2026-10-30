const { expect } = require("@playwright/test");
const { gotoOnion, normalizeBaseUrl, performKeycloakLogin, requireDotenvValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const AUTH_PATH = "/ui/vault/auth?with=oidc";
const CALLBACK_PATH = "/ui/vault/auth/oidc/oidc/callback";

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const issuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");

/**
 * Args:
 *   page: Playwright page without an OpenBao session; ends on the OpenBao UI, signed in through the OIDC method and the Keycloak popup.
 *   username: Keycloak login of the persona.
 *   password: Keycloak password of the persona.
 */
async function signInThroughOidc(page, username, password) {
  await page.context().clearCookies();

  if (issuerUrl) {
    const warmup = await page.context().newPage();
    await gotoOnion(warmup, issuerUrl, { waitUntil: "domcontentloaded" }).catch(() => {});
    await warmup.close();
  }

  await gotoOnion(page, `${baseUrl}${AUTH_PATH}`, { waitUntil: "domcontentloaded" });

  const submit = page.getByRole("button", { name: /sign in with oidc provider/i }).first();
  await expect(submit, "the OIDC submit button must render").toBeVisible({
    timeout: resolveTimeout(60_000),
  });

  await expect
    .poll(
      async () =>
        page.evaluate(async (callbackPath) => {
          try {
            const response = await fetch("/v1/auth/oidc/oidc/auth_url", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                role: "",
                redirect_uri: `${window.location.origin}${callbackPath}`,
              }),
            });
            return response.status;
          } catch {
            return 0;
          }
        }, CALLBACK_PATH),
      {
        timeout: resolveTimeout(60_000),
        message: "the auth_url endpoint the OIDC form depends on never became reachable",
      },
    )
    .toBe(200);

  let popup = null;
  for (let attempt = 1; attempt <= 4 && !popup; attempt += 1) {
    const popupPromise = page
      .waitForEvent("popup", { timeout: resolveTimeout(15_000) })
      .catch(() => null);
    await submit.click({ timeout: resolveTimeout(15_000) });
    popup = await popupPromise;
  }
  expect(popup, "clicking the OIDC submit button must open the provider popup").toBeTruthy();

  await popup.waitForURL(/openid-connect\/auth/, { timeout: resolveTimeout(60_000) });
  expect(popup.url(), "the popup must reach the Keycloak authorization endpoint").toContain(
    "openid-connect/auth",
  );

  await performKeycloakLogin(popup, username, password, canonicalDomain);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "expected the parent page to leave the OpenBao auth surface after the OIDC exchange",
    })
    .not.toContain("/ui/vault/auth");
}

/**
 * Args:
 *   page: Playwright page signed in to the OpenBao UI.
 *
 * Returns:
 *   The token the UI keeps in its browser storage that OpenBao still accepts, or null.
 */
async function uiSessionToken(page) {
  return page.evaluate(async () => {
    for (const key of Object.keys(window.localStorage)) {
      if (!key.startsWith("vault-")) continue;
      let stored;
      try {
        stored = JSON.parse(window.localStorage.getItem(key));
      } catch {
        continue;
      }
      if (!stored || typeof stored.token !== "string") continue;
      const response = await fetch("/v1/auth/token/lookup-self", { headers: { "X-Vault-Token": stored.token } });
      if (response.ok) return stored.token;
    }
    return null;
  });
}

module.exports = { AUTH_PATH, CALLBACK_PATH, signInThroughOidc, uiSessionToken };
