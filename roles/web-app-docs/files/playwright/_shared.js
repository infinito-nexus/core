const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
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

let lastTransportError = null;

async function statusOf(request, url) {
  try {
    const response = await request.get(url, { failOnStatusCode: false, maxRedirects: 0, timeout: resolveTimeout(30_000) });
    lastTransportError = null;
    return response.status();
  } catch (error) {
    lastTransportError = error;
    return 0;
  }
}

const POLL_REPORT_RESERVE_MS = 60_000;

async function pollStatus(request, url, expected, message, timeout) {
  lastTransportError = null;
  const budget = Math.max(
    30_000,
    resolveTimeout(timeout) - POLL_REPORT_RESERVE_MS,
  );
  try {
    await expect
      .poll(() => statusOf(request, url), { message, timeout: budget, intervals: [30_000] })
      .toBe(expected);
  } catch (failure) {
    if (!lastTransportError) throw failure;
    throw new Error(
      `${failure.message}\nlast transport error reaching ${url}: ${lastTransportError.message}`,
      { cause: failure },
    );
  }
}

module.exports = {
  appBaseUrl,
  canonicalDomain,
  RELEASE_TAG,
  fetchVersions,
  versionState,
  pollStatus,
};
