const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-weblate/files/playwright/test-two-factor.js");
const BASE_URL = "https://translate.example.org";
const FLAGGED_PROJECT_TEST = "two-factor: a flagged project refuses the edit it allowed before, superuser included";
const REFUSAL = "This project requires two-factor authentication";
const SLUG = /infinito-2fa-probe-\d+/;
const LOAD_REQUESTS = 3;
const POLL_ATTEMPTS = 10;

process.env.LOGIN_METHOD_NATIVE_ENABLED = "true";

/**
 * Args:
 *   status: HTTP status of the answer.
 *   body: JSON body, or the plain text of a refusal.
 *
 * Returns:
 *   The subset of a Playwright APIResponse the spec reads.
 */
function reply(status, body) {
  return {
    status: () => status,
    ok: () => status >= 200 && status < 300,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  };
}

/**
 * Returns:
 *   `{state, request}`: a Weblate API that, like Weblate 2026.11, creates the source translation of a new component
 *   at once but commits its strings only when the background component_after_save task ends, LOAD_REQUESTS requests
 *   later; German added before that commit keeps its strings invisible for longer than the spec polls.
 *   `state.germanDuringLoad` records whether German was added before the commit.
 */
function fakeWeblate() {
  const state = { requestsSinceComponent: undefined, germanDuringLoad: undefined, flagged: false };
  const loading = () => state.requestsSinceComponent <= LOAD_REQUESTS;
  const routes = {
    "POST /api/projects/": () => reply(201, {}),
    "POST /api/projects/<slug>/components/": () => {
      state.requestsSinceComponent = 0;
      return reply(201, {});
    },
    "GET /api/components/<slug>/probe/translations/": () => reply(200, { results: [{ language_code: "en" }] }),
    "GET /api/translations/<slug>/probe/en/units/": () => reply(200, { results: loading() ? [] : [{ id: 1 }] }),
    "POST /api/components/<slug>/probe/translations/": () => {
      state.germanDuringLoad = loading();
      return reply(201, {});
    },
    "GET /api/translations/<slug>/probe/de/units/": () =>
      reply(200, { results: state.germanDuringLoad ? [] : [{ id: 2 }] }),
    "PATCH /api/units/2/": () => (state.flagged ? reply(403, REFUSAL) : reply(200, {})),
    "PATCH /api/projects/<slug>/": () => {
      state.flagged = true;
      return reply(200, {});
    },
    "DELETE /api/projects/<slug>/": () => reply(202, {}),
  };
  const request = {
    async fetch(url, options) {
      if (state.requestsSinceComponent !== undefined) {
        state.requestsSinceComponent += 1;
      }
      const route = `${options.method} ${new URL(url).pathname.replace(SLUG, "<slug>")}`;
      return route in routes ? routes[route]() : reply(404, { detail: route });
    },
  };
  return { state, request };
}

/**
 * Args:
 *   actual: the value under test.
 *   message: the failure message.
 *
 * Returns:
 *   The matchers of Playwright's expect the spec uses.
 */
function expect(actual, message) {
  return {
    toBe: (expected) => assert.equal(actual, expected, message),
    toContain: (part) => assert.ok(String(actual).includes(part), message),
  };
}

expect.poll = (probe, { message }) => ({
  async toBe(expected) {
    for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
      if ((await probe()) === expected) {
        return;
      }
    }
    throw new Error(message);
  },
});

/**
 * Args:
 *   file: the spec file to load.
 *
 * Returns:
 *   The body of the spec's flagged-project test.
 */
function flaggedProjectTest(file) {
  const registered = {};
  const playwrightTest = Object.assign(
    (name, body) => {
      registered[name] = body;
    },
    {
      skip: (condition, reason) => assert.equal(condition, false, reason),
      setTimeout: () => undefined,
    },
  );
  const globals = { Buffer };
  loadInternals(
    file,
    [],
    {
      "@playwright/test": { test: playwrightTest, expect },
      "./personas": {
        gotoOnion: () => undefined,
        normalizeBaseUrl: (url) => url,
        requireDotenvValue: (value, name) => (name === "APP_BASE_URL" ? BASE_URL : name),
      },
      "./timeouts": { resolveTimeout: (ms) => ms },
    },
    globals,
  );
  globals.module.exports.register();
  return registered[FLAGGED_PROJECT_TEST];
}

/**
 * Args:
 *   old: text the spec holds exactly once.
 *   replacement: its replacement.
 *
 * Returns:
 *   The path of a planted copy of the spec, for a negative control.
 */
function planted(old, replacement) {
  const source = fs.readFileSync(SPEC, "utf8");
  assert.equal(source.split(old).length, 2, `the plant ${old} must occur exactly once`);
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "weblate-two-factor-plant-"));
  const file = path.join(directory, "test-two-factor.js");
  fs.writeFileSync(file, source.replace(old, replacement));
  return file;
}

test("German is added only once the source string has loaded, so the German string turns up", async () => {
  const weblate = fakeWeblate();
  await flaggedProjectTest(SPEC)({ request: weblate.request });
  assert.equal(weblate.state.germanDuringLoad, false);
  assert.equal(weblate.state.flagged, true);
});

test("negative control: waiting on the translation list, which Weblate fills before the load, adds German mid-load", async () => {
  const weblate = fakeWeblate();
  const file = planted("`translations/${slug}/probe/en/units/`", "`components/${slug}/probe/translations/`");
  await assert.rejects(flaggedProjectTest(file)({ request: weblate.request }), /the German translation must hold the probe string/);
  assert.equal(weblate.state.germanDuringLoad, true);
});
