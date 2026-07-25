const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const env = {
  baseUrl: normalizeBaseUrl(process.env.OPENCLAW_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  gatewayToken: decodeDotenvQuotedValue(process.env.OPENCLAW_GATEWAY_TOKEN || ""),
  ssoEnabled: String(process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true",
};

async function beforeEach() {}

module.exports = { env, beforeEach };
