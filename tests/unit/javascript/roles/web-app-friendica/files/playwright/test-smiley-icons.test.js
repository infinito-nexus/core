const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const { watchSubresources } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-friendica/files/playwright/test-smiley-icons.js"),
  ["watchSubresources"],
  {},
  { URL },
);

const TRACKER = "https://matomo.example.org/matomo.php?action_name=Network&idsite=2&rec=1&send_image=0";
const SMILEY = "https://social.example.org/addon/smiley_pack/icons/animals/bunny.gif";

function fakePage() {
  const handlers = {};
  return {
    emit: (event, payload) => handlers[event]?.(payload),
    on: (event, handler) => {
      handlers[event] = handler;
    },
    off: (event) => {
      delete handlers[event];
    },
  };
}

/**
 * Args:
 *   url: the request URL.
 *   resourceType: what Playwright reports as its resource type.
 *   errorText: the failure text, or null for a request that did not fail.
 */
function fakeRequest(url, resourceType, errorText = null) {
  return {
    url: () => url,
    resourceType: () => resourceType,
    failure: () => (errorText ? { errorText } : null),
  };
}

/**
 * Args:
 *   emit: drives the watcher with `page.emit(event, payload)`.
 *
 * Returns:
 *   The failures the watcher recorded.
 */
function failuresAfter(emit) {
  const page = fakePage();
  const watcher = watchSubresources(page);
  emit(page);
  watcher.stop();
  return Array.from(watcher.failures);
}

test("a Matomo beacon the next navigation aborts is no tracker failure", () => {
  const failures = failuresAfter((page) => page.emit("requestfailed", fakeRequest(TRACKER, "ping", "net::ERR_ABORTED")));

  assert.deepEqual(failures, []);
});

test("a Matomo beacon the network refuses still fails the spec", () => {
  const failures = failuresAfter((page) =>
    page.emit("requestfailed", fakeRequest(TRACKER, "ping", "net::ERR_CONNECTION_REFUSED")),
  );

  assert.deepEqual(failures, [`net::ERR_CONNECTION_REFUSED ${TRACKER}`]);
});

test("an aborted smiley still fails the spec, only the tracker beacon is exempt", () => {
  const failures = failuresAfter((page) => page.emit("requestfailed", fakeRequest(SMILEY, "image", "net::ERR_ABORTED")));

  assert.deepEqual(failures, [`net::ERR_ABORTED ${SMILEY}`]);
});

test("a Matomo answer outside 2xx still fails the spec", () => {
  const failures = failuresAfter((page) =>
    page.emit("response", { request: () => fakeRequest(TRACKER, "ping"), status: () => 500 }),
  );

  assert.deepEqual(failures, [`500 ${TRACKER}`]);
});
