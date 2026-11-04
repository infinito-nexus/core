const { test, expect } = require("./fixtures/onion-test");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvJsonList,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const gatedTiles = decodeDotenvJsonList(process.env.DASHBOARD_GATED_TILES_JSON, "DASHBOARD_GATED_TILES_JSON");
const HEALTH_STATES = ["running", "paused", "degraded", "down", "unknown"];
const statusEnabled = decodeDotenvQuotedValue(process.env.DASHBOARD_STATUS_ENABLED) === "true";
const statusStaleAfterSeconds = Number(
  requireDotenvValue(process.env.DASHBOARD_STATUS_STALE_AFTER_SECONDS, "DASHBOARD_STATUS_STALE_AFTER_SECONDS"),
);
const locksEnabled = decodeDotenvQuotedValue(process.env.DASHBOARD_LOCKS_ENABLED) === "true";

function tile(page, id) {
  return page.locator(`.portui-main > [data-portui-id="${id}"]`);
}

async function openDashboard(page, path) {
  await page.addInitScript(() => {
    document.addEventListener("dashboard:identity", (event) => {
      window.__portuiIdentity = event.detail.groups;
    });
  });
  await gotoOnion(page, path, { waitUntil: "domcontentloaded" });
}

async function identity(page) {
  await expect
    .poll(() => page.evaluate(() => window.__portuiIdentity !== undefined), {
      timeout: resolveTimeout(60_000),
      message: "Expected oidc.js to announce the visitor's groups through the dashboard:identity event",
    })
    .toBe(true);
  return page.evaluate(() => window.__portuiIdentity);
}

async function signIn(page, shared, username, password) {
  await openDashboard(page, "/");
  await shared.waitForDashboardReady(page);
  await page.locator("nav.menu-header").locator("a, button").filter({ hasText: /login/i }).first().click({
    timeout: resolveTimeout(30_000),
  });
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => page.url().startsWith(appBaseUrl), {
      timeout: resolveTimeout(60_000),
      message: `Expected Keycloak login to redirect back to the dashboard: ${appBaseUrl}`,
    })
    .toBe(true);
  await shared.waitForDashboardReady(page);
}

/**
 * Args:
 *   page: a dashboard page after the identity event.
 *   groups: the groups oidc.js announced, null for an anonymous visitor.
 * Returns: the number of gated tiles that show a lock.
 */
async function expectLocks(page, shared, groups) {
  const data = await shared.dashboardData(page);
  let locked = 0;
  for (const gated of gatedTiles) {
    const card = data.cards.find((entry) => entry.key === gated.id);
    expect(card, `Expected a dashboard card for the gated application ${gated.id}`).toBeTruthy();
    const expectLock = groups === null || !groups.some((group) => gated.allowed_groups.includes(group));
    const lock = tile(page, gated.id).locator(".portui-chip-lock");
    await expect(lock, `${gated.id}: lock ${expectLock ? "expected" : "unexpected"} for ${JSON.stringify(groups)}`)
      .toHaveCount(expectLock ? 1 : 0, { timeout: resolveTimeout(30_000) });
    if (expectLock && groups === null) {
      await expect(lock).toHaveAttribute("data-portui-state", "signin");
    }
    locked += expectLock ? 1 : 0;
  }
  return locked;
}

