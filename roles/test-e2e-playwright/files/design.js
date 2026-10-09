/**
 * Corporate design assertions and the gallery capture shared by every role
 * spec whose role consumes the `design` service.
 *
 * - `assertDesignTokens(page, label)`: the `--design-*` tokens are present and
 *   switch between light and dark mode.
 * - `tokenValue(page, token, property)`: the computed `property` of a probe
 *   styled with `var(token)`.
 * - `assertToken(page, selector, property, token, label)`: the computed
 *   `property` of the first `selector` match equals the value of `token`.
 * - `assertLightAndDark(page, selector, label)`: the surface behind the first
 *   `selector` match is darker in dark mode than in light mode.
 * - `assertReadable(page, selectors, label, min)`: each element's text color
 *   reaches `min` contrast against its effective background in light and dark
 *   mode, measured with CSS transitions switched off. A selector is a string
 *   or `{ selector, optional: true }`; one that matches nothing visible fails
 *   unless it is optional, and at least one element must be measured.
 * - `galleryEnabled()`: true when `INFINITO_PLAYWRIGHT_KEEP=true`.
 * - `captureDesignGallery(page, views)`: per view, color mode and viewport one
 *   screenshot with the injected CSS/JS (`/reports/design/after/`), named
 *   `<view>-<mode>-<viewport>.png`. Each screenshot waits up to
 *   `SETTLE_TIMEOUT_MS` for finite animations to end.
 *   A view is `{ name, url, prepare?, afterOnly? }`: `prepare(page)` brings the
 *   opened page into the state to capture.
 *   `PLAYWRIGHT_GALLERY_VIEWS` (comma-separated names) limits the
 *   capture to those views.
 *   `PLAYWRIGHT_GALLERY_BEFORE=true` also captures every view with every
 *   injected snippet stripped from the document (`/reports/design/before/`).
 *   `afterOnly: true` skips that plain side for a state that only exists with
 *   the injected snippets; a plain side that still carries them fails the view.
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
const INJECTION_MARK = "infinito-inj";
const GALLERY_VIEWS = (process.env.PLAYWRIGHT_GALLERY_VIEWS || "")
  .split(",")
  .map((name) => name.trim())
  .filter(Boolean);
const GALLERY_SIDES = process.env.PLAYWRIGHT_GALLERY_BEFORE === "true" ? ["after", "before"] : ["after"];
const SETTLE_TIMEOUT_MS = 5_000;
const FREEZE_CSS = "*, *::before, *::after { transition: none !important; }";

async function settle(page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
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

async function carriesInjection(page) {
  return page.evaluate((mark) => {
    const walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
    while (walker.nextNode()) {
      if (walker.currentNode.data === mark) return true;
    }
    return false;
  }, INJECTION_MARK);
}

async function openView(page, view, side) {
  await gotoOnion(page, view.url);
  // A redirect the browser follows and a hash route inside the loaded document both bypass page.route(), so the document is loaded once more by the URL it ended on.
  if (side === "before" && (await carriesInjection(page))) {
    const landed = page.url();
    await gotoOnion(page, "about:blank");
    await gotoOnion(page, landed);
  }
  if (view.prepare) await view.prepare(page);
  if (side === "before") {
    expect(
      await carriesInjection(page),
      "the plain side still carries the injected snippets; open the view by the URL its document ends on",
    ).toBe(false);
  }
}

async function tokenValue(page, token, property) {
  return page.evaluate(
    ([name, cssProperty]) => {
      const probe = document.createElement("span");
      probe.style.setProperty(cssProperty, `var(${name})`);
      document.body.appendChild(probe);
      const value = getComputedStyle(probe).getPropertyValue(cssProperty);
      probe.remove();
      return value;
    },
    [token, property],
  );
}

async function assertToken(page, selector, property, token, label) {
  const expected = await tokenValue(page, token, property);
  await expect
    .poll(
      () =>
        page
          .locator(selector)
          .first()
          .evaluate((element, cssProperty) => getComputedStyle(element).getPropertyValue(cssProperty), property),
      { message: `${label}: ${selector} ${property} must equal ${token}` },
    )
    .toBe(expected);
}

async function assertDesignTokens(page, label) {
  const seen = {};
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    seen[mode] = {
      primary: await page.evaluate(() =>
        getComputedStyle(document.documentElement).getPropertyValue("--design-primary").trim(),
      ),
      surface: await tokenValue(page, "--design-surface-1", "color"),
    };
    expect(seen[mode].primary, `${label}: --design-primary missing in ${mode} mode`).not.toBe("");
  }
  expect(
    seen.dark.surface,
    `${label}: --design-surface-1 must change between light and dark mode`,
  ).not.toBe(seen.light.surface);
  await page.emulateMedia({ colorScheme: null });
}

async function measure(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el || el.getClientRects().length === 0 || getComputedStyle(el).visibility === "hidden") return null;
    const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    const rgba = (value) => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = value;
      ctx.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    let background = [255, 255, 255];
    for (let cur = el; cur; cur = cur.parentElement) {
      const [r, g, b, a] = rgba(getComputedStyle(cur).backgroundColor);
      if (a > 0.5) {
        background = [r, g, b];
        break;
      }
    }
    const [r, g, b, a] = rgba(getComputedStyle(el).color);
    return { background, color: [r, g, b].map((channel, i) => a * channel + (1 - a) * background[i]) };
  }, selector);
}

function luminance([r, g, b]) {
  const lin = (c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

async function assertLightAndDark(page, selector, label) {
  await page.addStyleTag({ content: FREEZE_CSS });
  const seen = {};
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await settle(page);
    const sample = await measure(page, selector);
    expect(sample, `${label}: '${selector}' matches nothing visible in ${mode} mode`).not.toBeNull();
    seen[mode] = luminance(sample.background);
  }
  await page.emulateMedia({ colorScheme: null });
  expect(
    seen.dark,
    `${label}: the surface behind '${selector}' must be darker in dark mode than in light mode`,
  ).toBeLessThan(seen.light);
}

async function assertReadable(page, selectors, label, min = 4.5) {
  const entries = selectors.map((entry) => (typeof entry === "string" ? { selector: entry } : entry));
  await page.addStyleTag({ content: FREEZE_CSS });
  let measured = 0;
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await settle(page);
    for (const { selector, optional } of entries) {
      const sample = await measure(page, selector);
      if (sample === null) {
        expect(optional === true, `${label}: '${selector}' matches nothing visible in ${mode} mode`).toBe(true);
        continue;
      }
      measured += 1;
      const [fg, bg] = [luminance(sample.color), luminance(sample.background)];
      const ratio = (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
      expect(
        ratio,
        `${label}: '${selector}' reaches contrast ${ratio.toFixed(2)} in ${mode} mode (needs ${min})`,
      ).toBeGreaterThanOrEqual(min);
    }
  }
  await page.emulateMedia({ colorScheme: null });
  expect(measured, `${label}: no element was measured`).toBeGreaterThan(0);
}

function galleryEnabled() {
  return process.env.INFINITO_PLAYWRIGHT_KEEP === "true";
}

/**
 * @param {import('@playwright/test').Page} page
 * @param {{name: string, url: string, prepare?: (page) => Promise<void>, afterOnly?: boolean}[]} views
 */
async function captureDesignGallery(page, views) {
  if (!galleryEnabled()) return;
  const wanted = views.filter((view) => GALLERY_VIEWS.length === 0 || GALLERY_VIEWS.includes(view.name));
  const original = page.viewportSize();
  const failures = [];
  // Chromium counts the fulfilled "before" document as public address space and blocks its cross-origin assets on the local stack.
  await page.context().grantPermissions(["local-network-access"]);
  for (const side of GALLERY_SIDES) {
    if (side === "before") await page.route("**/*", stripInjectedSnippets);
    for (const [viewport, size] of Object.entries(VIEWPORTS)) {
      await page.setViewportSize(size);
      for (const view of wanted) {
        if (side === "before" && view.afterOnly === true) continue;
        for (const mode of MODES) {
          const file = `${view.name}-${mode}-${viewport}.png`;
          try {
            await page.emulateMedia({ colorScheme: mode });
            await openView(page, view, side);
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
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
  tokenValue,
};
