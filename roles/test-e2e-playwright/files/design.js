/**
 * Corporate design assertions and the before/after gallery capture shared by
 * every role spec whose role consumes the `design` service.
 *
 * - `assertDesignTokens(page, label)`: the `--design-*` tokens are present and
 *   switch between light and dark mode.
 * - `assertReadable(page, selectors, label, min)`: each visible element's text
 *   color reaches `min` contrast against its effective background.
 * - `galleryEnabled()`: true when `INFINITO_PLAYWRIGHT_KEEP=true`.
 * - `captureDesignGallery(page, views)`: per view, color mode and viewport one
 *   screenshot with the injected CSS/JS (`/reports/design/after/`) and one with
 *   every injected snippet stripped from the document
 *   (`/reports/design/before/`), named `<view>-<mode>-<viewport>.png`. Each
 *   screenshot waits up to `SETTLE_TIMEOUT_MS` for finite animations to end.
 */

const { expect } = require("@playwright/test");

const { gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
};
const GALLERY_DIR = "/reports/design";
const INJECTED_SNIPPETS = /<!--infinito-inj-->[\s\S]*?<!--\/infinito-inj-->/g;
const SETTLE_TIMEOUT_MS = 5_000;

async function settle(page) {
  await page
    .waitForFunction(
      () =>
        document
          .getAnimations()
          .every((a) => a.playState !== "running" || a.effect?.getComputedTiming().iterations === Infinity),
      null,
      { timeout: resolveTimeout(SETTLE_TIMEOUT_MS) },
    )
    .catch(() => {});
}

async function stripInjectedSnippets(route) {
  if (route.request().resourceType() !== "document") return route.continue();
  const response = await route.fetch({ maxRedirects: 0 });
  if (response.status() >= 300 && response.status() < 400) return route.fulfill({ response });
  const body = (await response.text()).replace(INJECTED_SNIPPETS, "");
  return route.fulfill({ response, body });
}

async function readTokens(page) {
  return page.evaluate(() => {
    const probe = (name) => {
      const el = document.createElement("span");
      el.style.color = `var(${name})`;
      document.body.appendChild(el);
      const value = getComputedStyle(el).color;
      el.remove();
      return value;
    };
    const root = getComputedStyle(document.documentElement);
    return {
      primary: root.getPropertyValue("--design-primary").trim(),
      surface: probe("--design-surface-1"),
      text: probe("--design-text"),
    };
  });
}

async function assertDesignTokens(page, label) {
  const seen = {};
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    seen[mode] = await readTokens(page);
    expect(seen[mode].primary, `${label}: --design-primary missing in ${mode} mode`).not.toBe("");
  }
  expect(
    seen.dark.surface,
    `${label}: --design-surface-1 must change between light and dark mode`,
  ).not.toBe(seen.light.surface);
  await page.emulateMedia({ colorScheme: null });
}

async function contrastOf(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el || !el.offsetParent) return null;
    const rgba = (value) => (value.match(/[\d.]+/g) || []).map(Number);
    const background = (node) => {
      for (let cur = node; cur; cur = cur.parentElement) {
        const [r, g, b, a = 1] = rgba(getComputedStyle(cur).backgroundColor);
        if (a > 0.5) return [r, g, b];
      }
      return [255, 255, 255];
    };
    const luminance = ([r, g, b]) => {
      const lin = (c) => {
        const s = c / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    };
    const fg = luminance(rgba(getComputedStyle(el).color));
    const bg = luminance(background(el));
    return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
  }, selector);
}

async function assertReadable(page, selectors, label, min = 4.5) {
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    for (const selector of selectors) {
      const ratio = await contrastOf(page, selector);
      if (ratio === null) continue;
      expect(
        ratio,
        `${label}: '${selector}' reaches contrast ${ratio.toFixed(2)} in ${mode} mode (needs ${min})`,
      ).toBeGreaterThanOrEqual(min);
    }
  }
  await page.emulateMedia({ colorScheme: null });
}

/**
 * @param {import('@playwright/test').Page} page
 * @param {{name: string, url: string, prepare?: (page) => Promise<void>}[]} views
 */
function galleryEnabled() {
  return process.env.INFINITO_PLAYWRIGHT_KEEP === "true";
}

async function captureDesignGallery(page, views) {
  if (!galleryEnabled()) return;
  const original = page.viewportSize();
  const failures = [];
  // Chromium counts the fulfilled "before" document as public address space and blocks its cross-origin assets on the local stack.
  await page.context().grantPermissions(["local-network-access"]);
  for (const side of ["after", "before"]) {
    if (side === "before") await page.route("**/*", stripInjectedSnippets);
    for (const [viewport, size] of Object.entries(VIEWPORTS)) {
      await page.setViewportSize(size);
      for (const view of views) {
        for (const mode of MODES) {
          const file = `${view.name}-${mode}-${viewport}.png`;
          try {
            await page.emulateMedia({ colorScheme: mode });
            await gotoOnion(page, view.url);
            if (view.prepare) await view.prepare(page);
            await settle(page);
            await page.screenshot({ path: `${GALLERY_DIR}/${side}/${file}` });
          } catch (error) {
            failures.push(`${side}/${file}: ${error.message.split("\n")[0]}`);
          }
        }
      }
    }
    if (side === "before") await page.unroute("**/*", stripInjectedSnippets);
  }
  await page.emulateMedia({ colorScheme: null });
  if (original) await page.setViewportSize(original);
  expect(failures, `design gallery views failed:\n${failures.join("\n")}`).toEqual([]);
}

module.exports = {
  assertDesignTokens,
  assertReadable,
  captureDesignGallery,
  galleryEnabled,
};
