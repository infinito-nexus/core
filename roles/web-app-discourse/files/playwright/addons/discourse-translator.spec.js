const { test, expect, request: apiRequest } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, requireDotenvValue } = require("../personas");
const { signInAsAdmin } = require("../sign-in");

test.use({ ignoreHTTPSErrors: true });

const discourseBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.DISCOURSE_BASE_URL, "DISCOURSE_BASE_URL"));
const expectedEndpoint = decodeDotenvQuotedValue(process.env.DISCOURSE_TRANSLATE_ENDPOINT);
const expectedProvider = decodeDotenvQuotedValue(process.env.DISCOURSE_TRANSLATE_PROVIDER);

function settingValue(settings, name) {
  const found = settings.find((entry) => entry && entry.setting === name);
  expect(found, `${name} site setting must exist (the discourse-translator plugin must be loaded)`).toBeTruthy();
  return String(found.value);
}

test("discourse-translator: posts are translated through the in-cluster gateway", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-translator");
  skipUnlessServiceEnabled("translate");
  test.setTimeout(resolveTimeout(180_000));

  expect(expectedEndpoint, "DISCOURSE_TRANSLATE_ENDPOINT must be set").toBeTruthy();
  expect(expectedProvider, "DISCOURSE_TRANSLATE_PROVIDER must be set").toBeTruthy();

  await page.context().clearCookies();
  await signInAsAdmin(page);

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

  const direct = await apiRequest.newContext({ ignoreHTTPSErrors: true });
  try {
    const catalogue = await direct.get(`${expectedEndpoint}/languages`, {
      failOnStatusCode: false,
      timeout: resolveTimeout(120_000),
    });
    expect(catalogue.status(), `expected the configured endpoint (${expectedEndpoint}/languages) to answer`).toBe(200);
    expect(Array.isArray(await catalogue.json()), "expected a language catalogue from the gateway").toBe(true);
  } finally {
    await direct.dispose();
  }
});
