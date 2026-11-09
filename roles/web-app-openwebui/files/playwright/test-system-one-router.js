const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

const ROUTER_ALIAS = "auto";

exports.register = function (shared) {
  test("system one router: the router alias answers, served by a model that is not itself", async ({ page }) => {
    skipUnlessServiceEnabled("litellm");
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000));

    await shared.signInViaDashboardOidc(
      page,
      shared.env.adminUsername,
      shared.env.adminPassword,
      "administrator"
    );

    const token = await page.evaluate(() => window.localStorage.getItem("token"));
    expect(
      token,
      "OpenWebUI must store a session token in localStorage after login (used to authenticate its OpenAI-compatible API)"
    ).toBeTruthy();

    const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
    const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

    const modelsResp = await page.request.get(`${base}/api/models`, { headers });
    expect(
      modelsResp.ok(),
      `OpenWebUI /api/models must respond to the authenticated session (HTTP ${modelsResp.status()})`
    ).toBeTruthy();

    const modelsBody = await modelsResp.json();
    const modelIds = (Array.isArray(modelsBody?.data) ? modelsBody.data : [])
      .map((m) => String(m?.id ?? m?.name ?? ""));
    expect(
      modelIds,
      `the gateway must publish the router alias '${ROUTER_ALIAS}' so a consumer can select it like any other model (got ${JSON.stringify(modelIds)})`
    ).toContain(ROUTER_ALIAS);

    const chatResp = await page.request.post(`${base}/api/chat/completions`, {
      headers,
      data: {
        model: ROUTER_ALIAS,
        messages: [{ role: "user", content: "Reply with exactly the word: pong" }],
        stream: false,
      },
    });
    expect(
      chatResp.ok(),
      `'${ROUTER_ALIAS}' must return 200 over OpenWebUI -> LiteLLM; a pre-call hook that raised instead of rewriting the model shows up here (HTTP ${chatResp.status()})`
    ).toBeTruthy();

    const chatBody = await chatResp.json();
    const content = (chatBody?.choices?.[0]?.message?.content ?? "").trim();
    expect(
      content.length,
      `'${ROUTER_ALIAS}' must return a non-empty assistant response (got ${JSON.stringify(chatBody).slice(0, 300)})`
    ).toBeGreaterThan(0);

    const servedBy = String(chatBody?.model ?? "");
    expect(
      servedBy && servedBy !== ROUTER_ALIAS,
      `the answer must name the model the hook chose rather than the alias itself, which is what distinguishes a routed request from the fallback route (got ${JSON.stringify(servedBy)})`
    ).toBeTruthy();
  });
};
