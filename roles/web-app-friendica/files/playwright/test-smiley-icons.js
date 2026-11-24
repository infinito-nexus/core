const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

const MATOMO_TRACKER_PATH = /\/matomo\.php$/;
const UPSTREAM_MISSING_ICON = "/addon/smiley_pack/icons/opensource/vivaldi.png";
const ABORTED = "net::ERR_ABORTED";

function isTrackedRequest(request) {
  const url = request.url();
  if (!/^https?:/i.test(url)) return false;
  const { pathname } = new URL(url);
  if (pathname === UPSTREAM_MISSING_ICON) return false;
  return request.resourceType() === "image" || MATOMO_TRACKER_PATH.test(pathname);
}

// A revalidated browser-cache hit surfaces as 304 while the body the page
// renders is the cached 2xx answer, so 304 counts as success.
function isSuccess(status) {
  return (status >= 200 && status < 300) || status === 304;
}

const FOLLOWED_REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);

// Friendica answers the avatar of an account without a stored profile photo
// with a 302 to /images/person-300.jpg. Chromium follows such a hop, so the
// answer at the end of the chain is judged in its place.
function isFollowedRedirect(response) {
  return FOLLOWED_REDIRECT_STATUSES.has(response.status()) && Boolean(response.headers().location);
}

// An image bounced through the oauth2-proxy login also ends in a 200, on the
// Keycloak login page, so a redirected image must end on an image.
function endsRedirectOffImage(request, response) {
  return (
    request.redirectedFrom() !== null &&
    request.resourceType() === "image" &&
    response.status() !== 304 &&
    !/^image\//i.test(response.headers()["content-type"] || "")
  );
}

// Leaving a document makes Chromium report what it still had in flight as
// net::ERR_ABORTED although no answer failed: the images its load event waited
// for, since the login helper navigates on before its landing page has loaded,
// and the Matomo keepalive beacon, which the browser delivers anyway.
function isNavigationAbort(failure, currentDocument, loadedDocuments) {
  if (failure.errorText !== ABORTED || !(failure.document < currentDocument)) return false;
  return failure.isTrackerBeacon || !loadedDocuments.has(failure.document);
}

// Playwright throws on frame() for a subframe whose navigation starts before
// the frame is attached; that request is no main-frame navigation either.
function isMainFrameNavigation(page, request) {
  if (!request.isNavigationRequest()) return false;
  try {
    return request.frame() === page.mainFrame();
  } catch {
    return false;
  }
}

function failureText(request) {
  const failure = request.failure();
  return failure ? failure.errorText : "request failed";
}

function watchSubresources(page) {
  const observed = new Set();
  const recorded = [];
  const documentOf = new WeakMap();
  const loadedDocuments = new Set();
  let currentDocument = 0;
  let newDocumentPending = false;
  const listeners = {
    // Playwright also fires framenavigated for pushState, replaceState and
    // #hash changes. Only a main-frame navigation that got a final answer, or
    // failed into Chromium's error page, opens a new document on its commit.
    framenavigated: (frame) => {
      if (frame !== page.mainFrame() || !newDocumentPending) return;
      newDocumentPending = false;
      currentDocument += 1;
    },
    load: () => {
      loadedDocuments.add(currentDocument);
    },
    request: (request) => {
      if (isTrackedRequest(request)) documentOf.set(request, currentDocument);
    },
    response: (response) => {
      const request = response.request();
      if (isMainFrameNavigation(page, request) && !isFollowedRedirect(response)) newDocumentPending = true;
      if (!isTrackedRequest(request)) return;
      observed.add(request.url());
      if (isFollowedRedirect(response)) return;
      if (!isSuccess(response.status()) || endsRedirectOffImage(request, response)) {
        recorded.push({ text: `${response.status()} ${request.url()}` });
      }
    },
    requestfailed: (request) => {
      const errorText = failureText(request);
      if (isMainFrameNavigation(page, request) && errorText !== ABORTED) newDocumentPending = true;
      if (!isTrackedRequest(request)) return;
      recorded.push({
        errorText,
        document: documentOf.get(request),
        isTrackerBeacon: MATOMO_TRACKER_PATH.test(new URL(request.url()).pathname),
        text: `${errorText} ${request.url()}`,
      });
    },
  };
  for (const [event, listener] of Object.entries(listeners)) page.on(event, listener);
  return {
    observed,
    failures() {
      return recorded
        .filter((failure) => !isNavigationAbort(failure, currentDocument, loadedDocuments))
        .map((failure) => failure.text);
    },
    stop() {
      for (const [event, listener] of Object.entries(listeners)) page.off(event, listener);
    },
  };
}

async function smileySources(page) {
  return page.locator("img.smiley").evaluateAll((imgs) =>
    [...new Set(imgs.map((img) => img.currentSrc || img.src).filter(Boolean))]
  );
}

exports.register = function (shared) {
  test("administrator: /network and /smilies → every smiley and image answers 2xx", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(240_000));

    const baseUrl = shared.trimmedBaseUrl();
    const login = shared.isServiceEnabled("sso") ? shared.loginViaOauth2ProxyAndFriendica : shared.loginViaFriendicaDirect;
    // The login helper already lands on /network; watching starts before it
    // so icons it caches are recorded instead of being missed as cache hits.
    const watcher = watchSubresources(page);
    try {
      await login(page, shared.env.adminUsername, shared.env.adminPassword);
      await gotoOnion(page, `${baseUrl}/network`, { waitUntil: "load", timeout: resolveTimeout(90_000) });
      await expect(
        page.locator("#topbar-first, #navbar-apps-menu, a[href*='/logout']").first(),
        "Expected the authenticated Friendica surface on /network"
      ).toBeVisible({ timeout: resolveTimeout(30_000) });
      const networkSmileys = await smileySources(page);

      await gotoOnion(page, `${baseUrl}/smilies`, { waitUntil: "load", timeout: resolveTimeout(90_000) });
      const listedSmileys = await smileySources(page);
      expect(
        listedSmileys.length,
        "Expected /smilies to render the smiley list as img.smiley elements"
      ).toBeGreaterThan(0);

      const neverFetched = [...new Set([...networkSmileys, ...listedSmileys])].filter(
        (src) => !watcher.observed.has(src) && new URL(src).pathname !== UPSTREAM_MISSING_ICON
      );
      expect(
        neverFetched,
        `Smiley icons rendered without any observed HTTP response:\n${neverFetched.join("\n")}`
      ).toEqual([]);
      const failures = watcher.failures();
      expect(
        failures,
        `Images or tracker requests that did not answer 2xx:\n${failures.join("\n")}`
      ).toEqual([]);
    } finally {
      watcher.stop();
      await shared.friendicaLogout(page);
    }
  });
};
