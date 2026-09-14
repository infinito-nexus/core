const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");

const playwrightStub = { expect: () => ({ toBe() {} }) };
const loadModule = Module._load;
Module._load = function (request, ...rest) {
  return request === "@playwright/test" ? playwrightStub : loadModule.call(this, request, ...rest);
};

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { confirmKeycloakLogoutIfPrompted, waitForLogoutControl } = require(
  path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/logout.js"),
);

Module._load = loadModule;

function fakePage({ visibleAfterMs = Infinity } = {}) {
  const start = Date.now();
  const intervals = [];
  const locator = () => {
    const self = {
      count: async () => 1,
      nth: () => ({ isVisible: async () => Date.now() - start >= visibleAfterMs }),
      filter: () => self,
    };
    return self;
  };
  return {
    intervals,
    locator,
    getByRole: locator,
    waitForTimeout: async (ms) => {
      intervals.push(ms);
      await new Promise((resolve) => setTimeout(resolve, ms));
    },
  };
}

test("returns true immediately when a logout control is already visible", async () => {
  const page = fakePage({ visibleAfterMs: 0 });
  const started = Date.now();
  assert.equal(await waitForLogoutControl(page, 3_000), true);
  assert.ok(Date.now() - started < 250, "must not sleep once the control is visible");
});

test("returns true as soon as the control appears, well before the deadline", async () => {
  const page = fakePage({ visibleAfterMs: 600 });
  const started = Date.now();
  assert.equal(await waitForLogoutControl(page, 5_000), true);
  const elapsed = Date.now() - started;
  assert.ok(elapsed >= 500, `expected to wait for the control, waited ${elapsed}ms`);
  assert.ok(elapsed < 2_000, `expected an early exit, waited ${elapsed}ms`);
});

test("costs at most the deadline when no control ever appears", async () => {
  const page = fakePage();
  const started = Date.now();
  assert.equal(await waitForLogoutControl(page, 900), false);
  const elapsed = Date.now() - started;
  assert.ok(elapsed >= 900, `must honour the full deadline, stopped after ${elapsed}ms`);
  assert.ok(elapsed < 1_800, `must not exceed the deadline materially, took ${elapsed}ms`);
});

test("polls on a fixed interval that no onion multiplier scales", async () => {
  const page = fakePage();
  await waitForLogoutControl(page, 900);
  assert.ok(page.intervals.length >= 3, `expected repeated polls, got ${page.intervals.length}`);
  assert.deepEqual(
    [...new Set(page.intervals)],
    [250],
    "the poll interval must stay 250ms so a slow target is detected sooner, not later",
  );
});

const KEYCLOAK_LOGOUT = "https://auth.test/realms/r/protocol/openid-connect/logout";

function keycloakLogoutPage({ url = KEYCLOAK_LOGOUT, promptAfterMs = Infinity, leaveAfterMs = Infinity } = {}) {
  let current = url;
  if (leaveAfterMs !== Infinity) setTimeout(() => { current = "https://app.test/"; }, leaveAfterMs);
  const page = {
    clicks: 0,
    probes: 0,
    url: () => current,
    locator: () => ({
      first: () => ({
        waitFor: ({ timeout }) => {
          page.probes += 1;
          return new Promise((resolve, reject) => {
            if (promptAfterMs <= timeout) setTimeout(resolve, promptAfterMs);
            else setTimeout(() => reject(new Error("waitFor timed out")), timeout);
          });
        },
        click: async () => { page.clicks += 1; },
      }),
    }),
    waitForURL: (predicate, { timeout }) =>
      new Promise((resolve, reject) => {
        const deadline = Date.now() + timeout;
        const tick = () => {
          if (predicate(new URL(current))) return resolve();
          if (Date.now() >= deadline) return reject(new Error("waitForURL timed out"));
          return setTimeout(tick, 20);
        };
        tick();
      }),
    waitForLoadState: async () => {},
  };
  return page;
}

test("confirm helper does nothing off the Keycloak logout endpoint", async () => {
  const page = keycloakLogoutPage({ url: "https://app.test/" });
  await confirmKeycloakLogoutIfPrompted(page);
  assert.equal(page.probes, 0);
  assert.equal(page.clicks, 0);
});

test("confirm helper clicks the confirmation Keycloak renders", async () => {
  const page = keycloakLogoutPage({ promptAfterMs: 100 });
  await confirmKeycloakLogoutIfPrompted(page);
  assert.equal(page.clicks, 1);
});

test("confirm helper returns once Keycloak redirects away without a prompt", async () => {
  const page = keycloakLogoutPage({ leaveAfterMs: 100 });
  const started = Date.now();
  await confirmKeycloakLogoutIfPrompted(page);
  const elapsed = Date.now() - started;
  assert.equal(page.clicks, 0);
  assert.ok(elapsed < 1_000, `must not wait out the confirm window after the redirect, waited ${elapsed}ms`);
});
