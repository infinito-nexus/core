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
const MAIN = "#page_content";
const NAV = "#pma_navigation";
const NAV_LINK = "#pma_navigation_tree li a.hover_show_full";
const FRAME = ".breadcrumb-navbar";
const LOGO = "#pmalogo h1, #imgpmalogo";
const SQL_EDITOR = "#sqlqueryform .CodeMirror";
const RESULTS = ".table_results";
const RESULT_CELL = ".table_results tbody td.data";
const PRIMARY = `${MAIN} .btn-primary >> visible=true`;
const CARD = `${MAIN} .card >> visible=true`;
const BADGE = `${MAIN} .badge`;
const SUCCESS = `${MAIN} .alert-success`;
const THEME_CSS = "link[href*='themes/infinito/css/theme']";
const THEME_SELECT = "#themeSelect";
const THEME_SELECT_ITEM = "#li_select_theme";
const THEME_SET = /route=(?:%2F|\/)themes(?:%2F|\/)set/;
const BASE_THEME = "pmahomme";
const COLOR_PROPERTY =
  /^(?:--[\w-]+|(?:[a-z-]*-)?color|background(?:-image)?|fill|stroke|box-shadow|text-shadow|border(?:-(?:top|right|bottom|left))?|outline|column-rule)$/;
const SHOWCASE = "design_showcase";
const MOBILE_WIDTH = 768;

const base = decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
const db = decodeDotenvQuotedValue(process.env.PHPMYADMIN_DB_NAME);
const ssoUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const ssoPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

function route(path) {
  return `${base}/index.php?route=${path}`;
}

/**
 * Args:
 *   page: Playwright page.
 *   path: phpMyAdmin route with its query, for example "/server/databases".
 *   ready: CSS selector that is visible once the view rendered.
 */
async function open(page, path, ready) {
  await gotoOnion(page, route(path));
  if (page.url().includes("openid-connect/auth")) {
    await expect(page.locator("input#password, input[name='password']").first()).toBeEditable({ timeout: resolveTimeout(60_000) });
    await performKeycloakLoginForm(page, ssoUsername, ssoPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
    await gotoOnion(page, route(path));
  }
  await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   page: Playwright page; creates the showcase table in the role database once.
 */
async function ensureShowcase(page) {
  await open(page, `/database/sql&db=${encodeURIComponent(db)}`, SQL_EDITOR);
  const sql = [
    `CREATE TABLE IF NOT EXISTS ${SHOWCASE} (id INT PRIMARY KEY, name VARCHAR(64) NOT NULL, status ENUM('active','paused','archived') NOT NULL, created DATE NOT NULL);`,
    `INSERT IGNORE INTO ${SHOWCASE} VALUES (1,'Alpha','active','2026-01-05'),(2,'Beta','paused','2026-02-11'),(3,'Gamma','archived','2026-03-17'),(4,'Delta','active','2026-04-23'),(5,'Epsilon','active','2026-05-29');`,
  ].join("\n");
  await page.evaluate(([selector, text]) => document.querySelector(selector).CodeMirror.setValue(text), [SQL_EDITOR, sql]);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().includes("route=/import") && candidate.request().method() === "POST", {
      timeout: resolveTimeout(30_000),
    }),
    page.locator("#button_submit_query").click(),
  ]);
  expect((await response.json()).success, "the showcase seed query succeeds").toBe(true);
}

/**
 * Args:
 *   page: Playwright page on a phpMyAdmin view.
 *   collapse: true collapses the navigation panel, false expands it.
 */
async function setNavigation(page, collapse) {
  const width = async () => {
    const box = await page.locator(NAV).boundingBox();
    return box ? box.width : 0;
  };
  await page.waitForLoadState("load");
  await page.waitForFunction(() => Boolean(window.jQuery && window.jQuery.isReady), null, { timeout: resolveTimeout(10_000) });
  if ((await width()) < 30 === collapse) return;
  await page.locator("#pma_navigation_collapser").click();
  await expect.poll(async () => (collapse ? (await width()) < 30 : (await width()) >= 200), { timeout: resolveTimeout(5_000) }).toBe(true);
}

