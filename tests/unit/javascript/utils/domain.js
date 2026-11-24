const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../..");
const KEY = "INFINITO_DOMAIN=";
const GENERAL_VARS = "group_vars/all/00_general.yml";
const SOFTWARE_NAME = /^SOFTWARE_NAME:\s*"([^"]+)"/m;
const SOFTWARE_DOMAIN_RULE = 'SOFTWARE_DOMAIN: "{{ SOFTWARE_NAME | lower }}"';

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

/**
 * Returns:
 *   SOFTWARE_DOMAIN as group_vars/all/00_general.yml derives it from
 *   SOFTWARE_NAME.
 */
function softwareDomain() {
  const general = fs.readFileSync(path.join(PROJECT_ROOT, GENERAL_VARS), "utf8");
  const name = general.match(SOFTWARE_NAME);
  if (!name) throw new Error(`${GENERAL_VARS} declares no SOFTWARE_NAME`);
  if (!general.includes(SOFTWARE_DOMAIN_RULE)) {
    throw new Error(`${GENERAL_VARS} no longer derives ${SOFTWARE_DOMAIN_RULE}; update softwareDomain()`);
  }
  return name[1].toLowerCase();
}

module.exports = { DOMAIN: defaultDomainPrimary(), SOFTWARE_DOMAIN: softwareDomain() };
