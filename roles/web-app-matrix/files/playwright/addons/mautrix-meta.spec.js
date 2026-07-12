const { test, expect } = require("../onion-test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("mautrix-meta addon: bridge appservice registers @metabot on the partner Synapse homeserver", async ({ request }) => {
  skipUnlessAddonEnabled("mautrix-meta");
  test.setTimeout(resolveTimeout(120_000));

  const { matrixBaseUrl, matrixServerName } = shared.env;
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set to reach the partner homeserver").toBeTruthy();
  expect(matrixServerName, "MATRIX_SERVER_NAME must be set to address the bridge bot").toBeTruthy();

  const botUserId = `@metabot:${matrixServerName}`;
  const profileUrl = new URL(
    `_matrix/client/v3/profile/${encodeURIComponent(botUserId)}`,
    matrixBaseUrl.endsWith("/") ? matrixBaseUrl : `${matrixBaseUrl}/`
  ).toString();

  const matrixHost = new URL(matrixBaseUrl).host;
  expect(
    new URL(profileUrl).host,
    "the bridge bot profile must be resolved against the partner Matrix homeserver host"
  ).toBe(matrixHost);

  const response = await request.get(profileUrl, { failOnStatusCode: false });

  expect(
    response.status(),
    `the partner Synapse must serve the bridge bot profile for ${botUserId}; ` +
      "a 404 means the mautrix-meta appservice never registered its bot (bridge wiring broken), " +
      "and a 5xx means the homeserver is unreachable — either way the coupling failed and this MUST fail, not skip"
  ).toBe(200);

  const body = await response.json();
  expect(
    body,
    "the bridge bot profile payload must come back as an object from the partner homeserver"
  ).toBeTruthy();
  expect(
    typeof body.displayname,
    `the registered ${botUserId} must expose a displayname provisioned by the mautrix-meta appservice`
  ).toBe("string");
  expect(
    body.displayname,
    "the Meta bridge bot displayname must be the one provisioned by the bridge registration"
  ).toMatch(/meta/i);

  const controlMxid = `@definitely-not-a-meta-bot-${Date.now()}:${matrixServerName}`;
  const controlUrl = new URL(
    `_matrix/client/v3/profile/${encodeURIComponent(controlMxid)}`,
    matrixBaseUrl.endsWith("/") ? matrixBaseUrl : `${matrixBaseUrl}/`
  ).toString();
  const controlResponse = await request.get(controlUrl, { failOnStatusCode: false });
  expect(
    controlResponse.status(),
    `an un-bridged localpart ${controlMxid} must be unknown to Synapse (404); if it resolves, ` +
      "the mautrix-meta appservice namespace is over-broad and the @metabot 200 above proves nothing"
  ).toBe(404);
});
