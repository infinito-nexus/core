const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const env = {
  baseUrl: normalizeBaseUrl(process.env.HOMEASSISTANT_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  mcpEnabled: String(process.env.MCP_SERVICE_ENABLED || "").toLowerCase() === "true",
};

async function beforeEach() {}

module.exports = { env, beforeEach };
