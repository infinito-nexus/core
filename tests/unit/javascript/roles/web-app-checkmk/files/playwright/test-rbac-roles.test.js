const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-checkmk/files/playwright/test-rbac-roles.js");
const ROW_SELECTOR = "table.data tr";
const ROLE_LINK_SELECTOR = "a[href*='mode=edit_role']";
const SYNC_LINK_SELECTOR = "a:has-text('Synchronize users')";

/**
 * Args:
 *   id: the Checkmk user id in the ID column.
 *   lastSeen: the Last seen column.
 *   connection: the Connection column.
 *   alias: the Alias column.
 *   email: the Email column.
 *   roles: the role aliases the Roles column links to.
 *
 * Returns:
 *   One row of the Checkmk user list as its cell texts and role links.
 */
function userRow(id, lastSeen, connection, alias, email, roles) {
  return {
    cells: ["", "", id, "", lastSeen, connection, "Password", "", alias, email, roles.join(""), "none"],
    roles,
  };
}

const CI_USER_LIST = [
  userRow(
    "administrator",
    "Never",
    "LDAP (ldap_infinito)",
    "Administrator Infinito.Nexus",
    `administrator@${DOMAIN}`,
    ["Administrator"],
  ),
  userRow("cmkadmin", "Never", "htpasswd (htpasswd)", "cmkadmin", "", ["Administrator"]),
  userRow("biber", "2026-11-24 09:10:01", "LDAP (ldap_infinito)", "Harry Beaver", `biber@${DOMAIN}`, [
    "Guest user",
  ]),
  userRow(
    "platformadmin",
    "2026-11-24 08:44:54",
    "LDAP (ldap_infinito)",
    "Platform Administrator",
    `platformadmin@${DOMAIN}`,
    ["Administrator"],
  ),
];

/**
 * Args:
 *   rows: the user list rows the locator still matches.
 *
 * Returns:
 *   A double of a Playwright row locator whose text filter sees the cells
 *   concatenated without separators, as Checkmk renders them.
 */
function rowLocator(rows) {
  const rowText = (row) => row.cells.join("");
  const matchesText = (row, hasText) =>
    hasText instanceof RegExp ? hasText.test(rowText(row)) : rowText(row).toLowerCase().includes(hasText.toLowerCase());
  const matchesHas = (row, has) =>
    has.role === "cell" &&
    row.cells.some((cell) => (has.exact ? cell.trim() === has.name : cell.toLowerCase().includes(has.name.toLowerCase())));
  return {
    filter: ({ has, hasText }) =>
      rowLocator(
        rows.filter((row) => (hasText === undefined || matchesText(row, hasText)) && (has === undefined || matchesHas(row, has))),
      ),
    first: () => rowLocator(rows.slice(0, 1)),
    count: async () => rows.length,
    innerText: async () => rows[0].cells.join("\t"),
    locator: (selector) => {
      assert.equal(selector, ROLE_LINK_SELECTOR);
      return { allInnerTexts: async () => rows.flatMap((row) => row.roles) };
    },
  };
}

/**
 * Args:
 *   rows: the rows the Checkmk user list shows.
 *   events: the list every navigation, sync click and poll result is appended to.
 *
 * Returns:
 *   A double of the administrator's Playwright page on the user list.
 */
function userListPage(rows, events) {
  return {
    locator: (selector) => {
      if (selector === "table.data") return { count: async () => 1 };
      if (selector === ROW_SELECTOR) return rowLocator(rows);
      assert.equal(selector, SYNC_LINK_SELECTOR);
      return {
        first: () => ({
          count: async () => 1,
          evaluate: async () => events.push(["sync"]),
        }),
      };
    },
    getByRole: (role, options) => ({ role, ...options }),
    waitForResponse: async () => undefined,
  };
}

/**
 * Args:
 *   events: the list every navigation, sync click and poll result is appended to.
 *
 * Returns:
 *   The spec's internal functions, loaded against doubles whose polls evaluate once.
 */
function load(events) {
  const poll = (probe) => ({
    toBeGreaterThan: async (floor) => assert.ok((await probe()) > floor),
    toContain: async (item) => {
      const value = await probe();
      events.push(["polled", value]);
      assert.ok(value.includes(item), `${JSON.stringify(value)} lacks ${item}`);
    },
  });
  return loadInternals(
    SPEC,
    ["syncUntilRowShows"],
    {
      "@playwright/test": {
        test: Object.assign(() => {}, { use: () => {}, setTimeout: () => {} }),
        expect: Object.assign(() => ({}), { poll }),
      },
      "./timeouts": { resolveTimeout: (ms) => ms },
      "./personas": {
        decodeDotenvQuotedValue: (value) => value,
        normalizeBaseUrl: (value) => value,
        requireDotenvValue: (value) => value,
        gotoOnion: async (_page, target) => events.push(["goto", target]),
      },
    },
    {},
  );
}

test("the administrator's row is found by its ID cell although Checkmk renders the cells without whitespace", async () => {
  const events = [];
  const { syncUntilRowShows } = load(events);

  await syncUntilRowShows(userListPage(CI_USER_LIST, events), "platformadmin", "Administrator");

  assert.deepEqual(events.at(-1), ["polled", ["Administrator"]]);
  assert.ok(!events.some(([kind]) => kind === "sync"));
});

test("biber's row is found by its ID cell and lists the synced role", async () => {
  const events = [];
  const { syncUntilRowShows } = load(events);

  await syncUntilRowShows(userListPage(CI_USER_LIST, events), "biber", "Guest user");

  assert.deepEqual(events.at(-1), ["polled", ["Guest user"]]);
});

test("a role alias that only the Alias column carries is not taken for the granted role", async () => {
  const events = [];
  const { syncUntilRowShows } = load(events);
  const rows = [
    userRow("platformadmin", "Never", "LDAP (ldap_infinito)", "Platform Administrator", "", ["Normal monitoring user"]),
  ];

  await assert.rejects(syncUntilRowShows(userListPage(rows, events), "platformadmin", "Administrator"));

  assert.deepEqual(events.at(-1), ["polled", ["Normal monitoring user"]]);
  assert.ok(events.some(([kind]) => kind === "sync"));
});

test("negative control: the former word-boundary row match finds no row in the same user list", async () => {
  const page = userListPage(CI_USER_LIST, []);
  const rows = page.locator(ROW_SELECTOR);

  for (const username of ["platformadmin", "biber"]) {
    assert.equal(await rows.filter({ hasText: new RegExp(`\\b${username}\\b`) }).count(), 0);
    assert.equal(await rows.filter({ has: page.getByRole("cell", { name: username, exact: true }) }).count(), 1);
  }
});
