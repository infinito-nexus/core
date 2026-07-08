const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("mautrix-signal addon: bridge appservice bot is provisioned and reachable on the Synapse homeserver", async ({ request }) => {
  skipUnlessAddonEnabled("mautrix-signal");
  test.setTimeout(resolveTimeout(60_000));

  const { matrixBaseUrl, matrixServerName } = shared.env;
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set").toBeTruthy();
  expect(matrixServerName, "MATRIX_SERVER_NAME must be set").toBeTruthy();

  const botUserId = `@signalbot:${matrixServerName}`;
  const profileUrl = (userId) =>
    `${matrixBaseUrl}/_matrix/client/v3/profile/${encodeURIComponent(userId)}`;

  const botResponse = await request.get(profileUrl(botUserId), { failOnStatusCode: false });
  expect(
    botResponse.status(),
    `the mautrix-signal appservice bot ${botUserId} must be registered on the Synapse homeserver — a 404/M_NOT_FOUND means the bridge registration never landed`
  ).toBe(200);

  const botProfile = await botResponse.json();
  expect(
    botProfile,
    `${botUserId} profile must expose the provisioned bridge bot display name, proving the appservice (not just a config value) reached Synapse`
  ).toHaveProperty("displayname");
  expect(
    String(botProfile.displayname || ""),
    `${botUserId} display name must be the Signal bridge bot, distinct from an empty/local placeholder`
  ).toMatch(/signal/i);

  const absentBotUserId = `@signalbot-not-provisioned-${Date.now()}:${matrixServerName}`;
  const absentResponse = await request.get(profileUrl(absentBotUserId), { failOnStatusCode: false });
  expect(
    absentResponse.status(),
    "control: an unregistered bridge bot must return 404 on the same homeserver — otherwise the 200 above is meaningless"
  ).toBe(404);
});
