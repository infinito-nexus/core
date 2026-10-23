const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue } = require("./personas");

const OWNED_BY_ADDON_SPEC = new Set([
  "hookshot",
  "mautrix_meta",
  "mautrix_signal",
  "mautrix_slack",
  "mautrix_telegram",
  "mautrix_whatsapp",
]);

const BRIDGE_TO_BOT_LOCALPART = {
  appservice_irc: "ircbot",
  chatgpt: "chatgptbot",
  discord: "discordbot",
  heisenbridge: "heisenbridge",
  mautrix_discord: "discordbot",
  mautrix_twitter: "twitterbot",
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

    const rawPlugins = decodeDotenvQuotedValue(process.env.MATRIX_PLUGINS_JSON || "") || "{}";
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
      if (OWNED_BY_ADDON_SPEC.has(bridge)) {
        continue;
      }
      const localpart = BRIDGE_TO_BOT_LOCALPART[bridge];
      if (!localpart) {
        failures.push(`${bridge}: no bot localpart registered in BRIDGE_TO_BOT_LOCALPART map`);
        continue;
      }
      const userId = `@${localpart}:${matrixServerName}`;
      const url = `${matrixBaseUrl}/_matrix/client/v3/profile/${encodeURIComponent(userId)}`;
      const r = await request.get(url, { failOnStatusCode: false, timeout: resolveTimeout(30_000) });
      if (r.status() >= 500) {
        failures.push(`${bridge}: ${userId} -> HTTP ${r.status()}`);
      }
    }

    expect(failures, `Bridge appservice probes failed:\n${failures.join("\n")}`).toEqual([]);
  });
};
