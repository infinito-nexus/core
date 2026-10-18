const { test, expect } = require("../onion-test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const BAIBOT_LOCALPART = "baibot";

test("baibot addon: the bot user is provisioned on the Synapse homeserver", async ({ request }) => {
  skipUnlessAddonEnabled("baibot");
  skipUnlessServiceEnabled("litellm");
  test.skip(
    !(process.env.MATRIX_FLAVOR || "").toLowerCase().includes("ansible"),
    "baibot ships with the matrix-docker-ansible-deploy flavor only",
  );

  test.setTimeout(resolveTimeout(60_000));

  const matrixBaseUrl = shared.env.matrixBaseUrl;
  const matrixServerName = shared.env.matrixServerName;
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set").toBeTruthy();
  expect(matrixServerName, "MATRIX_SERVER_NAME must be set").toBeTruthy();

  const botUserId = `@${BAIBOT_LOCALPART}:${matrixServerName}`;
  const profileUrl = `${matrixBaseUrl}/_matrix/client/v3/profile/${encodeURIComponent(botUserId)}`;

  const response = await request.get(profileUrl, { failOnStatusCode: false, timeout: resolveTimeout(30_000) });

  expect(
    response.status(),
    `the baibot user ${botUserId} must be registered on Synapse (${matrixBaseUrl}). MDAD creates it from ` +
      `matrix_user_creator_users_auto whenever the bot is enabled and carries a password, so a 404 means either ` +
      `the password reached the renderer empty or user creation never ran. Got HTTP ${response.status()}.`,
  ).toBe(200);

  const profile = await response.json().catch(() => null);
  expect(
    profile && typeof profile === "object" && !Array.isArray(profile),
    `Synapse must return the baibot profile JSON object for ${botUserId}, proving the bot user exists`,
  ).toBe(true);
});
