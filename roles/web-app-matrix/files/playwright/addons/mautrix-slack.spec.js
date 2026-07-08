const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("mautrix-slack addon: Slack bridge appservice bot is provisioned and reachable on Synapse", async ({ request }) => {
  skipUnlessAddonEnabled("mautrix-slack");
  test.setTimeout(resolveTimeout(60_000));

  const matrixBaseUrl = shared.env.matrixBaseUrl;
  const matrixServerName = shared.env.matrixServerName;
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set for the bridge probe").toBeTruthy();
  expect(matrixServerName, "MATRIX_SERVER_NAME must be set for the bridge probe").toBeTruthy();

  const botUserId = `@slackbot:${matrixServerName}`;
  const profileUrl = `${matrixBaseUrl.replace(/\/$/, "")}/_matrix/client/v3/profile/${encodeURIComponent(botUserId)}`;

  const response = await request.get(profileUrl, { failOnStatusCode: false });
  const status = response.status();
  const body = await response.text();

  expect(
    status,
    `the mautrix-slack appservice bot ${botUserId} must be reachable on Synapse (the bridge actually registered its appservice with the homeserver). HTTP ${status}: ${body.slice(0, 300)}`
  ).toBeLessThan(500);

  expect(
    status,
    `Synapse must know the mautrix-slack bridge bot ${botUserId}. A 404/M_NOT_FOUND means the bridge's appservice registration never landed — the coupling failed to provision, so this MUST fail (not skip). HTTP ${status}: ${body.slice(0, 300)}`
  ).not.toBe(404);

  expect(
    status,
    `the mautrix-slack bridge bot profile lookup must succeed. HTTP ${status}: ${body.slice(0, 300)}`
  ).toBe(200);

  let profile;
  try {
    profile = JSON.parse(body);
  } catch (e) {
    throw new Error(`mautrix-slack bridge bot profile must be valid JSON. HTTP ${status}: ${body.slice(0, 300)}`, { cause: e });
  }

  expect(
    profile.displayname,
    "the provisioned mautrix-slack bridge bot must carry its Slack-bridge displayname (proves the bridge — not a stray Matrix account — owns @slackbot)"
  ).toMatch(/slack/i);
});
