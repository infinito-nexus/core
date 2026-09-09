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
const { waitForLogoutControl } = require(
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
