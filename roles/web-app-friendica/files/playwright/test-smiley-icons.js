const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

const MATOMO_TRACKER_PATH = /\/matomo\.php$/;
const UPSTREAM_MISSING_ICON = "/addon/smiley_pack/icons/opensource/vivaldi.png";

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

function watchSubresources(page) {
  const observed = new Set();
  const failures = [];
  const onResponse = (response) => {
    const request = response.request();
    if (!isTrackedRequest(request)) return;
    observed.add(request.url());
    const status = response.status();
    if (!isSuccess(status)) failures.push(`${status} ${request.url()}`);
  };
  const onRequestFailed = (request) => {
    if (!isTrackedRequest(request)) return;
    const failure = request.failure();
    failures.push(`${failure ? failure.errorText : "request failed"} ${request.url()}`);
  };
  page.on("response", onResponse);
  page.on("requestfailed", onRequestFailed);
  return {
    observed,
    failures,
    stop() {
      page.off("response", onResponse);
      page.off("requestfailed", onRequestFailed);
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
      expect(
        watcher.failures,
        `Images or tracker requests that did not answer 2xx:\n${watcher.failures.join("\n")}`
      ).toEqual([]);
    } finally {
      watcher.stop();
      await shared.friendicaLogout(page);
    }
  });
};
