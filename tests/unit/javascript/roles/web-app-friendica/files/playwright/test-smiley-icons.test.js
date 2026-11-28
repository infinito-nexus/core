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
const AVATAR = "https://social.example.org/photo/contact/48/2?ts=1795534247";
const DEFAULT_AVATAR = "https://social.example.org/images/person-300.jpg";
const NETWORK_PAGE = "https://social.example.org/network";
const LOGIN_PAGE = "https://auth.example.org/realms/main/protocol/openid-connect/auth?client_id=social";
const ABORTED = "net::ERR_ABORTED";
const MAIN_FRAME = { name: "main" };
const SUBFRAME = { name: "sub" };

function fakePage() {
  const handlers = {};
  return {
    emit: (event, payload) => handlers[event]?.(payload),
    mainFrame: () => MAIN_FRAME,
    on: (event, handler) => {
      handlers[event] = handler;
    },
    off: (event, handler) => {
      if (handlers[event] === handler) delete handlers[event];
    },
  };
}

/**
 * Args:
 *   url: the request URL.
 *   resourceType: what Playwright reports as its resource type.
 *   options.errorText: the failure text, or null for a request that did not fail.
 *   options.redirectedFrom: the request whose redirect started this one, or null.
 *   options.navigationOf: the frame this request navigates, or null for a subresource.
 */
function fakeRequest(url, resourceType, { errorText = null, redirectedFrom = null, navigationOf = null } = {}) {
  return {
    url: () => url,
    resourceType: () => resourceType,
    failure: () => (errorText ? { errorText } : null),
    redirectedFrom: () => redirectedFrom,
    isNavigationRequest: () => navigationOf !== null,
    frame: () => navigationOf ?? MAIN_FRAME,
  };
}

/**
 * Args:
 *   request: the request this response answers.
 *   status: the HTTP status.
 *   headers: the lower-cased response headers.
 */
function fakeResponse(request, status, headers = {}) {
  return { request: () => request, status: () => status, headers: () => headers };
}

/**
 * Args:
 *   frame: the frame whose navigation the page answers.
 *
 * Returns:
 *   The `[event, payload]` pair of the final answer to that navigation.
 */
function navigationAnswer(frame) {
  const request = fakeRequest(NETWORK_PAGE, "document", { navigationOf: frame });
  return ["response", fakeResponse(request, 200, { "content-type": "text/html" })];
}

const ANSWER = navigationAnswer(MAIN_FRAME);
const COMMIT = ["framenavigated", MAIN_FRAME];
const SAME_DOCUMENT = ["framenavigated", MAIN_FRAME];
const LOAD = ["load"];

/**
 * Args:
 *   events: the `[event, payload]` pairs the page emits after its first document committed.
 *
 * Returns:
 *   The failures the watcher recorded.
 */
function failuresAfter(...events) {
  const page = fakePage();
  const watcher = watchSubresources(page);
  for (const event of [ANSWER, COMMIT, ...events]) page.emit(...event);
  watcher.stop();
  return Array.from(watcher.failures());
}

/**
 * Args:
 *   target: the response at the end of a redirect from AVATAR.
 *
 * Returns:
 *   The failures the watcher recorded.
 */
function failuresAfterRedirect(target) {
  const hop = fakeResponse(fakeRequest(AVATAR, "image"), 302, { location: target.request().url() });
  return failuresAfter(["response", hop], ["response", target]);
}

/**
 * Args:
 *   url: the URL the redirect chain ends on.
 *   resourceType: what Playwright reports as the resource type of the chain.
 *
 * Returns:
 *   A request that the redirect from AVATAR started.
 */
function redirectTarget(url, resourceType) {
  return fakeRequest(url, resourceType, { redirectedFrom: fakeRequest(AVATAR, resourceType) });
}

test("a Matomo beacon aborted on leaving a loaded page is no tracker failure", () => {
  const beacon = fakeRequest(TRACKER, "ping", { errorText: ABORTED });

  assert.deepEqual(failuresAfter(["request", beacon], LOAD, ANSWER, ["requestfailed", beacon], COMMIT), []);
});

test("an avatar aborted as the login helper leaves its landing page before load is no failure", () => {
  const avatar = fakeRequest(DEFAULT_AVATAR, "image", { errorText: ABORTED });

  assert.deepEqual(failuresAfter(["request", avatar], ANSWER, ["requestfailed", avatar], COMMIT), []);
});

test("the abort rule holds when the commit is reported before the abort", () => {
  const avatar = fakeRequest(DEFAULT_AVATAR, "image", { errorText: ABORTED });

  assert.deepEqual(failuresAfter(["request", avatar], ANSWER, COMMIT, ["requestfailed", avatar]), []);
});

test("an image still pending when the spec leaves a loaded page fails the spec", () => {
  const smiley = fakeRequest(SMILEY, "image", { errorText: ABORTED });

  assert.deepEqual(failuresAfter(["request", smiley], LOAD, ANSWER, ["requestfailed", smiley], COMMIT), [
    `${ABORTED} ${SMILEY}`,
  ]);
});

