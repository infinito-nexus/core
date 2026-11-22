const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-moodle/files/playwright/test-rbac-roles.js");
const MOODLE = "https://academy.example.test";

/**
 * Args:
 *   events: the list every step appends to.
 *   tourBlocksClicks: whether a started user tour still covers the dashboard when the logout runs.
 *
 * Returns:
 *   The shared helper double and the page double the spec's logout step drives.
 */
function harness(events, tourBlocksClicks) {
  const state = { tourActive: tourBlocksClicks };
  const page = {
    locator: (selector) => ({ selector }),
  };
  const shared = {
    env: { moodleBaseUrl: MOODLE },
    endUserTour: async () => {
      events.push(["endUserTour"]);
      state.tourActive = false;
    },
  };
  const personas = {
    decodeDotenvQuotedValue: (value) => value,
    gotoOnion: async (_page, target) => events.push(["goto", target]),
    inAppLogout: async () => events.push(["inAppLogout", state.tourActive ? "blocked" : "clicked"]),
  };
  return { page, shared, personas };
}

function load(personas, events) {
  return loadInternals(
    SPEC,
    ["logoutAndAssertSessionGone"],
    {
      "@playwright/test": {
        test: Object.assign(() => {}, { describe: () => {} }),
        expect: (target) => ({
          toHaveCount: async (count) => events.push(["count", target.selector, count]),
        }),
      },
      "./timeouts": { resolveTimeout: (ms) => ms },
      "./personas": personas,
    },
    {},
  );
}

test("the logout step ends the dashboard's user tour before it clicks the in-app logout", async () => {
  const events = [];
  const { page, shared, personas } = harness(events, true);
  const { logoutAndAssertSessionGone } = load(personas, events);

  await logoutAndAssertSessionGone(shared, page);

  assert.deepEqual(events.slice(0, 3), [["goto", `${MOODLE}/my/`], ["endUserTour"], ["inAppLogout", "clicked"]]);
  assert.deepEqual(events.at(-1), ["count", "form#adminsettings", 0]);
});

test("a dashboard without a user tour is logged out the same way", async () => {
  const events = [];
  const { page, shared, personas } = harness(events, false);
  const { logoutAndAssertSessionGone } = load(personas, events);

  await logoutAndAssertSessionGone(shared, page);

  assert.deepEqual(events, [
    ["goto", `${MOODLE}/my/`],
    ["endUserTour"],
    ["inAppLogout", "clicked"],
    ["goto", `${MOODLE}/admin/settings.php?section=frontpagesettings`],
    ["count", "form#adminsettings", 0],
  ]);
});
