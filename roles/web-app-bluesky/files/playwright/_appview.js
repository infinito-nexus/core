const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiFetchOnion, apiGetOnion } = require("./personas");

const LXM_PATTERN = /lxm|lexicon method/i;
const PROXIED_METHODS = ["app.bsky.feed.getTimeline", "app.bsky.notification.listNotifications"];
const PERSONAL_DETAILS = "app.bsky.actor.defs#personalDetailsPref";
const ADULT_BIRTHDATE = "1990-01-01";

async function expectPdsProxiesAppView(request, pdsBaseUrl, accessJwt) {
  for (const nsid of PROXIED_METHODS) {
    const response = await apiGetOnion(request, `${pdsBaseUrl}/xrpc/${nsid}`, {
      headers: { authorization: `Bearer ${accessJwt}` },
      timeout: resolveTimeout(30_000),
    });
    const body = await response.text();
    expect(
      response.status(),
      `PDS must proxy ${nsid} to PDS_BSKY_APP_VIEW_URL with a service JWT the AppView accepts (got body: ${body})`,
    ).toBe(200);
  }
}

async function brokerAccessJwt(page) {
  let accessJwt = "";
  await expect
    .poll(
      async () => {
        accessJwt = await page
          .evaluate(() => JSON.parse(localStorage.getItem("BSKY_STORAGE") || "{}").session?.currentAccount?.accessJwt || "")
          .catch(() => "");
        return accessJwt;
      },
      { timeout: resolveTimeout(60_000), message: "broker handoff left no accessJwt in BSKY_STORAGE" },
    )
    .not.toBe("");
  return accessJwt;
}

async function readPreferences(request, pdsBaseUrl, accessJwt) {
  const response = await apiGetOnion(request, `${pdsBaseUrl}/xrpc/app.bsky.actor.getPreferences`, {
    headers: { authorization: `Bearer ${accessJwt}` },
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), `PDS getPreferences must return 200 (got body: ${await response.text()})`).toBe(200);
  return (await response.json()).preferences;
}

async function restorePreferences(request, pdsBaseUrl, accessJwt, preferences) {
  if (preferences.some((entry) => entry.$type === PERSONAL_DETAILS && entry.birthDate)) return;
  const restore = apiFetchOnion(request, `${pdsBaseUrl}/xrpc/app.bsky.actor.putPreferences`, {
    method: "POST",
    headers: { authorization: `Bearer ${accessJwt}`, "content-type": "application/json" },
    data: { preferences },
    timeout: resolveTimeout(30_000),
  }).then((response) => {
    if (response.status() !== 200) throw new Error(`putPreferences answered ${response.status()}`);
  });
  const deadline = new Promise((_, reject) => {
    setTimeout(() => reject(new Error("putPreferences timed out")), resolveTimeout(45_000));
  });
  await Promise.race([restore, deadline]).catch((err) => console.warn(`bluesky: preferences not restored: ${err.message}`));
}

function collectAppViewResponses(page) {
  const seen = [];
  page.on("response", (response) => {
    const { pathname } = new URL(response.url());
    if (!pathname.startsWith("/xrpc/app.bsky.") || response.request().method() !== "GET") return;
    const status = response.status();
    seen.push({
      nsid: pathname.slice("/xrpc/".length),
      status,
      body: status === 200 ? Promise.resolve("") : response.text().catch((err) => `<body unavailable: ${err.message}>`),
    });
  });
  return seen;
}

async function waitForResponseTo(seen, nsid, from = 0) {
  await expect
    .poll(() => seen.slice(from).some((entry) => entry.nsid === nsid), {
      timeout: resolveTimeout(60_000),
      message: `social-app never requested ${nsid}`,
    })
    .toBe(true);
}

async function expectNoFailures(seen, nsid) {
  const failed = seen.filter((entry) => entry.nsid === nsid && entry.status !== 200);
  expect(
    await Promise.all(failed.map(async (entry) => `${entry.status} ${await entry.body}`)),
    `PDS must proxy ${nsid} to the AppView with a service JWT the AppView accepts`,
  ).toEqual([]);
}

async function expectNoLxmRejections(seen, pageErrors) {
  const lines = await Promise.all(seen.map(async (entry) => `${entry.nsid} ${entry.status} ${await entry.body}`));
  expect(
    lines.filter((line) => LXM_PATTERN.test(line)),
    "no AppView call may be rejected for a missing lxm claim",
  ).toEqual([]);
  expect(
    pageErrors.filter((message) => LXM_PATTERN.test(message)),
    "social-app must not raise lxm page errors after login",
  ).toEqual([]);
}

async function reachFollowingFeed(page) {
  const home = page.getByTestId("followingFeedPage");
  const birthdateGate = page.getByRole("button", { name: "Click here to update your birthdate" }).first();
  await expect(async () => {
    if (await birthdateGate.isVisible()) {
      await birthdateGate.click();
      const dialog = page.getByTestId("birthDateSettingsDialog");
      await dialog.getByTestId("birthdayInput").fill(ADULT_BIRTHDATE);
      await dialog.getByRole("button", { name: "Save birthdate" }).click();
    }
    await expect(home).toBeVisible({ timeout: resolveTimeout(5_000) });
  }).toPass({ timeout: resolveTimeout(120_000) });
}

module.exports = {
  brokerAccessJwt,
  collectAppViewResponses,
  expectNoFailures,
  expectNoLxmRejections,
  expectPdsProxiesAppView,
  reachFollowingFeed,
  readPreferences,
  restorePreferences,
  waitForResponseTo,
};
