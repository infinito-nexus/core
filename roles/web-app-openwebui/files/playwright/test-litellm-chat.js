const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("litellm chat: a gateway model answers a chat completion via OpenWebUI", async ({ page }) => {
    skipUnlessServiceEnabled("litellm");
    test.setTimeout(120_000);

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
    const chatModel = modelIds.find((id) => id && !/embed/i.test(id));
    expect(
      chatModel,
      `a chat model must be served by OpenWebUI through the LiteLLM gateway, proving gateway and backend are reachable and the model pulled (got ${JSON.stringify(modelIds)})`
    ).toBeTruthy();

    const chatResp = await page.request.post(`${base}/api/chat/completions`, {
      headers,
      data: {
        model: chatModel,
        messages: [{ role: "user", content: "Reply with exactly the word: pong" }],
        stream: false,
      },
    });
    expect(
      chatResp.ok(),
      `the ${chatModel} chat completion must return 200 over OpenWebUI -> LiteLLM (HTTP ${chatResp.status()})`
    ).toBeTruthy();

    const chatBody = await chatResp.json();
    const content = (chatBody?.choices?.[0]?.message?.content ?? "").trim();
    expect(
      content.length,
      `the model must return a non-empty assistant response over OpenWebUI -> LiteLLM -> ${chatModel} (got ${JSON.stringify(chatBody).slice(0, 300)})`
    ).toBeGreaterThan(0);
  });
};
