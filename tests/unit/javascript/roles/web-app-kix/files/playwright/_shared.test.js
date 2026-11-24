const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SHARED = path.join(PROJECT_ROOT, "roles/web-app-kix/files/playwright/_shared.js");
const BASE = "https://kix.example.org";
const POLL_LIMIT = 50;
const BIBER = { login: "biber", street: "Biberweg 7" };
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

/**
 * Args:
 *   contacts: contacts KIX holds, each with its login name and the street the directory synced.
 *
 * Returns:
 *   A KIX customer dashboard stand-in: a load lists no contact, a submitted search lists the contacts whose login name
 *   matches the typed term, and while the contacts table depends on the organisations one it lists none.
 */
function customerDashboard(contacts) {
  const app = { url: "", dependent: false, term: "", listed: [], visits: [] };
  const element = {
    isVisible: async () => app.url !== "",
    first: () => element,
    fill: async (value) => {
      app.term = value;
    },
    click: async () => {
      app.listed = app.dependent ? [] : contacts.filter((contact) => contact.login === app.term);
    },
  };
  app.page = {
    url: () => app.url,
    evaluate: async () => false,
    locator: () => element,
    getByText: (text) => ({
      first: () => ({ isVisible: async () => app.listed.some((contact) => contact.street.includes(text)) }),
    }),
  };
  app.gotoOnion = async (page, url) => {
    app.visits.push(url);
    const target = new URL(url);
    app.dependent = target.searchParams.get("dependent") === "true";
    app.url = `${BASE}${target.pathname}?dependent=${app.dependent}`;
    app.term = "";
    app.listed = [];
  };
  return app;
}

function loadShared(name, personas) {
  return loadInternals(
    SHARED,
    [name],
    {
      "@playwright/test": { expect: fakeExpect, request: {} },
      "./timeouts": { resolveTimeout: identity },
      "./personas": { decodeDotenvQuotedValue: identity, requireDotenvValue: identity, ...personas },
      "./service-gating": { isServiceEnabled: () => false },
    },
    { URL },
  )[name];
}

function loadLogout(app) {
  return loadShared("runKixDirectoryLogout", { inAppLogout: app.inAppLogout, gotoOnion: app.gotoOnion });
}

function loadSearch(app) {
  return loadShared("searchCustomerDashboard", { gotoOnion: app.gotoOnion });
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

test("the customer dashboard search for a login lists that contact's street with the organisation dependency off", async () => {
  process.env.APP_BASE_URL = BASE;
  const app = customerDashboard([BIBER]);
  await loadSearch(app)(app.page, BIBER.login);
  assert.deepEqual(app.visits, [`${BASE}/organisations?dependent=false`]);
  assert.equal(await app.page.getByText(BIBER.street).first().isVisible(), true);
});

test("an unsearched customer dashboard lists no contact, the failure the search prevents", async () => {
  process.env.APP_BASE_URL = BASE;
  const app = customerDashboard([BIBER]);
  await app.gotoOnion(app.page, `${BASE}/organisations`);
  assert.equal(await app.page.getByText(BIBER.street).first().isVisible(), false);
});

test("a customer dashboard search for another login leaves the contact unlisted", async () => {
  process.env.APP_BASE_URL = BASE;
  const app = customerDashboard([BIBER]);
  await loadSearch(app)(app.page, "nobody");
  assert.equal(await app.page.getByText(BIBER.street).first().isVisible(), false);
});
