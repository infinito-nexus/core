const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
  tokenValue,
} = require("./design");
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const NARROW_BELOW = 768;
const ICONS_HIDDEN_BELOW = 576;
const SYMBOL_ONLY_WIDTH = 900;
const HEADER = ".mantine-AppShell-header";
const DRAWER = ".mantine-AppShell-navbar";
const LOGO = `${HEADER} a > .mantine-Group-root > img`;
const EDITOR = "main .cm-content";
const EXECUTE = "main button.mantine-Button-root[data-variant='primary']";
const TABLE = "main .mantine-Table-table";
const ROW = "main .mantine-Table-tbody .mantine-Table-tr";
const CELL = "main .mantine-Table-tbody .mantine-Table-td";
const GROUP = "main .mantine-Accordion-item";
const GROUP_CONTROL = "main .mantine-Accordion-control";
const CARD = "main .mantine-Card-root";
const BADGE = "main .mantine-Badge-root";
const MENU = ".mantine-Menu-dropdown";
const POPOVER = ".mantine-Popover-dropdown";
const MODAL = ".mantine-Modal-content";
const CHECKED_BOX = `${POPOVER} .mantine-Checkbox-input:checked`;
const THEME_SWITCH = "button[aria-label^='Switch to']";
const SCHEME_KEY = "mantine-color-scheme-value";

const base = decodeDotenvQuotedValue(process.env.PROMETHEUS_BASE_URL).replace(/\/$/, "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

/**
 * Args:
 *   page: Playwright page whose finite animations must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            new Promise((resolve) => {
              requestAnimationFrame(() =>
                requestAnimationFrame(() =>
                  resolve(
                    document
                      .getAnimations()
                      .some(
                        (animation) =>
                          animation.playState === "running" &&
                          animation.effect?.getComputedTiming().iterations !== Infinity,
                      ),
                  ),
                ),
              );
            }),
        ),
      { message: "every finite animation of the page must have ended", timeout: resolveTimeout(10_000) },
    )
    .toBe(false);
}

/**
 * Args:
 *   page: Playwright page.
 *   path: route below the Prometheus base URL, with its query string.
 *   ready: CSS selector that is visible once the view rendered.
 */
async function open(page, path, ready) {
  await gotoOnion(page, `${base}${path}`);
  if (page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
    await gotoOnion(page, `${base}${path}`);
  }
  await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  await animationsSettled(page);
}

/**
 * Args:
 *   page: Playwright page.
 *   mode: "light" or "dark", the scheme the browser reports and the app must have followed.
 */
async function emulate(page, mode) {
  await page.emulateMedia({ colorScheme: mode });
  await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", mode);
}

function shown(ready) {
  return (page) => expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(20_000) });
}

function opened(ready, panel, trigger) {
  return async (page) => {
    await shown(ready)(page);
    await trigger(page);
    const target = page.locator(panel).first();
    await expect(target).toBeVisible({ timeout: resolveTimeout(10_000) });
    await animationsSettled(page);
    await expect(target).toHaveCSS("opacity", "1");
  };
}

async function openDrawerBelow(page, width) {
  if (page.viewportSize().width < width) {
    await page.locator(`${HEADER} .mantine-Burger-root`).click();
    await expect(page.locator(DRAWER)).toBeVisible({ timeout: resolveTimeout(10_000) });
    await animationsSettled(page);
  }
}

function chrome(page, width) {
  return page.locator(page.viewportSize().width < width ? DRAWER : HEADER);
}

