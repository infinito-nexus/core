/**
 * Shared service-gating helper for role-local Playwright specs.
 *
 * Contract:
 *   isServiceEnabled("oidc")         -> boolean
 *   requireService("oidc", testFn)   -> wraps a test, calling test.skip() when
 *                                       the service is disabled
 *   isServiceDisabledReason("email") -> "EMAIL_SERVICE_ENABLED=false" style
 *                                       diagnostic string, or null if enabled
 *
 * Sources of truth:
 *   Per-service boolean env flags named <SERVICE>_SERVICE_ENABLED in
 *   UPPER_SNAKE_CASE. Values MUST be the literal strings "true" or "false".
 *   An absent variable is treated as "enabled" so local rerun-spec.sh runs
 *   against a fully-featured deploy keep their old behaviour.
 *
 * Typo-safety:
 *   A service name that is not declared in the spec's env registry (i.e.
 *   no <SERVICE>_SERVICE_ENABLED variable was ever rendered for it) MUST
 *   be treated as a test authoring bug and hard-fail the caller. Otherwise
 *   `isServiceEnabled("oicd")` would silently disable tests without
 *   surfacing the typo.
 *
 * See:
 *   docs/requirements/006-playwright-service-gated-tests.md
 *   docs/contributing/artefact/files/role/playwright.specs.js.md
 */

const { test } = require("@playwright/test");

const SUFFIX = "_SERVICE_ENABLED";

function envKey(name) {
  if (typeof name !== "string" || name.length === 0) {
    throw new Error(`service-gating: service name must be a non-empty string, got ${String(name)}`);
  }
  return name.toUpperCase().replace(/[^A-Z0-9]+/g, "_") + SUFFIX;
}

function rawValue(name) {
  return process.env[envKey(name)];
}

function parseBoolean(raw, key) {
  if (raw === undefined) return undefined;
  if (raw === "true") return true;
  if (raw === "false") return false;
  throw new Error(
    `service-gating: ${key} must be "true" or "false" (strict), got ${JSON.stringify(raw)}`
  );
}

/**
 * The env registry is the set of `<SERVICE>_SERVICE_ENABLED` keys that were
 * rendered by Ansible into the Playwright env. Any service outside this set
 * is considered unknown and using it throws.
 */
function registeredServices() {
  const registered = new Set();
  for (const key of Object.keys(process.env)) {
    if (key.endsWith(SUFFIX)) {
      const serviceSlug = key.slice(0, -SUFFIX.length);
      if (serviceSlug.length > 0) {
        registered.add(serviceSlug.toLowerCase());
      }
    }
  }
  return registered;
}

function assertKnownService(name) {
  const registered = registeredServices();
  if (registered.size === 0) {
    // No <SERVICE>_SERVICE_ENABLED at all in the env — assume an older
    // staged .env that predates requirement 006. Treat every service as
    // enabled and let individual lookups fall through to the default.
    return;
  }
  const slug = name.toLowerCase();
  if (!registered.has(slug)) {
    throw new Error(
      `service-gating: Unknown service "${name}". ` +
        `Declare ${envKey(name)} in the role's templates/playwright.env.j2 ` +
        `(see docs/contributing/artefact/files/role/playwright.specs.js.md#service-gating).`
    );
  }
}

function isServiceEnabled(name) {
  assertKnownService(name);
  const key = envKey(name);
  const parsed = parseBoolean(rawValue(name), key);
  return parsed === undefined ? true : parsed;
}

function isServiceDisabledReason(name) {
  if (isServiceEnabled(name)) return null;
  return `${envKey(name)}=false`;
}

/**
 * Skip the current test when the named service is disabled. Call this at
 * the top of a test body, before Playwright has performed any action:
 *
 *   test("foo", async ({ page }) => {
 *     skipUnlessServiceEnabled("oidc");
 *     // real assertions below
 *   });
 *
 * This API exists in addition to `requireService` because Playwright's
 * fixture system validates test function signatures at parse time and
 * rejects wrapper functions whose first argument is not a destructuring
 * pattern ("First argument must use the object destructuring pattern").
 * Calling `skipUnlessServiceEnabled` from inside the body keeps the
 * original arrow-with-destructuring signature Playwright insists on.
 */
function skipUnlessServiceEnabled(name) {
  const reason = isServiceDisabledReason(name);
  if (reason !== null) {
    test.skip(true, reason);
  }
}

/**
 * Legacy wrapper kept for compatibility with callers that were written
 * against the wrap-style API. New code SHOULD use
 * `skipUnlessServiceEnabled` at the top of the test body instead.
 */
function requireService(name, testFn) {
  if (typeof testFn !== "function") {
    throw new Error(
      `service-gating: requireService("${name}", fn) requires a function as second argument`
    );
  }
  return async function serviceGatedTest({ page, browser, context, request, browserName } = {}) {
    skipUnlessServiceEnabled(name);
    return testFn({ page, browser, context, request, browserName });
  };
}

module.exports = {
  isServiceEnabled,
  isServiceDisabledReason,
  requireService,
  skipUnlessServiceEnabled,
};
