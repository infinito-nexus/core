const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SHARED = path.join(PROJECT_ROOT, "roles/web-app-kix/files/playwright/_shared.js");
const BASE = "https://kix.example.org";
const POLL_LIMIT = 50;
const BIBER = { login: "biber", street: "Biberweg 7", phone: "+49 30 1234567", country: "IS" };
const ADMIN = "platformadmin";
const ACTIVE_CONTEXT_SELECTOR = ".content-wrapper > [data-contextinstanceid]:not(.d-none)";
const ROLE_ASSIGNED_AGENTS_SELECTOR = ".role-assigned-users";
const WIDGET_TOGGLE_SELECTOR = ".widget-header .minimize-icon-wrapper button";
const WIDGET_TABLE_SELECTOR = ".widget-content table.kix-table";
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
 * Returns:
 *   A locator stand-in for a selector that matches nothing.
 */
function absent() {
  const nothing = {
    first: () => nothing,
    locator: () => nothing,
    getByText: () => nothing,
    count: async () => 0,
    isVisible: async () => false,
    getAttribute: async () => null,
    click: async () => {
      throw new Error("no element matches the selector");
    },
  };
  return nothing;
}

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
 *   A KIX customer dashboard stand-in: a load lists no contact; the search takes the input's value only on a keyup, a
 *   keyup of Enter submits it and the search button submits the value the last keyup took; a submitted term lists the
 *   contacts whose login name it matches, and while the contacts table depends on the organisations one it lists none.
 */
