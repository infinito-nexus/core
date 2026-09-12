const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon ai-engine: WordPress answers a prompt through the in-cluster LiteLLM gateway", async ({ browser }) => {
  skipUnlessAddonEnabled("ai-engine");
  test.setTimeout(resolveTimeout(180_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/admin.php?page=mwai_settings`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });

    const bootstrap = await page.waitForFunction(
      () => (window.mwai && window.mwai.rest_nonce ? window.mwai : null),
      undefined,
      { timeout: resolveTimeout(60_000) }
    ).then((handle) => handle.jsonValue());

    expect(
      bootstrap.api_url,
      "the AI Engine admin bundle must expose its REST base, otherwise the plugin never loaded"
    ).toBeTruthy();

    const envs = (bootstrap.options && bootstrap.options.ai_envs) || [];
    const managed = envs.find((entry) => entry && entry.id === "infinito-litellm");
    expect(
      managed,
      "the deploy must have merged the 'infinito-litellm' environment into mwai_options.ai_envs"
    ).toBeTruthy();

    expect(
      managed.type,
      "the managed environment must use the OpenAI-compatible 'custom' engine, not a vendor engine"
    ).toBe("custom");

    const endpointHost = new URL(managed.endpoint).host.split(":")[0];
    expect(
      endpointHost,
      "the managed endpoint must be the in-cluster litellm service name — a dotted host would resolve through the public ingress and leave the deployment"
    ).not.toContain(".");
    expect(
      endpointHost,
      "the managed endpoint must point at the svc-ai-litellm gateway, not at WordPress itself"
    ).not.toBe(new URL(shared.env.wpBaseUrl).host);

    expect(
      bootstrap.options.ai_default_env,
      "the gateway environment must be the site default, so no surface falls back to a third-party provider"
    ).toBe("infinito-litellm");

    const completion = await context.request.post(`${bootstrap.api_url}/ai/completions`, {
      headers: {
        "X-WP-Nonce": bootstrap.rest_nonce,
        "Content-Type": "application/json",
      },
      data: {
        message: "Reply with the single word: pong",
        env: "infinito-litellm",
        model: bootstrap.options.ai_default_model,
        stream: false,
      },
      timeout: resolveTimeout(120_000),
    });

    expect(
      completion.status(),
      "POST mwai/v1/ai/completions must succeed — a non-200 means the virtual key or the gateway endpoint is wrong"
    ).toBe(200);

    const body = await completion.json();
    expect(
      body.success,
      `the completion must report success; got: ${JSON.stringify(body).slice(0, 400)}`
    ).toBe(true);
    expect(
      String(body.data || "").trim().length,
      "the gateway must return a non-empty completion, proving the prompt was answered inside the deployment"
    ).toBeGreaterThan(0);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
