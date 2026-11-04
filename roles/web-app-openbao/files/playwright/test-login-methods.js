const { test, expect } = require("@playwright/test");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const ssoOffered = process.env.LOGIN_METHOD_SSO_ENABLED === "true";
const directoryOffered = process.env.LOGIN_METHOD_LDAP_ENABLED === "true";

test.use({ ignoreHTTPSErrors: true });

test("login methods: with SSO on the login page lists the OIDC method and opens on it", async ({ page, request }) => {
  skipUnlessServiceEnabled("sso");
  const mounts = await request.get(`${baseUrl}/v1/sys/internal/ui/mounts`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(mounts.status(), "the unauthenticated UI mount listing must answer").toBe(200);
  const listed = Object.keys(((await mounts.json()).data || {}).auth || {});
  expect(listed, "listing_visibility=unauth must name exactly the OIDC mount while the sso method is on").toEqual(
    ssoOffered ? ["oidc/"] : [],
  );
  if (ssoOffered) {
    await gotoOnion(page, `${baseUrl}/ui/vault/auth`, { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("button", { name: /sign in with oidc provider/i }).first(),
      "the login page must open on the OIDC entry without choosing a method",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  }
});

test("login methods: with SSO on the LDAP login answers only while the ldap method is on", async ({ request }) => {
  skipUnlessServiceEnabled("sso");
  const response = await request.post(`${baseUrl}/v1/auth/ldap/login/${encodeURIComponent(adminUsername)}`, {
    data: { password: adminPassword },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  if (response.status() === 200) {
    await request.post(`${baseUrl}/v1/auth/token/revoke-self`, {
      headers: { "X-Vault-Token": (await response.json()).auth.client_token },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
  }
  expect(response.status() === 200, `the LDAP login answered ${response.status()}`).toBe(directoryOffered);
});
