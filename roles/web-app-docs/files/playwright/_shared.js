const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const RELEASE_TAG = /^v\d+\.\d+\.\d+$/;

async function fetchVersions(request) {
  const response = await request.get(`${appBaseUrl}/api/versions`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected the versions api to answer").toBe(200);
  return response.json();
}

async function versionState(request, name) {
  const version = (await fetchVersions(request)).find((candidate) => candidate.name === name);
  return version ? version.state : "unknown";
}

module.exports = { appBaseUrl, canonicalDomain, RELEASE_TAG, fetchVersions, versionState };
