const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const expectApiKey =
  String(process.env.INTEGRATION_OPENAI_EXPECT_API_KEY || "").toLowerCase() === "true";

test("integration integration_openai: Nextcloud is configured and coupled to the openwebui/flowise backend", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_openai");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await page.goto(
      new URL("settings/admin/ai", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const openaiSection = page.locator("#openai_prefs").first();
    await expect(
      openaiSection,
      "the integration_openai admin section (#openai_prefs) must render on settings/admin/ai when the addon is enabled — its absence means the app was never installed/enabled and the coupling failed to provision"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const serviceUrlField = openaiSection
      .locator("#openai-url")
      .or(openaiSection.getByRole("textbox", { name: /service url/i }))
      .first();
    await expect(
      serviceUrlField,
      "the integration_openai admin section must expose the Service URL field (#openai-url)"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const configuredUrl = ((await serviceUrlField.inputValue().catch(() => "")) || "").trim();
    expect(
      configuredUrl.length,
      "the Service URL must be populated from config:app:set so the openwebui/flowise partner endpoint is wired"
    ).toBeGreaterThan(0);

    expect(
      configuredUrl,
      "the Service URL must be a valid http(s) URL pointing at the OpenAI-compatible AI backend (web-app-openwebui / web-app-flowise base URL)"
    ).toMatch(/^https?:\/\/.+/i);

    const configuredHost = new URL(configuredUrl).host;
    expect(
      configuredHost,
      "the Service URL host must be the AI backend partner (openwebui chat.ai.* or flowise flow.ai.*), proving the config:app:set actually wired the partner endpoint rather than a placeholder"
    ).toMatch(/^(chat|flow)\.ai\./i);
    expect(
      configuredHost,
      "the Service URL must point at the partner backend, distinct from the Nextcloud host — proving real cross-host coupling, not a self-pointing/unconfigured value"
    ).not.toBe(new URL(shared.env.nextcloudBaseUrl).host);

    if (expectApiKey) {
      const apiKeyField = openaiSection
        .locator("#openai-api-key")
        .or(openaiSection.getByRole("textbox", { name: /api key/i }))
        .first();
      await expect(
        apiKeyField,
        "the integration_openai admin section must expose the API key field (#openai-api-key)"
      ).toBeVisible({ timeout: resolveTimeout(60_000) });

      const configuredApiKey = ((await apiKeyField.inputValue().catch(() => "")) || "").trim();
      expect(
        configuredApiKey.length,
        "the API key must be provisioned (config:app:set integration_openai api_key) so the Flowise/LiteLLM master-key-protected /v1 endpoint authenticates instead of returning 401"
      ).toBeGreaterThan(0);
    }
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
