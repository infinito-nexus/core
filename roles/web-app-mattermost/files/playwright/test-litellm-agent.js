const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const LITELLM_API_URL = decodeDotenvQuotedValue(process.env.LITELLM_API_URL);
const LITELLM_BOT_NAME = decodeDotenvQuotedValue(process.env.LITELLM_BOT_NAME);

const PLUGIN_FAILURE_NOTICE = /sorry!?\s*an error|an error occurred|accessing the llm/i;

// The role rewrites the administrator to gitlab auth only when SSO is on, so the
// password grant exists exactly in the deployments that run without OIDC.
async function acquireAdminToken(context, shared, baseUrl) {
  if (!shared.oidcEnabled) {
    const login = await context.request.post(`${baseUrl}/api/v4/users/login`, {
      failOnStatusCode: false,
      headers: { "Content-Type": "application/json" },
      data: { login_id: shared.env.adminUsername, password: shared.env.adminPassword },
    });
    expect(
      login.status(),
      `the administrator must be able to open a Mattermost session; without one the Agents bot cannot be prompted at all (HTTP ${login.status()})`,
    ).toBe(200);

    const token = login.headers().token;
    expect(
      token,
      "Mattermost must return the session token in the Token response header of /api/v4/users/login",
    ).toBeTruthy();
    return token;
  }

  const page = await context.newPage();
  await shared.startMattermostSsoFlow(page, baseUrl);
  await performKeycloakLoginForm(page, shared.env.adminUsername, shared.env.adminPassword);
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: "Expected redirect back to Mattermost after the administrator OIDC login",
    })
    .toContain(baseUrl);

  const session = (await context.cookies(baseUrl)).find((cookie) => cookie.name === "MMAUTHTOKEN");
  expect(
    session && session.value,
    "the OIDC login must leave an MMAUTHTOKEN session cookie; without it no Agents prompt can be authenticated",
  ).toBeTruthy();
  await page.close().catch(() => {});
  return session.value;
}

async function firstBotReply(context, baseUrl, headers, channelId, botId, afterPostId) {
  const response = await context.request.get(
    `${baseUrl}/api/v4/channels/${channelId}/posts?after=${afterPostId}&per_page=50`,
    { headers, failOnStatusCode: false },
  );
  if (!response.ok()) return "";

  const body = await response.json();
  const replies = Object.values((body && body.posts) || {})
    .filter((post) => post.user_id === botId && String(post.message || "").trim().length > 0)
    .sort((a, b) => a.create_at - b.create_at);
  return replies.length > 0 ? String(replies[0].message).trim() : "";
}

exports.register = function (shared) {
  test("litellm: the Agents bot answers a prompt through the in-cluster gateway", async ({ browser }) => {
    skipUnlessServiceEnabled("litellm");
    test.setTimeout(300_000);

    expect(
      LITELLM_API_URL,
      "LITELLM_API_URL must render MATTERMOST_LITELLM_BASE_URL into the Playwright env; without it the endpoint the Agents plugin was pointed at cannot be checked",
    ).toMatch(/^https?:\/\/.+/i);

    const gatewayHost = new URL(LITELLM_API_URL).hostname;
    expect(
      gatewayHost,
      `the Agents service endpoint must address the gateway by its bare in-cluster service name; "${gatewayHost}" carries a dot, so the container dns-search suffix completes it and the prompt leaves the deployment through the public ingress`,
    ).not.toContain(".");

    const baseUrl = shared.expectedMattermostBaseUrl();
    const context = await browser.newContext({ ignoreHTTPSErrors: true });

    try {
      const token = await acquireAdminToken(context, shared, baseUrl);
      // Mattermost enforces CSRF only for a token read out of the cookie; carrying
      // it in the Authorization header keeps these calls header-authenticated.
      const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

      const meResponse = await context.request.get(`${baseUrl}/api/v4/users/me`, {
        headers,
        failOnStatusCode: false,
      });
      expect(
        meResponse.status(),
        `the session token must authenticate against the Mattermost API (HTTP ${meResponse.status()})`,
      ).toBe(200);
      const me = await meResponse.json();

      const botResponse = await context.request.get(
        `${baseUrl}/api/v4/users/username/${LITELLM_BOT_NAME}`,
        { headers, failOnStatusCode: false },
      );
      expect(
        botResponse.status(),
        `the Agents plugin must have provisioned the bot user "${LITELLM_BOT_NAME}"; its absence means the bot row the deploy merged into agents_confighistory was never picked up (HTTP ${botResponse.status()})`,
      ).toBe(200);
      const bot = await botResponse.json();
      expect(
        bot.id,
        `the "${LITELLM_BOT_NAME}" account must carry a user id so a direct message channel can be opened with it`,
      ).toBeTruthy();

      const dmResponse = await context.request.post(`${baseUrl}/api/v4/channels/direct`, {
        headers,
        failOnStatusCode: false,
        data: [me.id, bot.id],
      });
      expect(
        dmResponse.ok(),
        `a direct message channel between the administrator and the Agents bot must open; the plugin answers prompts only inside a channel it participates in (HTTP ${dmResponse.status()})`,
      ).toBeTruthy();
      const dm = await dmResponse.json();

      const prompt = `Reply with exactly the word: pong (${Date.now()})`;
      const promptResponse = await context.request.post(`${baseUrl}/api/v4/posts`, {
        headers,
        failOnStatusCode: false,
        data: { channel_id: dm.id, message: prompt },
      });
      expect(
        promptResponse.ok(),
        `the prompt must be posted into the Agents direct message channel (HTTP ${promptResponse.status()})`,
      ).toBeTruthy();
      const prompted = await promptResponse.json();

      let reply = "";
      await expect
        .poll(
          async () => {
            reply = await firstBotReply(context, baseUrl, headers, dm.id, bot.id, prompted.id);
            return reply.length;
          },
          {
            timeout: 180_000,
            intervals: [2_000],
            message: `the Agents bot "${LITELLM_BOT_NAME}" must answer the direct message with a real completion; silence means the plugin never reached ${LITELLM_API_URL}, the gateway rejected the virtual key, or no model is served behind it`,
          },
        )
        .toBeGreaterThan(0);

      expect(
        reply,
        `the Agents bot returned the plugin's LLM failure notice instead of a completion, so the prompt never got an answer out of ${LITELLM_API_URL}: ${JSON.stringify(reply).slice(0, 300)}`,
      ).not.toMatch(PLUGIN_FAILURE_NOTICE);
    } finally {
      await context.close().catch(() => {});
    }
  });
};
