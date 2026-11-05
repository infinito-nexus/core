const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../..");
const KEY = "INFINITO_DOMAIN=";

/**
 * Returns:
 *   The INFINITO_DOMAIN value declared in default.env.
 */
function defaultDomainPrimary() {
  const line = fs
    .readFileSync(path.join(PROJECT_ROOT, "default.env"), "utf8")
    .split("\n")
    .find((entry) => entry.startsWith(KEY));
  if (!line) throw new Error(`default.env declares no ${KEY.slice(0, -1)}`);
  return line.slice(KEY.length).trim().replace(/^["']|["']$/g, "");
}

module.exports = { DOMAIN: defaultDomainPrimary() };