test("an aborted Matomo beacon on the document still shown fails the spec", () => {
  const beacon = fakeRequest(TRACKER, "ping", { errorText: ABORTED });

  assert.deepEqual(failuresAfter(["request", beacon], ["requestfailed", beacon]), [`${ABORTED} ${TRACKER}`]);
});

test("a same-document navigation does not discard the document an aborted smiley belongs to", () => {
  const smiley = fakeRequest(SMILEY, "image", { errorText: ABORTED });

  assert.deepEqual(failuresAfter(["request", smiley], ["requestfailed", smiley], SAME_DOCUMENT), [
    `${ABORTED} ${SMILEY}`,
  ]);
});

test("a subframe navigation does not discard the document an aborted smiley belongs to", () => {
  const smiley = fakeRequest(SMILEY, "image", { errorText: ABORTED });

  assert.deepEqual(
    failuresAfter(["request", smiley], navigationAnswer(SUBFRAME), ["requestfailed", smiley], ["framenavigated", SUBFRAME]),
    [`${ABORTED} ${SMILEY}`],
  );
});

test("a navigation the network fails opens Chromium's error page as a new document", () => {
  const avatar = fakeRequest(DEFAULT_AVATAR, "image", { errorText: ABORTED });
  const navigation = fakeRequest(NETWORK_PAGE, "document", { errorText: "net::ERR_TIMED_OUT", navigationOf: MAIN_FRAME });

  assert.deepEqual(
    failuresAfter(["request", avatar], ["requestfailed", navigation], ["requestfailed", avatar], COMMIT),
    [],
  );
});

test("an image the network refuses before a navigation still fails the spec", () => {
  const smiley = fakeRequest(SMILEY, "image", { errorText: "net::ERR_CONNECTION_REFUSED" });

  assert.deepEqual(failuresAfter(["request", smiley], ANSWER, ["requestfailed", smiley], COMMIT), [
    `net::ERR_CONNECTION_REFUSED ${SMILEY}`,
  ]);
});

test("a Matomo beacon the network refuses still fails the spec", () => {
  const beacon = fakeRequest(TRACKER, "ping", { errorText: "net::ERR_CONNECTION_REFUSED" });

  assert.deepEqual(failuresAfter(["request", beacon], ["requestfailed", beacon]), [
    `net::ERR_CONNECTION_REFUSED ${TRACKER}`,
  ]);
});

test("a Matomo answer outside 2xx still fails the spec", () => {
  assert.deepEqual(failuresAfter(["response", fakeResponse(fakeRequest(TRACKER, "ping"), 500)]), [`500 ${TRACKER}`]);
});

test("an avatar redirected to the default avatar image is no failure", () => {
  const target = redirectTarget(DEFAULT_AVATAR, "image");

  assert.deepEqual(failuresAfterRedirect(fakeResponse(target, 200, { "content-type": "image/jpeg" })), []);
});

test("a redirected image revalidated from the browser cache as 304 is no failure", () => {
  const target = redirectTarget(DEFAULT_AVATAR, "image");

  assert.deepEqual(failuresAfterRedirect(fakeResponse(target, 304)), []);
});

test("an avatar redirected to a missing image fails the spec on the target", () => {
  const target = redirectTarget(DEFAULT_AVATAR, "image");

  assert.deepEqual(failuresAfterRedirect(fakeResponse(target, 404, { "content-type": "text/html" })), [
    `404 ${DEFAULT_AVATAR}`,
  ]);
});

test("an image redirected to the login page fails the spec although that page answers 200", () => {
  const target = redirectTarget(LOGIN_PAGE, "image");

  assert.deepEqual(failuresAfterRedirect(fakeResponse(target, 200, { "content-type": "text/html; charset=utf-8" })), [
    `200 ${LOGIN_PAGE}`,
  ]);
});

test("an image answered directly stays judged by its status alone, whatever its content type", () => {
  const smiley = fakeResponse(fakeRequest(SMILEY, "image"), 200, { "content-type": "text/html" });

  assert.deepEqual(failuresAfter(["response", smiley]), []);
});

test("a redirected Matomo beacon is judged by its status alone, not by an image content type", () => {
  const target = redirectTarget(TRACKER, "ping");

  assert.deepEqual(failuresAfterRedirect(fakeResponse(target, 204)), []);
});

test("a redirect without a target fails the spec", () => {
  assert.deepEqual(failuresAfter(["response", fakeResponse(fakeRequest(AVATAR, "image"), 302)]), [`302 ${AVATAR}`]);
});

test("a 300 answer Chromium does not follow fails the spec despite its Location", () => {
  const multipleChoices = fakeResponse(fakeRequest(AVATAR, "image"), 300, { location: DEFAULT_AVATAR });

  assert.deepEqual(failuresAfter(["response", multipleChoices]), [`300 ${AVATAR}`]);
});

test("a stopped watcher records nothing more", () => {
  const page = fakePage();
  const watcher = watchSubresources(page);
  watcher.stop();
  page.emit("response", fakeResponse(fakeRequest(SMILEY, "image"), 404));

  assert.deepEqual(Array.from(watcher.failures()), []);
});
