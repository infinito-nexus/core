const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const CONSOLE_FORM = "input[name='accessKey'], input[name='username'], input#accessKey, input#username";
const IDENTITY_PROVIDER_ENTRY = /\bsso\b|log\s*in\s+with|sign\s*in\s+with|continue\s+with/i;

test("login methods: with SSO on the Console sign-in names Keycloak as its only identity provider and offers no switched-off entry", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const consoleBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.MINIO_CONSOLE_URL, "MINIO_CONSOLE_URL"));
  const keycloakAuth = `${normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"))}/protocol/openid-connect/auth`;
  await page.context().clearCookies();

  const strategy = await page.request.get(`${consoleBaseUrl}/api/v1/login`, { timeout: resolveTimeout(30_000) });
  expect(strategy.status(), "the Console must answer GET /api/v1/login with its sign-in strategy").toBe(200);
  const redirectRules = (await strategy.json()).redirectRules || [];
  for (const rule of redirectRules) {
    expect(
      String(rule.redirect || ""),
      `every identity provider the Console offers must be Keycloak, got ${rule.displayName || "an unnamed rule"}`,
    ).toContain(keycloakAuth);
  }

  await gotoOnion(page, `${consoleBaseUrl}/login`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator(CONSOLE_FORM).first(),
    "the root break-glass form must stay on the Console sign-in, login.method.native has no MinIO switch",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  await expect(
    page.getByRole("link", { name: /sign\s*up|register|create\s+(an\s+)?account/i }),
    "login.method.registration is off, so no registration entry may render",
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /passkey|security\s+key|webauthn/i }),
    "MinIO has no passkey method, so no passkey entry may render",
  ).toHaveCount(0);
  const identityProviderEntries = page.getByRole("button", { name: IDENTITY_PROVIDER_ENTRY });
  if (redirectRules.length === 0) {
    await expect(
      identityProviderEntries,
      "without a Console redirect rule no identity provider entry may render",
    ).toHaveCount(0);
  } else {
    await expect(
      identityProviderEntries.first(),
      "the Console names a redirect rule, so its Keycloak entry must render",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
  }
});
