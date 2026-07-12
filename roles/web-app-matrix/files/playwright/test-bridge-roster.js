const { test, expect } = require("./onion-test");

const BRIDGE_TO_BOT_LOCALPART = {
  appservice_irc: "ircbot",
  appservice_kakaotalk: "kakaotalkbot",
  appservice_slack: "slackbot",
  chatgpt: "chatgptbot",
  discord: "discordbot",
  facebook: "facebookbot",
  gitter: "gitterbot",
  googlechat: "googlechatbot",
  heisenbridge: "heisenbridge",
  hookshot: "hookshot",
  imessage: "imessagebot",
  instagram: "instagrambot",
  mautrix_discord: "discordbot",
  mautrix_signal: "signalbot",
  mautrix_slack: "slackbot",
  mautrix_telegram: "telegrambot",
  mautrix_twitter: "twitterbot",
  mautrix_whatsapp: "whatsappbot",
  signal: "signalbot",
  slack: "slackbot",
  sms: "smsbot",
  telegram: "telegrambot",
  whatsapp: "whatsappbot",
};

function isTruthy(value) {
  if (value === true) return true;
  if (typeof value === "string") return value.toLowerCase() === "true";
  return false;
}

exports.register = function (shared) {
  test("bridge-roster: every enabled bridge has a reachable appservice bot on Synapse", async ({ request }) => {
    shared.skipUnlessServiceEnabled("bridges");
    const { matrixBaseUrl, matrixServerName } = shared.env;

    const rawPlugins = process.env.MATRIX_PLUGINS_JSON || "{}";
    let plugins;
    try {
      plugins = JSON.parse(rawPlugins);
    } catch (e) {
      throw new Error(`MATRIX_PLUGINS_JSON must parse as JSON (got: ${rawPlugins.slice(0, 200)}): ${e.message}`, { cause: e });
    }
    const enabled = Object.entries(plugins).filter(([, v]) => isTruthy(v)).map(([k]) => k);

    if (enabled.length === 0) {
      test.skip(true, `MATRIX_PLUGINS_JSON has no truthy bridge entries despite BRIDGES_SERVICE_ENABLED=true. Raw: ${rawPlugins.slice(0, 200)}`);
    }

    const failures = [];
    for (const bridge of enabled) {
      const localpart = BRIDGE_TO_BOT_LOCALPART[bridge];
      if (!localpart) {
        failures.push(`${bridge}: no bot localpart registered in BRIDGE_TO_BOT_LOCALPART map`);
        continue;
      }
      const userId = `@${localpart}:${matrixServerName}`;
      const url = `${matrixBaseUrl}/_matrix/client/v3/profile/${encodeURIComponent(userId)}`;
      const r = await request.get(url, { failOnStatusCode: false });
      if (r.status() >= 500) {
        failures.push(`${bridge}: ${userId} -> HTTP ${r.status()}`);
      }
    }

    expect(failures, `Bridge appservice probes failed:\n${failures.join("\n")}`).toEqual([]);
  });
};
