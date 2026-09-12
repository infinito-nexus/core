const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const env = {
  baseUrl: normalizeBaseUrl(process.env.LITELLM_UI_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
};

async function beforeEach() {}

module.exports = { env, beforeEach };
