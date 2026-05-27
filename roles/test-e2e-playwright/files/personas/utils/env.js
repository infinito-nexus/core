/**
 * Env-handling utilities shared by every persona-flow module.
 *
 * Kept tiny and dependency-free so each module can `require` only
 * what it needs.
 */

const { test } = require("@playwright/test");
const { isServiceEnabled } = require("../../service-gating");

function decodeDotenvQuoted(value) {
  if (typeof value !== "string" || value.length < 2) return value;
  if (!(value.startsWith('"') && value.endsWith('"'))) return value;
  const encoded = value.slice(1, -1);
  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

function normalizeUrl(value) {
  return decodeDotenvQuoted(value || "").replace(/\/$/, "");
}

function readEnv(name) {
  return decodeDotenvQuoted(process.env[name] || "");
}

/**
 * Tolerant variant of `skipUnlessServiceEnabled`: treats an unknown
 * service (i.e. one whose `<NAME>_SERVICE_ENABLED` flag is not declared
 * in the role's env registry) as "disabled" rather than a hard fail.
 * Roles MAY mark a service entry with `# nocheck: playwright-service-flag`
 * in `meta/services.yml`, in which case the env flag is not rendered
 * and the gate MUST skip cleanly.
 */
function safeSkipUnlessEnabled(name) {
  let enabled;
  try {
    enabled = isServiceEnabled(name);
  } catch {
    enabled = false;
  }
  if (!enabled) {
    test.skip(true, `${name.toUpperCase()}_SERVICE_ENABLED=false or unknown`);
  }
}

function safeIsEnabled(name) {
  try {
    return isServiceEnabled(name);
  } catch {
    return false;
  }
}

module.exports = {
  decodeDotenvQuoted,
  normalizeUrl,
  readEnv,
  safeSkipUnlessEnabled,
  safeIsEnabled,
};
