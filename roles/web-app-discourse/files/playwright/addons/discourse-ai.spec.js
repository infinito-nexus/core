const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const {
  normalizeBaseUrl,
  decodeDotenvQuotedValue,
  performKeycloakLoginForm,
  gotoOnion,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const discourseBaseUrl = normalizeBaseUrl(process.env.DISCOURSE_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const expectedEndpoint = decodeDotenvQuotedValue(process.env.DISCOURSE_LITELLM_CHAT_ENDPOINT);
const expectedModel = decodeDotenvQuotedValue(process.env.DISCOURSE_LITELLM_MODEL);
const expectedDisplayName = decodeDotenvQuotedValue(process.env.DISCOURSE_AI_LLM_DISPLAY_NAME);

async function signInViaOidc(page) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${discourseBaseUrl}/`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s+with\s+oidc|sign\s*in\s+with\s+sso|continue\s+with\s+oidc|continue\s+with\s+sso|single\s+sign[-\s]*on|log\s*in|sign\s*up/i })
    .first();

  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click();
  } else {
    await gotoOnion(page, `${discourseBaseUrl}/auth/oidc`).catch(() => {});
  }

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect back to discourse at ${discourseBaseUrl}`,
    })
    .toContain(discourseBaseUrl);
}

function settingValue(settings, name) {
  const found = settings.find((s) => s && s.setting === name);
  expect(found, `${name} site setting must exist (discourse-ai plugin loaded)`).toBeTruthy();
  return String(found.value);
}

test("discourse-ai: the Discourse AI model routes prompts through the in-cluster gateway and answers one", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-ai");
  test.setTimeout(resolveTimeout(180_000));

  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(discourseBaseUrl, "DISCOURSE_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(expectedEndpoint, "DISCOURSE_LITELLM_CHAT_ENDPOINT must be set").toBeTruthy();
  expect(expectedModel, "DISCOURSE_LITELLM_MODEL must be set").toBeTruthy();
  expect(expectedDisplayName, "DISCOURSE_AI_LLM_DISPLAY_NAME must be set").toBeTruthy();

  const discourseHost = new URL(discourseBaseUrl).host;

  try {
    await page.context().clearCookies();
    await signInViaOidc(page);

    await expect(page.locator("body")).toContainText(
      /topic|category|welcome|latest|discourse/i,
      { timeout: resolveTimeout(60_000) },
    );

    const llmIndex = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/plugins/discourse-ai/ai-llms.json`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      if (!res.ok) return { ok: false, status: res.status };
      const body = await res.json();
      return { ok: true, llms: (body && body.ai_llms) || [] };
    }, discourseBaseUrl);

    expect(
      llmIndex.ok,
      `expected /admin/plugins/discourse-ai/ai-llms.json to be reachable as admin (status ${llmIndex.status}); a 404 means the bundled discourse-ai plugin never loaded`,
    ).toBe(true);

    const llm = llmIndex.llms.find((entry) => entry && entry.display_name === expectedDisplayName);
    expect(
      llm,
      `the LLM row "${expectedDisplayName}" must be registered (the deploy provisions it; its absence means the gateway wiring never ran)`,
    ).toBeTruthy();

    expect(
      String(llm.url),
      "the LLM endpoint must be the in-cluster gateway chat-completions URL the deploy configured, not a vendor endpoint",
    ).toBe(expectedEndpoint);

    const endpointUrl = new URL(String(llm.url));
    expect(
      endpointUrl.protocol,
      "the gateway endpoint must be plain http on the container network; https would mean it leaves through the public ingress",
    ).toBe("http:");
    expect(
      endpointUrl.hostname.includes("."),
      `the gateway host must be an undotted container name (got "${endpointUrl.hostname}"); a dotted host picks up the dns-search suffix and routes prompts through the public ingress`,
    ).toBe(false);
    expect(
      endpointUrl.host.toLowerCase(),
      "the gateway host must be a distinct in-cluster service, not Discourse itself",
    ).not.toBe(discourseHost.toLowerCase());

    expect(
      String(llm.provider),
      "the provider must be open_ai so the OpenAI-compatible endpoint of the gateway is used verbatim",
    ).toBe("open_ai");

    expect(
      String(llm.name),
      "the model name sent in the request body must be the model the gateway serves",
    ).toBe(expectedModel);

    expect(
      String(llm.api_key || "").length,
      "the LLM row must carry this role's own virtual key, otherwise the gateway answers 401",
    ).toBeGreaterThan(0);

    const siteSettings = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/site_settings.json`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      if (!res.ok) return { ok: false, status: res.status };
      const body = await res.json();
      return { ok: true, settings: (body && body.site_settings) || [] };
    }, discourseBaseUrl);

    expect(
      siteSettings.ok,
      `expected /admin/site_settings.json to be reachable as admin (status ${siteSettings.status})`,
    ).toBe(true);

    expect(
      settingValue(siteSettings.settings, "discourse_ai_enabled").toLowerCase(),
      "discourse_ai_enabled must be on, otherwise no AI surface is served at all",
    ).toBe("true");

    expect(
      settingValue(siteSettings.settings, "ai_default_llm_model"),
      "ai_default_llm_model must point at the gateway row, so every AI feature resolves to it",
    ).toBe(String(llm.id));

    const completion = await page.evaluate(async ({ base, model }) => {
      const csrfRes = await fetch(`${base}/session/csrf.json`, {
        headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
        credentials: "include",
      });
      const csrfBody = csrfRes.ok ? await csrfRes.json() : {};
      const csrf =
        (csrfBody && csrfBody.csrf) ||
        document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") ||
        "";

      const res = await fetch(`${base}/admin/plugins/discourse-ai/ai-llms/test.json`, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRF-Token": csrf,
        },
        credentials: "include",
        body: JSON.stringify({ ai_llm: model }),
      });
      const text = await res.text();
      let body;
      try {
        body = JSON.parse(text);
      } catch {
        body = { raw: text.slice(0, 500) };
      }
      return { status: res.status, body };
    }, {
      base: discourseBaseUrl,
      model: {
        provider: llm.provider,
        name: llm.name,
        url: llm.url,
        api_key: llm.api_key,
        tokenizer: llm.tokenizer,
        max_prompt_tokens: llm.max_prompt_tokens,
      },
    });

    expect(
      completion.status,
      `the admin LLM probe must be accepted (status ${completion.status})`,
    ).toBe(200);

    expect(
      completion.body.success,
      `the gateway must answer the probe prompt with non-empty text in both the streaming and the non-streaming mode: ${JSON.stringify(completion.body.error || completion.body.validation_errors || completion.body.raw || completion.body)}`,
    ).toBe(true);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
