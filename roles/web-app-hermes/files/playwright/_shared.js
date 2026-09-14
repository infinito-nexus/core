const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const env = {
  baseUrl: normalizeBaseUrl(process.env.HERMES_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  apiServerKey: decodeDotenvQuotedValue(process.env.HERMES_API_SERVER_KEY || ""),
};

async function beforeEach() {}

module.exports = { env, beforeEach };
