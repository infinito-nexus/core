const { test, expect } = require("@playwright/test");
const { apiFetchOnion, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const nativeOffered = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const registrationOffered = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";

test.use({ ignoreHTTPSErrors: true, serviceWorkers: "block" });

test("login methods: with SSO on the instance config offers only the enabled sign-in methods", async ({ request }) => {
  skipUnlessServiceEnabled("sso");
  const response = await apiFetchOnion(request, `${base}/api`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    data: { query: "{ config { registrationsOpen auth { databaseLogin oauthProviders { id } } } }" },
  });
  expect(response.status(), "the public GraphQL config query must answer").toBe(200);
  const { config } = (await response.json()).data;
  expect(config.auth.oauthProviders.map((provider) => provider.id), "the Keycloak provider must be offered").toContain("keycloak");
  expect(config.auth.databaseLogin, "disable_database_login must follow login.method.native").toBe(nativeOffered);
  expect(config.registrationsOpen, "registrations_open must follow login.method.registration").toBe(registrationOffered);
});

test("login methods: with SSO on the sign-in page shows the Keycloak entry and the form only for the native method", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await gotoOnion(page, `${base}/login`);
  await expect(page.locator("main#main a[href*='/auth/']").first(), "expected the Keycloak entry on /login").toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await expect(page.locator("#password")).toHaveCount(nativeOffered ? 1 : 0);
});
