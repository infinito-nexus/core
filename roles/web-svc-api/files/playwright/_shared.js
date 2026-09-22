const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const translatedRole = decodeDotenvQuotedValue(process.env.TRANSLATED_ROLE || "");
const SEMVER_TAG = /^v\d+\.\d+\.\d+$/;

function apiUrl(path, params = {}) {
  const url = new URL(`${appBaseUrl}${path}`);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  return url.toString();
}

async function getJson(request, path, params = {}, headers = {}) {
  const response = await request.get(apiUrl(path, params), { headers, timeout: resolveTimeout(120_000) });
  expect(response.status(), `Expected ${path} ${JSON.stringify(params)} to answer 200`).toBe(200);
  expect(response.headers()["content-type"], `Expected ${path} to answer JSON`).toContain("application/json");
  return { response, body: await response.json() };
}

async function statusOf(request, path, params = {}, method = "GET") {
  const response = await request.fetch(apiUrl(path, params), {
    method,
    failOnStatusCode: false,
    timeout: resolveTimeout(120_000),
  });
  return response.status();
}

async function repositoriesWithForks(request) {
  let repositories = [];
  await expect
    .poll(
      async () => {
        repositories = (await getJson(request, "/v1/repositories")).body;
        return repositories.some((entry) => !entry.root && entry.branches.length > 0);
      },
      { message: "Expected the first fetch to mirror at least one fork", timeout: resolveTimeout(900_000), intervals: [10_000] },
    )
    .toBe(true);
  return repositories;
}

function newestReleaseTag(repositories) {
  const root = repositories.find((entry) => entry.root);
  const tags = root.tags.filter((tag) => SEMVER_TAG.test(tag.name));
  expect(tags.length, "Expected core to carry release tags").toBeGreaterThan(0);
  return tags.sort((a, b) => b.date.localeCompare(a.date))[0];
}

module.exports = {
  appBaseUrl,
  canonicalDomain,
  adminPassword,
  translatedRole,
  apiUrl,
  getJson,
  statusOf,
  repositoriesWithForks,
  newestReleaseTag,
};
