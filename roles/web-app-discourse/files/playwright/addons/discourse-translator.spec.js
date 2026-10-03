const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  normalizeBaseUrl,
  decodeDotenvQuotedValue,
  performKeycloakLoginForm,
  requireDotenvValue,
  gotoOnion,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
const discourseBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.DISCOURSE_BASE_URL, "DISCOURSE_BASE_URL"));
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const expectedEndpoint = decodeDotenvQuotedValue(process.env.DISCOURSE_TRANSLATE_ENDPOINT);
const expectedProvider = decodeDotenvQuotedValue(process.env.DISCOURSE_TRANSLATE_PROVIDER);

async function signInViaOidc(page) {
  await gotoOnion(page, `${discourseBaseUrl}/`);
  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s+with\s+oidc|sign\s*in\s+with\s+sso|single\s+sign[-\s]*on|log\s*in/i })
    .first();
  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click();
  } else {
    await gotoOnion(page, `${discourseBaseUrl}/auth/oidc`).catch(() => {});
  }
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${oidcIssuerUrl})`,
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect back to discourse at ${discourseBaseUrl}`,
    })
    .toContain(discourseBaseUrl);
}

function settingValue(settings, name) {
  const found = settings.find((entry) => entry && entry.setting === name);
  expect(found, `${name} site setting must exist (the discourse-translator plugin must be loaded)`).toBeTruthy();
  return String(found.value);
}

test("discourse-translator: posts are translated through the in-cluster gateway", async ({ page, request }) => {
  skipUnlessAddonEnabled("discourse-translator");
  skipUnlessServiceEnabled("translate");
  test.setTimeout(resolveTimeout(180_000));

  expect(expectedEndpoint, "DISCOURSE_TRANSLATE_ENDPOINT must be set").toBeTruthy();
  expect(expectedProvider, "DISCOURSE_TRANSLATE_PROVIDER must be set").toBeTruthy();

  await page.context().clearCookies();
  await signInViaOidc(page);

  const settings = await page.evaluate(async (base) => {
    const res = await fetch(`${base}/admin/site_settings.json`, {
      headers: { Accept: "application/json" },
      credentials: "include",
    });
    if (!res.ok) return { ok: false, status: res.status };
    const body = await res.json();
    return { ok: true, settings: (body && body.site_settings) || [] };
  }, discourseBaseUrl);

  expect(settings.ok, `expected /admin/site_settings.json to answer as admin (status ${settings.status})`).toBe(true);
  expect(settingValue(settings.settings, "translator_enabled"), "the translator must be switched on").toBe("true");
  expect(settingValue(settings.settings, "translator_provider"), "the provider must be the gateway's dialect").toBe(expectedProvider);
  expect(
    settingValue(settings.settings, "translator_libretranslate_endpoint"),
    "the translator must post to the deployed gateway",
  ).toBe(expectedEndpoint);

  const catalogue = await request.get(`${expectedEndpoint}/languages`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(120_000),
  });
  expect(catalogue.status(), `expected the configured endpoint (${expectedEndpoint}/languages) to answer`).toBe(200);
  expect(Array.isArray(await catalogue.json()), "expected a language catalogue from the gateway").toBe(true);
});
