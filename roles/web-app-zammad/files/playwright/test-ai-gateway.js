const { test, expect, request } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue } = require("./personas");

const expectedBaseUrl = decodeDotenvQuotedValue(process.env.ZAMMAD_LITELLM_BASE_URL || "").trim();
const expectedModel = decodeDotenvQuotedValue(process.env.ZAMMAD_LITELLM_MODEL || "").trim();

exports.register = function (shared) {
  test("administrator: Smart Assist answers a prompt through the in-cluster LiteLLM gateway", async () => {
    shared.skipUnlessServiceEnabled("litellm");
    test.setTimeout(resolveTimeout(180_000));

    expect(expectedBaseUrl, "ZAMMAD_LITELLM_BASE_URL must be rendered into playwright.env").toBeTruthy();
    expect(expectedModel, "ZAMMAD_LITELLM_MODEL must be rendered into playwright.env").toBeTruthy();

    const api = await request.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: {
        Authorization: `Basic ${Buffer.from(
          `${shared.env.adminApiUsername}:${shared.env.adminApiPassword}`
        ).toString("base64")}`,
        "Content-Type": "application/json",
      },
    });

    try {
      const settingsResp = await api.get(`${shared.env.zammadBaseUrl}/api/v1/settings`);
      expect(
        settingsResp.status(),
        `GET /api/v1/settings must succeed for the admin bot: ${await settingsResp.text()}`
      ).toBe(200);

      const settings = await settingsResp.json();
      const byName = (name) =>
        (Array.isArray(settings) ? settings : []).find((entry) => entry && entry.name === name);

      const providerFlag = byName("ai_provider");
      expect(
        providerFlag && providerFlag.state_current && providerFlag.state_current.value,
        "ai_provider must be true, otherwise the deploy never wrote a provider and Smart Assist is dark"
      ).toBeTruthy();

      const providerConfig = byName("ai_provider_config");
      const config =
        (providerConfig && providerConfig.state_current && providerConfig.state_current.value) || {};

      expect(
        config.provider,
        "the provider must be the OpenAI-compatible one, not a vendor-hosted provider"
      ).toBe("custom_open_ai");

      expect(
        config.url,
        "ai_provider_config.url must be the gateway base URL the deploy wrote"
      ).toBe(expectedBaseUrl);

      expect(
        config.model,
        "ai_provider_config.model must be the model the gateway actually serves"
      ).toBe(expectedModel);

      const configuredHost = new URL(config.url).hostname;
      expect(
        configuredHost,
        "the gateway host must carry no dot; a dotted host is completed by the container dns-search suffix and resolves through the public ingress, sending prompts out of the deployment"
      ).not.toContain(".");
      expect(
        configuredHost,
        "the gateway host must differ from the Zammad host, proving a real cross-service endpoint rather than a self-pointing placeholder"
      ).not.toBe(new URL(shared.env.zammadBaseUrl).hostname);

      const toolsResp = await api.get(`${shared.env.zammadBaseUrl}/api/v1/ai_text_tools`);
      expect(
        toolsResp.status(),
        `GET /api/v1/ai_text_tools must succeed: ${await toolsResp.text()}`
      ).toBe(200);

      const tools = await toolsResp.json();
      const tool = (Array.isArray(tools) ? tools : []).find((entry) => entry && entry.active);
      expect(
        tool,
        "Zammad seeds its writing-assistant text tools; none being active means the AI seeds never ran"
      ).toBeTruthy();

      const completion = await api.post(
        `${shared.env.zammadBaseUrl}/api/v1/ai_assistance/text_tools/${tool.id}`,
        { data: { input: "teh qick brown fox jump over teh lazy dog" }, timeout: resolveTimeout(120_000) }
      );
      expect(
        completion.status(),
        `POST /api/v1/ai_assistance/text_tools must succeed; a 4xx/5xx means the gateway rejected the virtual key or is unreachable: ${await completion.text()}`
      ).toBe(200);

      const body = await completion.json();
      expect(
        String(body.output || "").trim().length,
        "the gateway must return a non-empty completion, proving the prompt was answered inside the deployment"
      ).toBeGreaterThan(0);
    } finally {
      await api.dispose().catch(() => {});
    }
  });
};
