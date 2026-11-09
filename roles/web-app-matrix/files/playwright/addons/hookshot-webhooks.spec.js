const { test, expect } = require("../onion-test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const HOOKSHOT_BOT_LOCALPART = "hookshot";

test("hookshot-webhooks addon: the hookshot appservice bot is provisioned on the Synapse homeserver", async ({ request }) => {
  skipUnlessAddonEnabled("hookshot-webhooks");
  skipUnlessServiceEnabled("n8n");
  test.skip(
    !(process.env.MATRIX_FLAVOR || "").toLowerCase().includes("ansible"),
    "hookshot ships with the matrix-docker-ansible-deploy flavor only",
  );

  const plugins = JSON.parse(decodeDotenvQuotedValue(process.env.MATRIX_PLUGINS_JSON || "") || "{}");
  test.skip(
    !plugins.hookshot,
    `services.matrix.plugins.hookshot is off, so MDAD renders no hookshot bridge (MATRIX_PLUGINS_JSON: ${JSON.stringify(plugins)})`,
  );

  test.setTimeout(resolveTimeout(60_000));

  const matrixBaseUrl = shared.env.matrixBaseUrl;
  const matrixServerName = shared.env.matrixServerName;
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set").toBeTruthy();
  expect(matrixServerName, "MATRIX_SERVER_NAME must be set").toBeTruthy();

  const botUserId = `@${HOOKSHOT_BOT_LOCALPART}:${matrixServerName}`;
  const profileUrl = `${matrixBaseUrl.replace(/\/$/, "")}/_matrix/client/v3/profile/${encodeURIComponent(botUserId)}`;

  const response = await request.get(profileUrl, { failOnStatusCode: false, timeout: resolveTimeout(30_000) });

  expect(
    response.status(),
    `the hookshot appservice bot ${botUserId} must be registered on Synapse (${matrixBaseUrl}) so an inbound ` +
      `generic webhook from n8n can be routed into a room. A 404 means the appservice registration never landed. ` +
      `Got HTTP ${response.status()}.`,
  ).toBe(200);
});
