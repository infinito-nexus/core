const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SHARED = path.join(PROJECT_ROOT, "roles/web-app-moodle/files/playwright/_shared.js");

/**
 * Args:
 *   options.html: the markup `page.content()` returns.
 *   options.tourShown: whether the end control of a user tour renders.
 *
 * Returns:
 *   A page double that records every click and assertion in `events`.
 */
function fakePage({ html = "", tourShown = false } = {}) {
  const events = [];
  return {
    events,
    content: async () => html,
    locator: (selector) => ({
      selector,
      events,
      first() {
        return this;
      },
      click: async () => events.push(["click", selector]),
      waitFor: async () => {
        if (!tourShown) throw new Error("not shown");
      },
    }),
  };
}

const { endUserTour } = loadInternals(
  SHARED,
  ["endUserTour"],
  {
    "@playwright/test": {
      expect: (target) => ({
        toHaveCount: async (count) => target.events.push(["count", target.selector, count]),
      }),
    },
    "./timeouts": { resolveTimeout: (ms) => ms },
    "./personas": {
      decodeDotenvQuotedValue: (value) => value,
      normalizeBaseUrl: (value) => value,
    },
  },
  {},
);

test("a started user tour is ended through its end control so its backdrop no longer swallows clicks", async () => {
  const page = fakePage({ html: '{"startTour":true}', tourShown: true });

  await endUserTour(page);

  assert.deepEqual(page.events, [
    ["click", '[data-role="flexitour-step"] [data-role="end"]'],
    ["count", "[data-flexitour]", 0],
  ]);
});

test("a started tour whose end control never renders is left alone instead of failing the step", async () => {
  const page = fakePage({ html: '{"startTour":true}', tourShown: false });

  await endUserTour(page);

  assert.deepEqual(page.events, []);
});

test("a page that starts no user tour is left untouched", async () => {
  const page = fakePage({ html: '{"startTour":false}', tourShown: true });

  await endUserTour(page);

  assert.deepEqual(page.events, []);
});