function views() {
  const query = (expr, rest = "") => `${base}/query?g0.expr=${encodeURIComponent(expr)}${rest}`;
  const options = (page) => page.locator("main button[aria-label='Show query options']").first().click();
  return [
    { name: "query", url: `${base}/query`, prepare: shown(EDITOR) },
    { name: "query-table", url: query("up", "&g0.tab=table"), prepare: shown(TABLE) },
    { name: "query-graph", url: query("up", "&g0.tab=graph&g0.range_input=1h"), prepare: shown("main .uplot canvas") },
    {
      name: "query-explain",
      url: query("sum by (job) (up)", "&g0.tab=explain&g0.show_tree=1"),
      prepare: (page) =>
        expect(page.locator("main .mantine-Tabs-panel", { hasText: "Aggregation" })).toBeVisible({ timeout: resolveTimeout(20_000) }),
    },
    {
      name: "query-tree",
      url: query("sum by (job) (rate(prometheus_http_requests_total[5m]))", "&g0.show_tree=1"),
      prepare: shown("main button[aria-label='Close tree view']"),
    },
    { name: "query-error", url: query("up{", "&g0.tab=table"), prepare: shown("main .mantine-Alert-root") },
    { name: "query-empty-result", url: query("design_showcase_absent", "&g0.tab=table"), prepare: shown("main .mantine-Alert-root") },
    { name: "query-options", url: `${base}/query`, prepare: opened(EDITOR, MENU, options) },
    {
      name: "metrics-explorer",
      url: `${base}/query`,
      prepare: opened(EDITOR, `${MODAL} .mantine-Table-table`, async (page) => {
        await options(page);
        await page.locator(MENU).getByText("Explore metrics").click();
      }),
    },
    {
      name: "query-autocomplete",
      url: `${base}/query`,
      prepare: opened(EDITOR, ".cm-tooltip-autocomplete", async (page) => {
        await page.locator(EDITOR).first().click();
        await page.keyboard.type("prometheus_");
      }),
    },
    { name: "alerts", url: `${base}/alerts`, prepare: shown(GROUP) },
    {
      name: "alerts-open",
      url: `${base}/alerts`,
      prepare: opened(GROUP, "main .mantine-Accordion-panel .mantine-Card-root", (page) =>
        page.locator(GROUP_CONTROL).first().click(),
      ),
    },
    { name: "targets", url: `${base}/targets`, prepare: shown(GROUP) },
    {
      name: "rules-open",
      url: `${base}/rules`,
      prepare: opened(GROUP, "main .mantine-Accordion-panel", (page) => page.locator(GROUP_CONTROL).first().click()),
    },
    { name: "service-discovery", url: `${base}/service-discovery`, prepare: shown(GROUP) },
    { name: "status", url: `${base}/status`, prepare: shown(`${CARD} .mantine-Table-table`) },
    { name: "tsdb-status", url: `${base}/tsdb-status`, prepare: shown(`${CARD} .mantine-Table-table`) },
    { name: "flags", url: `${base}/flags`, prepare: shown(ROW) },
    { name: "config", url: `${base}/config`, prepare: shown("main pre code") },
    {
      name: "status-menu",
      url: `${base}/query`,
      prepare: opened(EDITOR, MENU, async (page) => {
        await openDrawerBelow(page, NARROW_BELOW);
        await chrome(page, NARROW_BELOW).getByRole("button", { name: "Status" }).click();
      }),
    },
    {
      name: "settings",
      url: `${base}/query`,
      prepare: opened(EDITOR, POPOVER, async (page) => {
        await openDrawerBelow(page, ICONS_HIDDEN_BELOW);
        await chrome(page, ICONS_HIDDEN_BELOW).locator("button[aria-label='Settings']").click();
      }),
    },
    {
      name: "navigation",
      url: `${base}/alerts`,
      prepare: async (page) => {
        await shown(GROUP)(page);
        await openDrawerBelow(page, NARROW_BELOW);
        await chrome(page, NARROW_BELOW).getByRole("link", { name: "Query" }).hover();
      },
    },
    {
      name: "navigation-focus",
      url: `${base}/alerts`,
      prepare: async (page) => {
        await shown(GROUP)(page);
        await openDrawerBelow(page, NARROW_BELOW);
        await chrome(page, NARROW_BELOW).getByRole("link", { name: "Alerts" }).focus();
        await page.keyboard.press("Shift+Tab");
      },
    },
    {
      name: "theme-switch",
      url: `${base}/query`,
      prepare: async (page) => {
        await shown(EDITOR)(page);
        await openDrawerBelow(page, ICONS_HIDDEN_BELOW);
        const toggle = chrome(page, ICONS_HIDDEN_BELOW).locator(THEME_SWITCH);
        await toggle.click();
        await expect(toggle).toHaveAttribute("aria-label", "Switch to dark theme");
        await toggle.click();
        await expect(toggle).toHaveAttribute("aria-label", "Switch to browser-preferred theme");
        await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", "dark");
        await page.evaluate((key) => window.localStorage.removeItem(key), SCHEME_KEY);
        if (page.viewportSize().width < ICONS_HIDDEN_BELOW) {
          await page.locator(`${HEADER} .mantine-Burger-root`).click();
          await animationsSettled(page);
          await expect
            .poll(
              async () => {
                const box = await page.locator(DRAWER).boundingBox();
                return box === null || box.x + box.width <= 0;
              },
              { message: "the drawer slid out of the viewport", timeout: resolveTimeout(10_000) },
            )
            .toBe(true);
        }
      },
    },
  ];
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/query", EDITOR);
    await assertDesignTokens(page, "prometheus");
  });

  test("design: page, primary action and text take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/query?g0.expr=up&g0.tab=table", TABLE);
    for (const mode of MODES) {
      await emulate(page, mode);
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, CELL, "color", "--design-text", `result ${mode}`);
      await assertToken(page, ROW, "border-bottom-color", "--design-border", `row divider ${mode}`);
      await page.mouse.move(0, 0);
      await assertToken(page, EXECUTE, "background-color", "--design-primary", `execute ${mode}`);
      await assertToken(page, EXECUTE, "color", "--design-on-primary", `execute ${mode}`);
      await page.locator(EXECUTE).first().hover();
      await assertToken(page, EXECUTE, "background-color", "--design-primary-hover", `hovered execute ${mode}`);
      await assertToken(page, EXECUTE, "color", "--design-on-primary", `hovered execute ${mode}`);
    }
    await page.mouse.move(0, 0);
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "body", "prometheus page");
    await assertReadable(page, [CELL, EXECUTE, "main .mantine-Tabs-tab"], "prometheus query page");
  });

  test("design: the header is the frame and keeps its focus indicator", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/alerts", GROUP);
    for (const mode of MODES) {
      await emulate(page, mode);
      await assertToken(page, HEADER, "background-color", "--design-frame", `header ${mode}`);
      await assertToken(page, `${HEADER} a[aria-current='page']`, "background-color", "--design-frame-active", `current entry ${mode}`);
      await assertToken(page, `${HEADER} a[aria-current='page']`, "color", "--design-on-frame", `current entry ${mode}`);
      await assertToken(page, `${HEADER} ${THEME_SWITCH}`, "color", "--design-on-frame", `header icon ${mode}`);
      await assertToken(page, `${HEADER} ${THEME_SWITCH}`, "background-color", "--design-frame-hover", `header icon ${mode}`);
      const outline = await tokenValue(page, "--design-on-frame", "outline-color");
      await page.locator(`${HEADER} a.mantine-Button-root`).first().focus();
      await page.keyboard.press("Shift+Tab");
      let stops = 0;
      for (; stops < 12; stops += 1) {
        const inFrame = await page.evaluate((selector) => Boolean(document.activeElement.closest(selector)), HEADER);
        if (!inFrame) break;
        const drawn = await page.evaluate(() => {
          const style = getComputedStyle(document.activeElement);
          return { color: style.outlineColor, style: style.outlineStyle, width: style.outlineWidth };
        });
        expect(drawn.style, `focus stop ${stops} ${mode}: an outline must be drawn`).not.toBe("none");
        expect(drawn.width, `focus stop ${stops} ${mode}: an outline must be drawn`).not.toBe("0px");
        expect(drawn.color, `focus stop ${stops} ${mode}: the outline takes --design-on-frame`).toBe(outline);
        await page.keyboard.press("Tab");
      }
      expect(stops, `the header holds focus stops in ${mode} mode`).toBeGreaterThan(3);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${HEADER} a.mantine-Button-root`, `${HEADER} a[aria-current='page']`], "prometheus header");
  });

  test("design: cards, rule groups and status badges take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/status", `${CARD} .mantine-Table-table`);
    for (const mode of MODES) {
      await emulate(page, mode);
      await assertToken(page, CARD, "background-color", "--design-surface-2", `card ${mode}`);
      await assertToken(page, `${CARD} .mantine-Table-tbody .mantine-Table-tr`, "border-bottom-color", "--design-border", `card row divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, CARD, "prometheus card");

    await open(page, "/alerts", GROUP);
    for (const mode of MODES) {
      await emulate(page, mode);
      await assertToken(page, GROUP, "background-color", "--design-surface-3", `rule group ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [GROUP_CONTROL, BADGE], "prometheus alerts");
  });

  test("design: the native theme switch drives the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await open(page, "/query", EDITOR);
    const html = page.locator("html");
    const toggle = page.locator(`${HEADER} ${THEME_SWITCH}`);
    const designTheme = () => html.getAttribute("data-design-theme");
    await expect(html).toHaveAttribute("data-mantine-color-scheme", "light");
    expect(await designTheme(), "the browser preference decides while the app follows it").toBeNull();
    const light = await tokenValue(page, "--design-surface-1", "color");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-label", "Switch to dark theme");
    await expect(html).toHaveAttribute("data-design-theme", "light");
    await toggle.click();
    await expect(html).toHaveAttribute("data-mantine-color-scheme", "dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    await assertToken(page, "body", "background-color", "--design-surface-1", "switched to dark");
    const dark = await tokenValue(page, "--design-surface-1", "color");
    expect(dark, "the surface token follows the switch to dark").not.toBe(light);
    await gotoOnion(page, page.url());
    await expect(page.locator(EDITOR).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    await assertToken(page, "body", "background-color", "--design-surface-1", "dark after reload");
    expect(await tokenValue(page, "--design-surface-1", "color"), "the stored choice survives a reload").toBe(dark);
    await toggle.click();
    await expect(html).toHaveAttribute("data-mantine-color-scheme", "light");
    await expect.poll(designTheme, { message: "back on the browser preference the mirror is removed" }).toBeNull();
    expect(await tokenValue(page, "--design-surface-1", "color"), "the surface token follows the browser again").toBe(light);
  });

  test("design: the header shows the generated logo and the page carries the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const symbolUrl = decodeDotenvQuotedValue(process.env.DESIGN_SYMBOL_URL);
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

    await open(page, "/query", EDITOR);
    if (title) await expect(page).toHaveTitle(title);
    if (logoUrl) {
      await expect(page.locator(LOGO)).toHaveCSS("content", `url("${logoUrl}")`);
      const box = await page.locator(LOGO).boundingBox();
      expect(box.width, "the lockup in the header is wider than high").toBeGreaterThan(box.height * 1.5);
      for (const icon of await page.locator("link[rel~='icon']").all()) {
        await expect(icon).toHaveAttribute("href", faviconUrl);
      }
      const original = page.viewportSize();
      await page.setViewportSize({ width: SYMBOL_ONLY_WIDTH, height: original.height });
      await expect(page.locator(LOGO)).toHaveCSS("content", `url("${symbolUrl}")`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, "the header does not overflow where upstream shows the symbol alone").toBeLessThanOrEqual(0);
      await page.setViewportSize(original);
      for (const url of [logoUrl, symbolUrl, faviconUrl]) {
        expect((await apiGetOnion(page.request, url)).ok(), `${url} is published on the CDN`).toBe(true);
      }
    }
  });

  test("design: the settings popover and its checked boxes take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/query", EDITOR);
    await page.locator(`${HEADER} button[aria-label='Settings']`).click();
    await expect(page.locator(POPOVER).first()).toBeVisible();
    await animationsSettled(page);
    for (const mode of MODES) {
      await emulate(page, mode);
      await assertToken(page, POPOVER, "background-color", "--design-surface-2", `popover ${mode}`);
      await assertToken(page, CHECKED_BOX, "background-color", "--design-primary", `checked box ${mode}`);
      await assertToken(page, `${CHECKED_BOX} ~ .mantine-Checkbox-icon`, "color", "--design-on-primary", `check mark ${mode}`);
      await assertToken(page, `${POPOVER} .mantine-Input-input`, "border-top-color", "--design-border-strong", `number field ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${POPOVER} .mantine-Checkbox-label`, `${POPOVER} .mantine-Input-input`], "prometheus settings");
  });

  test("design: gallery of query, monitoring status, server status and menus", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));

    await open(page, "/query", EDITOR);
    await captureDesignGallery(page, views());
  });
};
