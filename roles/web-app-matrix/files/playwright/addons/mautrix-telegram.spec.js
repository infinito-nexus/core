const { test, expect } = require("../onion-test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const TELEGRAM_BOT_LOCALPART = "telegrambot";

test("mautrix-telegram addon: appservice bot is provisioned on the Synapse homeserver", async ({ request }) => {
  skipUnlessAddonEnabled("mautrix-telegram");
  test.setTimeout(resolveTimeout(60_000));

  const matrixBaseUrl = shared.env.matrixBaseUrl;
  const matrixServerName = shared.env.matrixServerName;
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set").toBeTruthy();
  expect(matrixServerName, "MATRIX_SERVER_NAME must be set").toBeTruthy();

  const botUserId = `@${TELEGRAM_BOT_LOCALPART}:${matrixServerName}`;
  const profileUrl =
    `${matrixBaseUrl}/_matrix/client/v3/profile/${encodeURIComponent(botUserId)}`;

  const response = await request.get(profileUrl, { failOnStatusCode: false });

  expect(
    response.status(),
    `the mautrix-telegram bridge appservice bot ${botUserId} must be registered on Synapse (${matrixBaseUrl}). ` +
      `A 404 means the appservice registration never landed in the homeserver — the bridge coupling failed to provision. ` +
      `A 5xx means the homeserver is unhealthy. Got HTTP ${response.status()}.`
  ).toBe(200);

  const profile = await response.json().catch(() => null);
  expect(
    profile && typeof profile === "object" && !Array.isArray(profile),
    `Synapse must return the telegram bridge bot's profile JSON object for ${botUserId}, proving the appservice bot user exists`
  ).toBe(true);
});
