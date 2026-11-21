const { test, expect } = require("@playwright/test");
const { apiFetchOnion, gotoOnion, inAppLogout, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { signInThroughOidc, uiSessionToken } = require("./_oidc-sign-in");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");

test.use({ ignoreHTTPSErrors: true });

function tokenCall(request, path, method, token) {
  return apiFetchOnion(request, `${baseUrl}/v1/auth/token/${path}`, {
    method,
    headers: { "X-Vault-Token": token },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
}

test("administrator: the UI logout control ends the OpenBao session", async ({ page, request }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));
  await signInThroughOidc(page, adminUsername, adminPassword);
  const token = await uiSessionToken(page);
  expect(token, "the OIDC login must leave a token OpenBao accepts in the UI").toBeTruthy();

  try {
    await inAppLogout(page);
    await expect
      .poll(async () => (await tokenCall(request, "lookup-self", "GET", token)).status(), {
        timeout: resolveTimeout(30_000),
        message: "after the logout OpenBao must reject the token the UI held",
      })
      .toBe(403);
    await gotoOnion(page, `${baseUrl}/ui/vault/secrets`, { waitUntil: "domcontentloaded" });
    await expect(page, "after the logout the UI must ask for a login again").toHaveURL(/\/ui\/vault\/auth/, {
      timeout: resolveTimeout(60_000),
    });
  } finally {
    await tokenCall(request, "revoke-self", "POST", token);
  }
});