function customerDashboard(contacts) {
  const app = { url: "", dependent: false, value: "", term: "", listed: [], visits: [] };
  const submit = () => {
    app.listed = app.dependent || !app.term ? [] : contacts.filter((contact) => contact.login === app.term);
  };
  const element = {
    isVisible: async () => app.url !== "",
    first: () => element,
    fill: async (value) => {
      app.value = value;
    },
    press: async (key) => {
      app.term = app.value;
      if (key === "Enter") submit();
    },
    click: async () => {
      submit();
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
    app.value = "";
    app.term = "";
    app.listed = [];
  };
  return app;
}

/**
 * Args:
 *   contexts: open KIX contexts in DOM order, each with whether KIX hides it and the texts it shows.
 *
 * Returns:
 *   A KIX page stand-in: a page-wide text search returns the first match in DOM order, hidden or not, and only the
 *   active context selector narrows the search to the context KIX shows.
 */
function openContexts(contexts) {
  const search = (list) => ({
    getByText: (text, options) => ({
      first: () => {
        const hit = list.find((context) =>
          context.texts.some((shown) => (options?.exact ? shown === text : shown.includes(text))),
        );
        return { isVisible: async () => Boolean(hit) && !hit.hidden };
      },
    }),
  });
  return {
    ...search(contexts),
    locator: (selector) =>
      selector === ACTIVE_CONTEXT_SELECTOR ? search(contexts.filter((context) => !context.hidden)) : absent(),
  };
}

/**
 * Args:
 *   agents: login names the role holds.
 *   minimized: whether the Assigned Agents widget is minimized once it has mounted.
 *   expands: whether a click on the widget toggle flips the widget.
 *   mountReads: reads of the toggle before the widget has mounted; until then the toggle has no title and the widget
 *     shows its unminimized first render.
 *
 * Returns:
 *   A KIX role detail view stand-in that answers only the exact selectors of the active context, the Assigned Agents
 *   widget, its toggle and its agents table; a minimized widget renders no agents table, so every agent counts zero;
 *   app.clicks counts the toggle clicks.
 */
function roleDetails(agents, { minimized, expands, mountReads }) {
  const app = { minimized, clicks: 0, reads: 0 };
  app.mounted = () => app.reads >= mountReads;
  const shownMinimized = () => app.mounted() && app.minimized;
  const toggle = {
    count: async () => {
      app.reads += 1;
      return 1;
    },
    getAttribute: async (name) => {
      app.reads += 1;
      if (name === "title") return app.mounted() ? (app.minimized ? "Expand widget" : "Collapse widget") : null;
      if (name === "aria-expanded") return shownMinimized() ? "false" : "true";
      return null;
    },
    click: async () => {
      app.clicks += 1;
      if (expands) app.minimized = !app.minimized;
    },
  };
  const table = {
    isVisible: async () => !shownMinimized(),
    getByText: (text) => {
      const matches = () => (shownMinimized() ? 0 : agents.filter((agent) => agent === text).length);
      return { count: async () => matches(), first: () => ({ isVisible: async () => matches() > 0 }) };
    },
  };
  const widget = {
    locator: (selector) => {
      if (selector === WIDGET_TOGGLE_SELECTOR) return { first: () => toggle };
      if (selector === WIDGET_TABLE_SELECTOR) return { first: () => table };
      return absent();
    },
  };
  const context = {
    locator: (selector) => (selector === ROLE_ASSIGNED_AGENTS_SELECTOR ? { first: () => widget } : absent()),
  };
  app.table = table;
  app.page = { locator: (selector) => (selector === ACTIVE_CONTEXT_SELECTOR ? context : absent()) };
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

function loadActiveContext() {
  return loadShared("activeContext", {});
}

function loadExpand() {
  return loadShared("expandRoleAssignedAgents", {});
}

function dashboardBehindContactPage() {
  return openContexts([
    { hidden: true, texts: [BIBER.phone, BIBER.country, BIBER.street] },
    { hidden: false, texts: ["Helpdesk lead", BIBER.phone, BIBER.country, BIBER.street] },
  ]);
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
  assert.equal(app.term, BIBER.login);
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

test("the active context finds the contact-page values a hidden dashboard row repeats before them", async () => {
  const shown = loadActiveContext()(dashboardBehindContactPage());
  assert.equal(await shown.getByText(BIBER.phone).first().isVisible(), true);
  assert.equal(await shown.getByText(BIBER.street).first().isVisible(), true);
  assert.equal(await shown.getByText(BIBER.country, { exact: true }).first().isVisible(), true);
});

test("a page-wide search for a contact-page value finds the hidden dashboard row first, the failure the scoping prevents", async () => {
  const page = dashboardBehindContactPage();
  assert.equal(await page.getByText(BIBER.phone).first().isVisible(), false);
  assert.equal(await page.getByText(BIBER.country, { exact: true }).first().isVisible(), false);
});

test("expanding the minimized Assigned Agents widget waits for its mount and returns its rendered agents table", async () => {
  const app = roleDetails([ADMIN], { minimized: true, expands: true, mountReads: 3 });
  const table = await loadExpand()(app.page);
  assert.equal(app.mounted(), true);
  assert.equal(app.clicks, 1);
  assert.equal(app.minimized, false);
  assert.equal(await table.isVisible(), true);
  assert.equal(await table.getByText(ADMIN).first().isVisible(), true);
  assert.equal(await table.getByText(BIBER.login).count(), 0);
});

test("an Assigned Agents widget already expanded stays expanded", async () => {
  const app = roleDetails([ADMIN], { minimized: false, expands: true, mountReads: 0 });
  await loadExpand()(app.page);
  assert.equal(app.clicks, 0);
  assert.equal(app.minimized, false);
});

test("without the expansion a minimized widget counts no agent the role holds, the false absence the expansion prevents", async () => {
  const app = roleDetails([BIBER.login], { minimized: true, expands: true, mountReads: 0 });
  assert.equal(await app.table.getByText(BIBER.login).count(), 0);
  const table = await loadExpand()(app.page);
  assert.equal(await table.getByText(BIBER.login).count(), 1);
});

test("an Assigned Agents widget that never expands fails the expansion instead of returning an unrendered table", async () => {
  const app = roleDetails([BIBER.login], { minimized: true, expands: false, mountReads: 0 });
  await assert.rejects(loadExpand()(app.page), /must expand and render its agents table/);
  assert.ok(app.clicks > 0);
});
