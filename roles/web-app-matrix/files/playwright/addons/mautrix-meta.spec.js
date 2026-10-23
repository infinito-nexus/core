const { test, expect } = require("../onion-test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { decodeDotenvQuotedValue, requireDotenvValue } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const FLAVOR_BRIDGE_BOTS = {
  compose: [{ localpart: "metabot", displayname: /meta/i }],
  ansible: [
    { localpart: "messengerbot", displayname: /messenger/i },
    { localpart: "instagrambot", displayname: /instagram/i },
  ],
};

test("mautrix-meta addon: the bridge appservices register their bots on the partner Synapse homeserver", async ({ request }) => {
  skipUnlessAddonEnabled("mautrix-meta");
  test.setTimeout(resolveTimeout(120_000));

  const { matrixBaseUrl, matrixServerName } = shared.env;
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set to reach the partner homeserver").toBeTruthy();
  expect(matrixServerName, "MATRIX_SERVER_NAME must be set to address the bridge bot").toBeTruthy();

  const flavor = decodeDotenvQuotedValue(
    requireDotenvValue(process.env.MATRIX_FLAVOR, "MATRIX_FLAVOR")
  ).toLowerCase();
  const bots = FLAVOR_BRIDGE_BOTS[flavor];
  expect(
    bots,
    `MATRIX_FLAVOR must name a known flavor (${Object.keys(FLAVOR_BRIDGE_BOTS).join(", ")}) because each one provisions ` +
      `different Meta bridge bots: the compose flavor renders one mautrix-meta service, while MDAD splits the addon into ` +
      `a messenger and an instagram bridge with a bot each. Got ${JSON.stringify(flavor)}`
  ).toBeTruthy();

  const baseUrl = matrixBaseUrl.endsWith("/") ? matrixBaseUrl : `${matrixBaseUrl}/`;
  const profileUrl = (userId) =>
    new URL(`_matrix/client/v3/profile/${encodeURIComponent(userId)}`, baseUrl).toString();
  const matrixHost = new URL(matrixBaseUrl).host;

  for (const bot of bots) {
    const botUserId = `@${bot.localpart}:${matrixServerName}`;
    const url = profileUrl(botUserId);

    expect(
      new URL(url).host,
      "the bridge bot profile must be resolved against the partner Matrix homeserver host"
    ).toBe(matrixHost);

    const response = await request.get(url, { failOnStatusCode: false, timeout: resolveTimeout(30_000) });

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
      `${botUserId} must carry the displayname its own Meta bridge provisions, proving the appservice — not a stray ` +
        "Matrix account — owns the localpart"
    ).toMatch(bot.displayname);
  }

  const controlMxid = `@definitely-not-a-meta-bot-${Date.now()}:${matrixServerName}`;
  const controlResponse = await request.get(profileUrl(controlMxid), {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(
    controlResponse.status(),
    `an un-bridged localpart ${controlMxid} must be unknown to Synapse (404); if it resolves, ` +
      "the mautrix-meta appservice namespace is over-broad and the profiles above prove nothing"
  ).toBe(404);
});
