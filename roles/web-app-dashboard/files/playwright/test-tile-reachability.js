// One parameterised test per role declared as a dashboard consumer in
// its meta/services.yml. The role list is emitted into
// DASHBOARD_TARGET_ROLES_JSON at deploy time by the env template via the
// `roles_with_service('dashboard')` Ansible filter, so this spec — and
// ONLY this spec — owns the per-role tile assertion. Other roles'
// personas no longer drive the dashboard click; they go straight to the
// app URL.

const { test, expect } = require("@playwright/test");

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
  const visible = await tile.isVisible({ timeout: 5_000 }).catch(() => false);

  if (!visible) {
    // Tile may be hidden inside a collapsed Bootstrap dropdown / accordion.
    const triggers = page.locator(
      "[data-bs-toggle='dropdown'], [data-bs-toggle='collapse'], [aria-expanded='false']"
    );
    const triggerCount = await triggers.count().catch(() => 0);
    for (let i = 0; i < triggerCount; i++) {
      const t = triggers.nth(i);
      if (!(await t.isVisible({ timeout: 200 }).catch(() => false))) continue;
      await t.click({ timeout: 1_000 }).catch(() => {});
    }
  }

  await expect(
    tile,
    `dashboard tile for ${canonicalDomain} MUST be visible`
  ).toBeVisible({ timeout: 30_000 });
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
      timeout: 30_000,
      message: `Expected dashboard URL to embed ${target.canonical_domain} via ?iframe=... after clicking the ${target.id} tile`,
    })
    .toContain(target.canonical_domain);

  const iframe = page.locator("#main iframe").first();
  await expect(
    iframe,
    `Expected #main iframe to be present after clicking the ${target.id} tile`
  ).toBeVisible({ timeout: 30_000 });

  const iframeSrc = await iframe.getAttribute("src");
  expect(
    iframeSrc || "",
    `Expected #main iframe src to point at ${target.canonical_domain}, got ${iframeSrc}`
  ).toContain(target.canonical_domain);
}

async function assertTileNavigatesTopLevel(page, context, target) {
  const tile = await findVisibleTile(page, target.canonical_domain);

  const href = await tile.getAttribute("href");
  expect(href, `tile for ${target.id} MUST carry an href`).toBeTruthy();
  expect(href, `tile href MUST point at ${target.canonical_domain}`).toContain(
    target.canonical_domain
  );

  const framingProbe = await page.request.get(
    target.canonical_url || `https://${target.canonical_domain}`,
    { ignoreHTTPSErrors: true }
  );
  const xFrameOptions = (framingProbe.headers()["x-frame-options"] || "").trim();
  expect(
    xFrameOptions,
    `iframe:false target ${target.id} must not send a framing-blocking X-Frame-Options (got "${xFrameOptions}"); fix the header or use iframe:true`
  ).toBe("");
  const cspHeader = framingProbe.headers()["content-security-policy"] || "";
  const frameAncestors = (cspHeader.match(/frame-ancestors([^;]*)/i) || ["", ""])[1].trim();
  if (frameAncestors) {
    expect(
      frameAncestors,
      `iframe:false target ${target.id} CSP frame-ancestors must permit the dashboard origin (got "${frameAncestors}")`
    ).toMatch(/\*|dashboard/i);
  }

  // iframe:false cards omit the `iframe-link` class, so clicking is a plain
  // anchor activation: it either navigates the top window in place or opens a
  // new tab (target=_blank). Either way the canonical domain must be reached
  // WITHOUT an embedded #main iframe, since SPAs like Keycloak's admin console
  // force a top-window redirect that would shatter the embed.
  const popupPromise = context
    .waitForEvent("page", { timeout: 15_000 })
    .catch(() => null);
  await tile.click();
  const popup = await popupPromise;

  if (popup) {
    await popup
      .waitForLoadState("domcontentloaded", { timeout: 30_000 })
      .catch(() => {});
    expect(
      popup.url(),
      `Expected new-tab URL to contain ${target.canonical_domain}, got ${popup.url()}`
    ).toContain(target.canonical_domain);
    await popup.close();
    return;
  }

  await expect
    .poll(() => page.url(), {
      timeout: 30_000,
      message: `Expected top-level navigation to ${target.canonical_domain} after clicking the ${target.id} tile`,
    })
    .toContain(target.canonical_domain);

  await expect(
    page.locator("#main iframe"),
    `Expected NO #main iframe for the non-embeddable ${target.id} tile`
  ).toHaveCount(0);
}

async function assertTabButtonOpensNewTab(page, context, target) {
  // The Tab anchor carries no href (role=generic, not link) and its
  // textContent is "<icon>\n Tab\n" (a /^tab$/ RegExp never matches), so the
  // stable handle is its onclick=openIframeInNewTab().
  const tabButton = page
    .locator('nav.menu-header a[onclick*="openIframeInNewTab"]')
    .first();

  // Embedding a tile calls enterFullscreen(), which adds body.fullscreen.
  // default.css then collapses the header to max-height:0, so the Tab item
  // (and the Toggle control next to it) exist in the DOM but have a zero box
  // and read as not-visible; neither can be clicked while collapsed. Exit
  // fullscreen via the globally-exposed exitFullscreen() to restore the
  // header; it only clears ?fullscreen=, leaving ?iframe= set so
  // openIframeInNewTab() still pops the embedded URL.
  if (!(await tabButton.isVisible().catch(() => false))) {
    await page.evaluate(() => window.exitFullscreen && window.exitFullscreen());
  }

  await expect(
    tabButton,
    `Expected the dashboard header "Tab" button to be visible for the ${target.id} tile`
  ).toBeVisible({ timeout: 30_000 });

  const [popup] = await Promise.all([
    context.waitForEvent("page", { timeout: 30_000 }),
    tabButton.click(),
  ]);

  await popup.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
  expect(
    popup.url(),
    `Expected popup tab URL to contain ${target.canonical_domain}, got ${popup.url()}`
  ).toContain(target.canonical_domain);
  await popup.close();
}

exports.register = function (shared) {
  for (const target of dashboardTargetRoles) {
    // iframe defaults to true so existing embeddable cards keep the original
    // assertion; only targets that explicitly opt out (services.dashboard.iframe
    // === false, e.g. web-app-keycloak) take the top-level-navigation branch.
    const embeddable = target.iframe !== false;
    if (embeddable) {
      test(`dashboard tile for ${target.id} embeds ${target.canonical_domain} in iframe and opens it in a new tab`, async ({ page, context }) => {
        await page.goto("/", { waitUntil: "domcontentloaded" });
        await shared.waitForDashboardReady(page);
        await assertTileLoadsInIframe(page, target);
        await assertTabButtonOpensNewTab(page, context, target);
      });
    } else {
      test(`dashboard tile for ${target.id} opens ${target.canonical_domain} via top-level navigation`, async ({ page, context }) => {
        await page.goto("/", { waitUntil: "domcontentloaded" });
        await shared.waitForDashboardReady(page);
        await assertTileNavigatesTopLevel(page, context, target);
      });
    }
  }
};
