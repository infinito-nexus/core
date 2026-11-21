const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SHARED = path.join(PROJECT_ROOT, "roles/web-app-kix/files/playwright/_shared.js");
const BASE = "https://kix.example.org";
const POLL_LIMIT = 50;
const identity = (value) => value;
const tick = () => new Promise((resolve) => setImmediate(resolve));

/**
 * Args:
 *   readValue: async or sync callback whose result is compared.
 *   matches: predicate the result must satisfy.
 *   message: failure text.
 */
async function pollUntil(readValue, matches, message) {
  for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
    if (matches(await readValue())) return;
    await tick();
  }
  throw new Error(message);
}

function fakeExpect(target, message) {
  return {
    toBeVisible: () => pollUntil(() => target.isVisible(), Boolean, message),
  };
}
fakeExpect.poll = (readValue, opts) => ({
  toBe: (expected) => pollUntil(readValue, (value) => value === expected, opts.message),
  not: { toContain: (needle) => pollUntil(readValue, (value) => !value.includes(needle), opts.message) },
});

/**
 * Args:
 *   deleteTicks: ticks the DELETE of the session takes before KIX navigates to its sign-in.
 *
 * Returns:
 *   A KIX stand-in: the logout click starts the DELETE, a navigation started while it runs is aborted by the app's own
 *   navigation to /auth, and a navigation after it lands on the sign-in again.
 */
function kixApp(deleteTicks) {
  const app = { url: `${BASE}/admin?moduleId=setup-assistant`, signInShown: false, deleting: false, visits: [] };
  app.page = {
    url: () => app.url,
    locator: () => ({ first: () => ({ isVisible: async () => app.signInShown }) }),
  };
  app.inAppLogout = async () => {
    app.deleting = true;
    (async () => {
      for (let step = 0; step < deleteTicks; step += 1) await tick();
      app.deleting = false;
      app.url = `${BASE}/auth`;
      app.signInShown = true;
    })();
  };
  app.gotoOnion = async (page, url) => {
    app.visits.push(url);
    if (app.deleting) throw new Error(`page.goto: net::ERR_ABORTED at ${url}`);
    app.url = `${BASE}/auth?redirectUrl=%2F`;
    app.signInShown = true;
  };
  return app;
}

function loadLogout(app) {
  return loadInternals(
    SHARED,
    ["runKixDirectoryLogout"],
    {
      "@playwright/test": { expect: fakeExpect, request: {} },
      "./timeouts": { resolveTimeout: identity },
      "./personas": {
        decodeDotenvQuotedValue: identity,
        requireDotenvValue: identity,
        inAppLogout: app.inAppLogout,
        gotoOnion: app.gotoOnion,
      },
      "./service-gating": { isServiceEnabled: () => false },
    },
    { URL },
  ).runKixDirectoryLogout;
}

test("the directory logout waits for the KIX sign-in before it requests a protected page again", async () => {
  process.env.APP_BASE_URL = BASE;
  const app = kixApp(5);
  await loadLogout(app)(app.page);
  assert.deepEqual(app.visits, [`${BASE}/`]);
  assert.equal(app.url, `${BASE}/auth?redirectUrl=%2F`);
});

test("a protected request sent while the KIX logout still runs is aborted, the failure the wait prevents", async () => {
  process.env.APP_BASE_URL = BASE;
  const app = kixApp(5);
  await app.inAppLogout(app.page);
  await assert.rejects(app.gotoOnion(app.page, `${BASE}/`), /net::ERR_ABORTED/);
});

test("a logout that never reaches the KIX sign-in fails instead of requesting the next page", async () => {
  process.env.APP_BASE_URL = BASE;
  const app = kixApp(POLL_LIMIT * 4);
  await assert.rejects(loadLogout(app)(app.page), /hand over to the KIX sign-in/);
  assert.deepEqual(app.visits, []);
});
