/**
 * Forged-identity probe for vhosts whose backend trusts a proxy-set identity header.
 *
 *   forgedIdentityHeaders(identity) -> object
 *     identity: { username, email, groups }, each a non-empty string.
 *     Returns every header in FORGED_IDENTITY_HEADER_NAMES set to that identity;
 *     X-Forwarded-Access-Token carries it as the claims of an unsigned JWT,
 *     groups split on ",".
 *
 *   forgedIdentityPaths({ paths, prometheusIntegration }) -> string[]
 *     paths: role paths to probe, each starting with "/".
 *     prometheusIntegration: boolean; true appends HEALTHZ_PATHS, the public
 *       locations the prometheus integration adds to the vhost.
 *
 *   probeForgedIdentity(request, { baseUrl, paths, identity, prometheusIntegration })
 *     -> Promise<Array<{ path, url, status, location, setCookieNames, contentType, body }>>
 *     request: a Playwright APIRequestContext with no browser session.
 *     baseUrl: vhost base URL; a trailing slash is dropped.
 *     Redirects are not followed, so every field describes the first hop.
 *     Throws when the /healthz/ready probe answers 500 or above.
 *
 *   parseStrictBoolean(raw, key) -> boolean
 *     raw: "true" or "false"; anything else throws, naming key.
 */

const { resolveTimeout } = require("../../timeouts");
const { apiFetchOnion } = require("./onion");

const FORGED_IDENTITY_HEADER_NAMES = Object.freeze([
  "X-Forwarded-User",
  "X-Forwarded-Preferred-Username",
  "X-Forwarded-Email",
  "X-Forwarded-Groups",
  "X-Auth-Request-User",
  "X-Auth-Request-Preferred-Username",
  "X-Auth-Request-Email",
  "X-Auth-Request-Groups",
  "Remote-User",
  "Remote-Email",
  "Remote-Groups",
  "X-Remote-User",
  "X-Forwarded-Access-Token",
]);

const READY_PATH = "/healthz/ready";
const HEALTHZ_PATHS = Object.freeze([READY_PATH, "/healthz/live"]);

function requireNonEmpty(value, name) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`forged-identity: ${name} must be a non-empty string, got ${JSON.stringify(value)}`);
  }
  return value;
}

function parseStrictBoolean(raw, key) {
  if (raw === "true") return true;
  if (raw === "false") return false;
  throw new Error(`forged-identity: ${key} must be "true" or "false", got ${JSON.stringify(raw)}`);
}

function base64url(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function forgedIdentityHeaders(identity) {
  const username = requireNonEmpty(identity && identity.username, "identity.username");
  const email = requireNonEmpty(identity && identity.email, "identity.email");
  const groups = requireNonEmpty(identity && identity.groups, "identity.groups");
  const accessToken = [
    base64url({ alg: "none", typ: "JWT" }),
    base64url({ preferred_username: username, email, groups: groups.split(","), sub: username }),
    "",
  ].join(".");
  const values = {
    "X-Forwarded-User": username,
    "X-Forwarded-Preferred-Username": username,
    "X-Forwarded-Email": email,
    "X-Forwarded-Groups": groups,
    "X-Auth-Request-User": username,
    "X-Auth-Request-Preferred-Username": username,
    "X-Auth-Request-Email": email,
    "X-Auth-Request-Groups": groups,
    "Remote-User": username,
    "Remote-Email": email,
    "Remote-Groups": groups,
    "X-Remote-User": username,
    "X-Forwarded-Access-Token": accessToken,
  };
  return Object.fromEntries(FORGED_IDENTITY_HEADER_NAMES.map((name) => [name, values[name]]));
}

function forgedIdentityPaths({ paths, prometheusIntegration }) {
  if (!Array.isArray(paths) || paths.length === 0) {
    throw new Error("forged-identity: paths must be a non-empty array");
  }
  if (typeof prometheusIntegration !== "boolean") {
    throw new Error(`forged-identity: prometheusIntegration must be a boolean, got ${JSON.stringify(prometheusIntegration)}`);
  }
  for (const path of paths) {
    if (typeof path !== "string" || !path.startsWith("/")) {
      throw new Error(`forged-identity: every path must start with "/", got ${JSON.stringify(path)}`);
    }
  }
  return [...new Set(prometheusIntegration ? [...paths, ...HEALTHZ_PATHS] : paths)];
}

function setCookieNamesOf(response) {
  return response
    .headersArray()
    .filter((header) => header.name.toLowerCase() === "set-cookie")
    .map((header) => header.value.split("=", 1)[0].trim());
}

async function probeForgedIdentity(request, { baseUrl, paths, identity, prometheusIntegration }) {
  const base = requireNonEmpty(baseUrl, "baseUrl").replace(/\/$/, "");
  const headers = forgedIdentityHeaders(identity);
  const results = [];
  for (const path of forgedIdentityPaths({ paths, prometheusIntegration })) {
    const url = `${base}${path}`;
    const response = await apiFetchOnion(request, url, {
      method: "GET",
      headers,
      maxRedirects: 0,
      failOnStatusCode: false,
      ignoreHTTPSErrors: true,
      timeout: resolveTimeout(30_000),
    });
    const status = response.status();
    if (path === READY_PATH && status >= 500) {
      throw new Error(`forged-identity: ${url} answered ${status}, so the probe did not reach the backend`);
    }
    const responseHeaders = response.headers();
    results.push({
      path,
      url,
      status,
      location: responseHeaders.location || "",
      setCookieNames: setCookieNamesOf(response),
      contentType: responseHeaders["content-type"] || "",
      body: await response.text(),
    });
  }
  return results;
}

module.exports = {
  FORGED_IDENTITY_HEADER_NAMES,
  HEALTHZ_PATHS,
  forgedIdentityHeaders,
  forgedIdentityPaths,
  parseStrictBoolean,
  probeForgedIdentity,
};