exports.register = function (shared) {
  test("folders: the top level shows folders, a folder opens by URL, and back and forward walk the history", async ({
    page,
  }) => {
    await openDashboard(page, "/");
    await shared.waitForDashboardReady(page);

    const folders = page.locator(".portui-main > [data-portui-folder]:visible");
    await expect(folders.first(), "Expected folder tiles at the top level").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    const filed = page.locator(".portui-main > [data-portui-id]:visible");
    await expect(filed, "Expected every filed application to stay inside its folder at the top level").toHaveCount(0);

    const path = await folders.first().getAttribute("data-portui-folder");
    await folders.first().locator("a.portui-folder-link").click();
    await expect.poll(() => new URL(page.url()).searchParams.get("folder")).toBe(path);
    await expect(page.locator(".portui-breadcrumb .breadcrumb-item.active a[aria-current='page']")).toBeVisible();
    await expect(page.locator(".portui-main > [data-portui-id]:visible, .portui-main > [data-portui-folder]:visible").first())
      .toBeVisible();

    await expect(page.locator("button.portui-back")).toBeEnabled();
    await page.locator("button.portui-back").click();
    await expect.poll(() => new URL(page.url()).searchParams.get("folder")).toBe(null);
    await expect(page.locator("button.portui-forward")).toBeEnabled();
    await page.locator("button.portui-forward").click();
    await expect.poll(() => new URL(page.url()).searchParams.get("folder")).toBe(path);

    await page.reload({ waitUntil: "domcontentloaded" });
    await shared.waitForDashboardReady(page);
    await expect(page.locator(`.portui-breadcrumb a[data-portui-folder-link="${path}"]`)).toBeVisible();
  });

  test("search: typing lists matching applications in the picker and Enter keeps the query in the URL", async ({
    page,
  }) => {
    await openDashboard(page, "/");
    await shared.waitForDashboardReady(page);
    const data = await shared.dashboardData(page);
    const card = data.cards.find((entry) => entry.key && entry.title);
    expect(card, "Expected at least one titled application card").toBeTruthy();

    const field = page.locator("#portui-search");
    await field.fill(card.title);
    const rows = page.locator("#portui-picker [role='option']");
    await expect(rows.filter({ hasText: card.title }).first()).toBeVisible({ timeout: resolveTimeout(10_000) });

    await field.press("Escape");
    await field.press("Enter");
    await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(card.title);
    await expect(tile(page, card.key)).toBeVisible();

    await page.reload({ waitUntil: "domcontentloaded" });
    await shared.waitForDashboardReady(page);
    await expect(field).toHaveValue(card.title);
    await expect(tile(page, card.key)).toBeVisible();
  });

  test("health: every application tile carries a health badge fed by /status.json", async ({ page }) => {
    test.skip(!statusEnabled, "the dashboard's health badges are switched off");
    const status = await page.request.get(`${appBaseUrl}/status.json`, { ignoreHTTPSErrors: true });
    expect(status.status(), "Expected the dashboard to serve the health sweep's status document").toBe(200);
    expect(status.headers()["content-type"]).toMatch(/application\/json/);
    const document_ = await status.json();
    expect(typeof document_.applications, "Expected the status document to map applications").toBe("object");

    await openDashboard(page, "/");
    await shared.waitForDashboardReady(page);
    const data = await shared.dashboardData(page);
    const ids = data.cards.map((card) => card.key).filter(Boolean);
    expect(ids.length).toBeGreaterThan(0);
    expect(
      Object.keys(document_.applications).filter((id) => !ids.includes(id)),
      "The public status document must name dashboard applications only",
    ).toEqual([]);
    for (const id of ids) {
      const badge = tile(page, id).locator(".portui-chip-health");
      await expect(badge, `${id}: expected one health badge`).toHaveCount(1, { timeout: resolveTimeout(30_000) });
      const entry = document_.applications[id];
      const fresh = entry && Date.now() - Date.parse(entry.checked) <= statusStaleAfterSeconds * 1000;
      const expected = fresh && HEALTH_STATES.includes(entry.state) ? entry.state : "unknown";
      await expect(badge, `${id}: the badge must show the state of the status document`).toHaveAttribute(
        "data-portui-state",
        expected,
        { timeout: resolveTimeout(30_000) },
      );
    }
  });

  test("locks: an anonymous visitor sees a sign-in lock on every gated tile", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.skip(!locksEnabled, "the dashboard's lock chips are switched off");
    test.skip(gatedTiles.length === 0, "this deployment gates no dashboard application behind oauth2-proxy groups");
    await openDashboard(page, "/");
    await shared.waitForDashboardReady(page);
    expect(await identity(page)).toBe(null);
    expect(await expectLocks(page, shared, null)).toBe(gatedTiles.length);
  });

  test("locks: biber sees a lock on gated tiles outside biber's groups", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.skip(!locksEnabled, "the dashboard's lock chips are switched off");
    test.skip(gatedTiles.length === 0, "this deployment gates no dashboard application behind oauth2-proxy groups");
    await signIn(
      page,
      shared,
      decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
      decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
    );
    const groups = await identity(page);
    expect(Array.isArray(groups), "Expected a signed-in visitor's groups to be a list").toBe(true);
    expect(await expectLocks(page, shared, groups), "Expected biber to meet at least one locked tile").toBeGreaterThan(0);
  });

  test("locks: the administrator opens gated tiles of the administrator groups without a lock", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.skip(!locksEnabled, "the dashboard's lock chips are switched off");
    test.skip(gatedTiles.length === 0, "this deployment gates no dashboard application behind oauth2-proxy groups");
    await signIn(
      page,
      shared,
      decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
      decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
    );
    const groups = await identity(page);
    expect(await expectLocks(page, shared, groups), "Expected the administrator to open at least one gated tile").toBeLessThan(
      gatedTiles.length,
    );
  });
};
