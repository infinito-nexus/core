const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { AUTH_PATH, CALLBACK_PATH, signInThroughOidc } = require("./_oidc-sign-in");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminFullName = decodeDotenvQuotedValue(process.env.ADMIN_FULL_NAME);
const emailMetadataKey = decodeDotenvQuotedValue(process.env.OIDC_CLAIM_EMAIL);
const nameMetadataKey = decodeDotenvQuotedValue(process.env.OIDC_CLAIM_NAME);

test.use({ ignoreHTTPSErrors: true });

test("oidc: the browser can reach the auth_url endpoint the login form depends on", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${baseUrl}${AUTH_PATH}`, { waitUntil: "domcontentloaded" });

  const probe = await page.evaluate(async (callbackPath) => {
    try {
      const response = await fetch("/v1/auth/oidc/oidc/auth_url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: "", redirect_uri: `${window.location.origin}${callbackPath}` }),
      });
      const text = await response.text();
      return { ok: response.ok, status: response.status, body: text.slice(0, 400) };
    } catch (err) {
      return { ok: false, status: 0, body: `fetch threw: ${err && err.message}` };
    }
  }, CALLBACK_PATH);

  expect(
    probe.status,
    `auth_url request from the browser failed (status ${probe.status}): ${probe.body}`,
  ).toBe(200);
  expect(
    probe.body,
    "auth_url must carry a Keycloak authorization endpoint",
  ).toContain("openid-connect/auth");
});

test("oidc: the administrator signs in through Keycloak and lands in the OpenBao UI", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));
  await signInThroughOidc(page, adminUsername, adminPassword);

  const meta = await page.evaluate(async () => {
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
      if (response.ok) return (await response.json()).data.meta || {};
    }
    return null;
  });
  expect(meta, "the OpenBao UI must hold the token the OIDC login issued").not.toBeNull();
  expect(
    meta[emailMetadataKey],
    `the OIDC role's claim_mappings MUST copy the email claim into the token metadata (meta: ${JSON.stringify(meta)})`,
  ).toBe(adminEmail);
  expect(
    meta[nameMetadataKey],
    `the OIDC role's claim_mappings MUST copy the name claim into the token metadata (meta: ${JSON.stringify(meta)})`,
  ).toBe(adminFullName);
});
