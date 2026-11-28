const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const SPEC = path.join(PROJECT_ROOT, "roles/web-app-shopware/files/playwright/test-admin-native.js");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const dotenv = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dotenv.js"));

const ATTEMPTS = 5;

function expect(target, message) {
  return {
    toHaveCount: async (expected) => {
      for (let attempt = 0; attempt < ATTEMPTS * 4; attempt += 1) {
        if ((await target.count()) === expected) return;
      }
      throw new Error(message);
    },
    toBeVisible: async () => {
      if (!(await target.isVisible())) throw new Error(message);
    },
    toPass: async () => {
      let last;
      for (let attempt = 0; attempt < ATTEMPTS; attempt += 1) {
        try {
          return await target();
        } catch (error) {
          last = error;
        }
      }
      throw last;
    },
  };
}

process.env.APP_BASE_URL = '"https://shop.example"';
const { clickLogout } = loadInternals(
  SPEC,
  ["clickLogout"],
  {
    "@playwright/test": { test: () => undefined, expect },
    "./personas": { ...dotenv, gotoOnion: async () => undefined },
    "./timeouts": { resolveTimeout: (ms) => ms },
  },
  {},
);

/**
 * Args:
 *   loadingPolls: loader count reads that still report the current user loading.
 *   droppedClicks: toggle clicks after the load that open nothing, e.g. closed again by the route watcher.
 *   open: whether the user-actions menu starts open.
 *   neverOpens: the toggle opens nothing at all.
 *
 * Returns:
 *   The fake page and its recorded state.
 */
function fakeAdmin({ loadingPolls = 0, droppedClicks = 0, open = false, neverOpens = false } = {}) {
  const state = { loadingPolls, droppedClicks, open, clicks: 0, clicksWhileLoading: 0, loggedOut: false };
  const loader = {
    count: async () => {
      if (state.loadingPolls === 0) return 0;
      state.loadingPolls -= 1;
      return 1;
    },
  };
  const toggle = {
    locator: () => loader,
    click: async () => {
      state.clicks += 1;
      if (state.loadingPolls > 0) {
        state.clicksWhileLoading += 1;
        return;
      }
      if (neverOpens) return;
      if (state.droppedClicks > 0) {
        state.droppedClicks -= 1;
        return;
      }
      state.open = !state.open;
    },
  };
  const logout = {
    isVisible: async () => state.open,
    click: async () => {
      assert.ok(state.open, "the logout link is clicked only while the menu shows it");
      state.loggedOut = true;
    },
  };
  const page = {
    locator: (selector) => ({ ".sw-admin-menu__user-actions-toggle": toggle, ".sw-admin-menu__logout-action": logout })[selector],
  };
  return { page, state };
}

test("the toggle is clicked only once the current user has loaded", async () => {
  const { page, state } = fakeAdmin({ loadingPolls: 3 });

  await clickLogout(page);

  assert.equal(state.clicksWhileLoading, 0);
  assert.equal(state.clicks, 1);
  assert.equal(state.loggedOut, true);
});

test("a toggle click that opens nothing is repeated until the logout shows", async () => {
  const { page, state } = fakeAdmin({ droppedClicks: 2 });

  await clickLogout(page);

  assert.equal(state.clicks, 3);
  assert.equal(state.loggedOut, true);
});

test("a menu that is already open is not toggled shut", async () => {
  const { page, state } = fakeAdmin({ open: true });

  await clickLogout(page);

  assert.equal(state.clicks, 0);
  assert.equal(state.loggedOut, true);
});

test("negative control: a toggle that never opens fails with the logout message instead of clicking blind", async () => {
  const { page, state } = fakeAdmin({ neverOpens: true });

  await assert.rejects(clickLogout(page), /Shopware's logout lives behind the user-actions toggle/);
  assert.equal(state.clicks, ATTEMPTS);
  assert.equal(state.loggedOut, false);
});

test("negative control: a user that never finishes loading fails before any toggle click", async () => {
  const { page, state } = fakeAdmin({ loadingPolls: Number.POSITIVE_INFINITY });

  await assert.rejects(clickLogout(page), /drops every user-actions click while its loader/);
  assert.equal(state.clicks, 0);
});
