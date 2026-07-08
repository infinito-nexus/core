// One parameterised test per role declared as a dashboard consumer in
// its meta/services.yml. The role list is emitted into
// DASHBOARD_TARGET_ROLES_JSON at deploy time by the env template via the
// `roles_with_service('dashboard')` Ansible filter, so this spec — and
// ONLY this spec — owns the per-role tile assertion. Other roles'
// personas no longer drive the dashboard click; they go straight to the
// app URL.

const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const dashboardTargetRoles = (() => {
  const raw = process.env.DASHBOARD_TARGET_ROLES_JSON || "[]";
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
})();

async function findVisibleTile(page, canonicalDomain) {
  const tile = page.locator(`a[href*="${canonicalDomain}"]:visible`).first();
  const visible = await tile.isVisible({ timeout: resolveTimeout(5_000) }).catch(() => false);

  if (!visible) {
    // Tile may be hidden inside a collapsed Bootstrap dropdown / accordion.
    const triggers = page.locator(
      "[data-bs-toggle='dropdown'], [data-bs-toggle='collapse'], [aria-expanded='false']"
    );
    const triggerCount = await triggers.count().catch(() => 0);
    for (let i = 0; i < triggerCount; i++) {
      const t = triggers.nth(i);
      if (!(await t.isVisible({ timeout: resolveTimeout(200) }).catch(() => false))) continue;
      await t.click({ timeout: resolveTimeout(1_000) }).catch(() => {});
    }
  }

  await expect(
    tile,
    `dashboard tile for ${canonicalDomain} MUST be visible`
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  return tile;
}

async function assertTileLoadsInIframe(page, target) {
  const tile = await findVisibleTile(page, target.canonical_domain);

  const href = await tile.getAttribute("href");
  expect(href, `tile for ${target.id} MUST carry an href`).toBeTruthy();
  expect(href, `tile href MUST point at ${target.canonical_domain}`).toContain(
    target.canonical_domain
  );

  await tile.click();

  // The dashboard's iframe.js listener updates the outer URL's `?iframe=`
  // query param via the iframeLocationChange postMessage from the embedded
  // app — this confirms the click triggered an in-page embed, not a
  // top-level navigation.
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected dashboard URL to embed ${target.canonical_domain} via ?iframe=... after clicking the ${target.id} tile`,
    })
    .toContain(target.canonical_domain);

  const iframe = page.locator("#main iframe").first();
  await expect(
    iframe,
    `Expected #main iframe to be present after clicking the ${target.id} tile`
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  const iframeSrc = await iframe.getAttribute("src");
  expect(
    iframeSrc || "",
    `Expected #main iframe src to point at ${target.canonical_domain}, got ${iframeSrc}`
  ).toContain(target.canonical_domain);
}

async function assertTabButtonOpensNewTab(page, context, target) {
  // The "Tab" header item is rendered from menu/header.yml.j2 with
  // onclick="openIframeInNewTab()" and visible label "Tab" — it
  // pops the currently-embedded iframe URL into a fresh browser tab.
  const tabButton = page
    .locator("nav.menu-header")
    .locator("a, button")
    .filter({ hasText: /^tab$/i })
    .first();

  await expect(
    tabButton,
    `Expected the dashboard header "Tab" button to be visible for the ${target.id} tile`
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  const [popup] = await Promise.all([
    context.waitForEvent("page", { timeout: resolveTimeout(30_000) }),
    tabButton.click(),
  ]);

  await popup.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
  expect(
    popup.url(),
    `Expected popup tab URL to contain ${target.canonical_domain}, got ${popup.url()}`
  ).toContain(target.canonical_domain);
  await popup.close();
}

exports.register = function (shared) {
  for (const target of dashboardTargetRoles) {
    test(`dashboard tile for ${target.id} embeds ${target.canonical_domain} in iframe and opens it in a new tab`, async ({ page, context }) => {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await shared.waitForDashboardReady(page);
      await assertTileLoadsInIframe(page, target);
      await assertTabButtonOpensNewTab(page, context, target);
    });
  }
};