function shown(ready) {
  return async (page) => {
    await setNavigation(page, page.viewportSize().width < MOBILE_WIDTH);
    await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   page: Playwright page on the phpMyAdmin home view.
 *   theme: theme id to pick in the chooser of the card "Appearance settings".
 */
async function pickTheme(page, theme) {
  const select = page.locator(THEME_SELECT);
  await expect(select).toBeVisible({ timeout: resolveTimeout(10_000) });
  const [posted] = await Promise.all([
    page.waitForResponse((response) => THEME_SET.test(response.url()) && response.request().method() === "POST", {
      timeout: resolveTimeout(30_000),
    }),
    select.selectOption(theme),
  ]);
  expect(posted.status(), `the chooser stores ${theme}`).toBeLessThan(400);
  await page.waitForLoadState("load");
  await expect(page.locator(THEME_SELECT)).toHaveValue(theme, { timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   source: text of a stylesheet.
 *   property: source of a regular expression that matches the color-bearing property names.
 *
 * Returns the declarations whose value carries a hex value, a numeric color function or a color keyword.
 */
function literalColors([source, property]) {
  const colorProperty = new RegExp(property);
  const keyword = (word) =>
    /^[a-z]+$/i.test(word) &&
    !/^(?:transparent|currentcolor|inherit|initial|unset|revert|none)$/i.test(word) &&
    CSS.supports("color", word);
  const found = [];
  for (const [, name, value] of source.matchAll(/(?:^|[{;])\s*(--[\w-]+|[a-z-]+)\s*:\s*([^;{}]+)/gm)) {
    if (!colorProperty.test(name) || value.includes("url(")) continue;
    if (
      /#[0-9a-f]{3,8}\b/i.test(value) ||
      /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(\s*[\d.]/i.test(value) ||
      value.split(/[\s,()]+/).some(keyword)
    ) {
      found.push(`${name}: ${value.trim()}`);
    }
  }
  return found;
}

function views() {
  const d = encodeURIComponent(db);
  const visibleForm = `${MAIN} form >> visible=true`;
  const visibleTable = `${MAIN} table >> visible=true`;
  return [
    { name: "home", url: route("/"), prepare: shown("#maincontainer") },
    { name: "server-databases", url: route("/server/databases"), prepare: shown(visibleTable) },
    { name: "server-sql", url: route("/server/sql"), prepare: shown(SQL_EDITOR) },
    { name: "server-status", url: route("/server/status"), prepare: shown(visibleTable) },
    { name: "server-monitor", url: route("/server/status/monitor"), prepare: shown(`${MAIN} canvas`) },
    { name: "server-variables", url: route("/server/variables"), prepare: shown(visibleTable) },
    { name: "server-collations", url: route("/server/collations"), prepare: shown(CARD) },
    { name: "server-engines", url: route("/server/engines"), prepare: shown(visibleTable) },
    { name: "user-accounts", url: route("/server/privileges"), prepare: shown(visibleTable) },
    { name: "server-export", url: route("/server/export"), prepare: shown(visibleForm) },
    { name: "server-import", url: route("/server/import"), prepare: shown(visibleForm) },
    { name: "settings-features", url: route("/preferences/features"), prepare: shown(`${MAIN} .nav-tabs`) },
    { name: "settings-manage", url: route("/preferences/manage"), prepare: shown(visibleForm) },
    { name: "database-structure", url: route(`/database/structure&db=${d}`), prepare: shown(visibleTable) },
    { name: "database-sql", url: route(`/database/sql&db=${d}`), prepare: shown(SQL_EDITOR) },
    { name: "database-search", url: route(`/database/search&db=${d}`), prepare: shown(visibleForm) },
    { name: "database-operations", url: route(`/database/operations&db=${d}`), prepare: shown(CARD) },
    {
      name: "table-browse",
      url: route(`/sql&db=${d}&table=${SHOWCASE}&pos=0`),
      prepare: async (page) => {
        await shown(RESULT_CELL)(page);
        await page.locator(`${RESULTS} tbody tr`).nth(1).hover();
      },
    },
    { name: "table-structure", url: route(`/table/structure&db=${d}&table=${SHOWCASE}`), prepare: shown(visibleTable) },
    { name: "table-insert", url: route(`/table/change&db=${d}&table=${SHOWCASE}`), prepare: shown(visibleForm) },
    { name: "table-search", url: route(`/table/search&db=${d}&table=${SHOWCASE}`), prepare: shown(visibleForm) },
    { name: "table-operations", url: route(`/table/operations&db=${d}&table=${SHOWCASE}`), prepare: shown(CARD) },
    { name: "table-export", url: route(`/table/export&db=${d}&table=${SHOWCASE}`), prepare: shown(visibleForm) },
    {
      name: "navigation-hover",
      url: route("/"),
      prepare: async (page) => {
        await setNavigation(page, false);
        const entry = page.locator(NAV_LINK, { hasText: db }).first();
        await expect(entry).toBeVisible({ timeout: resolveTimeout(10_000) });
        await entry.hover();
      },
    },
  ];
}

exports.register = function () {
  test("design: the highlighted SQL of a result takes the status tokens in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await ensureShowcase(page);
    await open(page, `/sql&db=${encodeURIComponent(db)}&table=${SHOWCASE}&pos=0`, `${RESULTS}, ${MAIN} .cm-keyword`);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, `${MAIN} .cm-keyword`, "color", "--design-info", `SQL keyword ${mode}`);
      await assertToken(page, `${MAIN} .cm-variable-2`, "color", "--design-link", `SQL identifier ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${MAIN} .cm-keyword`], "phpmyadmin SQL keyword");
  });

  test("design: the role theme is active and loads", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await open(page, "/", "#maincontainer");
    await expect(page.locator(THEME_CSS)).toHaveCount(1);
    const themeUrl = new URL(await page.locator(THEME_CSS).getAttribute("href"), page.url()).toString();
    for (const url of [themeUrl, new URL("design.css", themeUrl).toString(), `${base}/themes/infinito/css/theme.rtl.css`, `${base}/themes/infinito/jquery/jquery-ui.css`]) {
      expect((await apiGetOnion(page.request, url)).ok(), `${url} is served`).toBe(true);
    }
    expect(errors, "the home page raises no page error").toEqual([]);
  });

  test("design: the theme stylesheet sets every color through a token", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/", "#maincontainer");
    const themeUrl = new URL(await page.locator(THEME_CSS).getAttribute("href"), page.url());
    const response = await apiGetOnion(page.request, new URL("design.css", themeUrl).toString());
    expect(response.ok(), "the role theme serves design.css").toBe(true);
    const offenders = await page.evaluate(literalColors, [await response.text(), COLOR_PROPERTY.source]);
    expect(offenders, "every color of the theme stylesheet comes from a --design-* token").toEqual([]);
  });

  test("design: phpMyAdmin's theme chooser starts on the role theme, another theme keeps its own colors, and the role theme returns", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/", "#maincontainer");
    await expect(page.locator(THEME_SELECT)).toHaveValue("infinito");
    await expect(page.locator("html"), "the role theme follows the browser color scheme").not.toHaveAttribute("data-design-theme", /.+/);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, NAV, "background-color", "--design-surface-2", `role theme ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });

    await pickTheme(page, BASE_THEME);
    await expect(page.locator(`link[href*='themes/${BASE_THEME}/css/theme']`)).toHaveCount(1);
    await expect(page.locator(THEME_CSS)).toHaveCount(0);
    await expect(page.locator(NAV), "the picked theme draws its own navigation").toHaveCSS("background-image", /linear-gradient/);
    await assertReadable(page, [`${THEME_SELECT_ITEM} label`], `${BASE_THEME} appearance card`);
    await expect(page.locator("html"), "a light theme of phpMyAdmin keeps the tokens light").toHaveAttribute("data-design-theme", "light");

    await pickTheme(page, "infinito");
    await expect(page.locator(THEME_CSS)).toHaveCount(1);
    await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
    await expect(page.locator(NAV)).toHaveCSS("background-image", "none");
    await assertToken(page, NAV, "background-color", "--design-surface-2", "role theme picked again");
  });

  test("design: the badges of the collation list are readable in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/server/collations", BADGE);
    await assertReadable(page, [BADGE], "phpmyadmin collation badge");
  });

  test("design: a success message takes the success tint and border in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await ensureShowcase(page);
    await open(page, `/sql&db=${encodeURIComponent(db)}&table=${SHOWCASE}&pos=0`, SUCCESS);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, SUCCESS, "background-color", "--design-success-subtle", `success message ${mode}`);
      await assertToken(page, SUCCESS, "border-top-color", "--design-success-border", `success message border ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [SUCCESS], "phpmyadmin success message");
  });

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/", "#maincontainer");
    await assertDesignTokens(page, "phpmyadmin");
  });

  test("design: page, navigation, results, cards and primary action take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await ensureShowcase(page);
    await open(page, `/sql&db=${encodeURIComponent(db)}&table=${SHOWCASE}&pos=0`, RESULT_CELL);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, NAV, "background-color", "--design-surface-2", `navigation ${mode}`);
      await assertToken(page, RESULT_CELL, "color", "--design-text", `result cell ${mode}`);
      await assertToken(page, `${RESULTS} thead th`, "background-color", "--design-surface-3", `result head ${mode}`);
      await assertToken(page, FRAME, "background-color", "--design-frame", `breadcrumb bar ${mode}`);
      await assertToken(page, `${FRAME} a`, "color", "--design-on-frame", `breadcrumb link ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, MAIN, "phpmyadmin content");
    await expect(page.locator(NAV_LINK).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    await assertReadable(page, [RESULT_CELL, NAV_LINK, `${FRAME} a`], "phpmyadmin browse");

    await open(page, "/server/databases", PRIMARY);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, PRIMARY, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, PRIMARY, "color", "--design-on-primary", `primary action text ${mode}`);
      await assertToken(page, CARD, "border-top-color", "--design-border", `card divider ${mode}`);
      await assertToken(page, CARD, "background-color", "--design-surface-2", `card ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${MAIN} .btn-primary`], "phpmyadmin primary action");
  });

  test("design: every focus stop in the breadcrumb bar draws its indicator in the frame text color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "/server/databases", `${FRAME} a`);
    const links = await page.locator(`${FRAME} a`).count();
    expect(links, "the breadcrumb bar carries links").toBeGreaterThan(0);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const expected = await tokenValue(page, "--design-on-frame", "outline-color");
      await page.locator(`${FRAME} a`).first().focus();
      await page.keyboard.press("Shift+Tab");
      for (let stop = 0; stop < links; stop += 1) {
        await page.keyboard.press("Tab");
        const focused = await page.evaluate((frame) => {
          const element = document.activeElement;
          const style = getComputedStyle(element);
          return { inFrame: Boolean(element.closest(frame)), style: style.outlineStyle, color: style.outlineColor };
        }, FRAME);
        expect(focused.inFrame, `focus stop ${stop} sits in the breadcrumb bar (${mode})`).toBe(true);
        expect(focused.style, `focus stop ${stop} draws an outline (${mode})`).not.toBe("none");
        expect(focused.color, `focus stop ${stop} outline color (${mode})`).toBe(expected);
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: logo, favicon and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await open(page, "/", "#maincontainer");
    if (title) await expect(page).toHaveTitle(new RegExp(`\\| ${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
    if (logoUrl) {
      const logo = page.locator(LOGO).first();
      await expect(logo).toHaveCSS("content", `url("${logoUrl}")`);
      const box = await logo.boundingBox();
      expect(box.width, "the navigation lockup is wider than high").toBeGreaterThan(box.height * 1.5);
      for (const icon of await page.locator("link[rel~='icon']").all()) {
        await expect(icon).toHaveAttribute("href", faviconUrl);
      }
      for (const url of [logoUrl, faviconUrl]) {
        expect((await apiGetOnion(page.request, url)).ok(), `${url} is published on the CDN`).toBe(true);
      }
    }
  });

  test("design: gallery of server, database, table and settings pages", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    await ensureShowcase(page);
    await captureDesignGallery(page, views());
  });
};
