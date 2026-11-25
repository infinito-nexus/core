const { test, expect } = require("@playwright/test");
const {
  apiFetchOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  inAppLogout,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");
const { resolveTimeout } = require("./timeouts");
const { signInThroughOidc, uiSessionToken } = require("./_oidc-sign-in");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const passwordMount = decodeDotenvQuotedValue(process.env.OPENBAO_PASSWORD_AUTH_MOUNT || "");

test.use({ ignoreHTTPSErrors: true });

function tokenCall(request, path, method, token) {
  return apiFetchOnion(request, `${baseUrl}/v1/auth/token/${path}`, {
    method,
    headers: { "X-Vault-Token": token },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
}

/**
 * Args:
 *   page: Playwright page that signs in through the OIDC method, and so through Keycloak, when the deployment provisions no password method, and ends with the UI storage cleared while the token stays valid.
 *   request: Playwright API context that signs in through the password method the deployment provisions.
 *
 * Returns:
 *   An OpenBao token of the platform administrator.
 */
async function administratorToken(page, request) {
  if (passwordMount) {
    const response = await apiFetchOnion(
      request,
      `${baseUrl}/v1/auth/${passwordMount}/login/${encodeURIComponent(adminUsername)}`,
      { method: "POST", data: { password: adminPassword }, failOnStatusCode: false, timeout: resolveTimeout(30_000) },
    );
    expect(response.status(), `the ${passwordMount} method must accept the administrator`).toBe(200);
    return (await response.json()).auth.client_token;
  }
  await signInThroughOidc(page, adminUsername, adminPassword);
  const token = await uiSessionToken(page);
  await page.evaluate(() => window.localStorage.clear());
  return token;
}

test("administrator: the Token method stays on the login page and signs an administrator token in", async ({ page, request }) => {
  test.setTimeout(resolveTimeout(240_000));
  const token = await administratorToken(page, request);
  expect(token, "the administrator must hold a token to sign in with").toBeTruthy();

  try {
    await gotoOnion(page, `${baseUrl}/ui/vault/auth?with=token`, { waitUntil: "domcontentloaded" });
    const field = page.locator("#auth-form input[name='token']");
    await expect(field, "the Token method must stay on the login page").toBeEditable({ timeout: resolveTimeout(60_000) });
    await field.fill(token);
    await page.locator("#auth-submit").click();
    await expect(page.locator(".hds-side-nav__home-link"), "the token must open the signed-in interface").toBeVisible({
      timeout: resolveTimeout(60_000),
    });

    const { data } = await (await tokenCall(request, "lookup-self", "GET", token)).json();
    expect(
      [...(data.policies || []), ...(data.identity_policies || [])],
      "the token signed in through the Token method must carry the administrator policy",
    ).toContain("administrator");

    await inAppLogout(page);
    await expect
      .poll(async () => (await tokenCall(request, "lookup-self", "GET", token)).status(), {
        timeout: resolveTimeout(30_000),
        message: "after the logout OpenBao must reject the token the Token method signed in",
      })
      .toBe(403);
  } finally {
    await tokenCall(request, "revoke-self", "POST", token);
  }
});
