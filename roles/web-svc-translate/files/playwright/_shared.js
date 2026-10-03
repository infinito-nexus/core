const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { normalizeBaseUrl, requireDotenvValue } = require("./personas");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const engines = requireDotenvValue(process.env.TRANSLATE_ENGINES, "TRANSLATE_ENGINES").split(",").filter(Boolean);
const weblateEnabled = requireDotenvValue(process.env.TRANSLATE_WEBLATE_ENABLED, "TRANSLATE_WEBLATE_ENABLED") === "true";
const weblateBaseUrl = weblateEnabled ? normalizeBaseUrl(requireDotenvValue(process.env.WEBLATE_BASE_URL, "WEBLATE_BASE_URL")) : "";
const weblateToken = weblateEnabled ? requireDotenvValue(process.env.WEBLATE_API_TOKEN, "WEBLATE_API_TOKEN") : "";
const weblateProject = weblateEnabled ? requireDotenvValue(process.env.WEBLATE_PROJECT, "WEBLATE_PROJECT") : "";

function url(path) {
  return `${appBaseUrl}${path}`;
}

async function post(request, path, payload) {
  return request.fetch(url(path), {
    method: "POST",
    data: payload,
    headers: { "Content-Type": "application/json" },
    failOnStatusCode: false,
    timeout: resolveTimeout(300_000),
  });
}

async function translate(request, payload) {
  const response = await post(request, "/translate", payload);
  expect(response.status(), `Expected /translate ${JSON.stringify(payload)} to answer 200`).toBe(200);
  return response.json();
}

async function weblate(request, path, options = {}) {
  const response = await request.fetch(`${weblateBaseUrl}/api/${path}`, {
    headers: { Authorization: `Token ${weblateToken}`, "Content-Type": "application/json", ...(options.headers || {}) },
    method: options.method || "GET",
    data: options.data,
    failOnStatusCode: false,
    timeout: resolveTimeout(120_000),
  });
  return { response, body: response.ok() ? await response.json() : null };
}

module.exports = {
  appBaseUrl,
  canonicalDomain,
  engines,
  weblateEnabled,
  weblateBaseUrl,
  weblateProject,
  url,
  post,
  translate,
  weblate,
};
