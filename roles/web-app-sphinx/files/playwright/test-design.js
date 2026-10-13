const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
} = require("./design");
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const iconUrl = decodeDotenvQuotedValue(process.env.DESIGN_ICON_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");

const MODES = ["light", "dark"];
const MAIN = "main";
const HEADER = "header.sticky";
const SIDEBAR = "#left-sidebar";
const SIDEBAR_LINK = `${SIDEBAR} a.reference`;
const SWITCH = "button[title='Toggle color scheme']";
const MENU = "header button.md\\:hidden";
const SEARCH = "#search-input";
const BREADCRUMBS = "nav[aria-label='breadcrumbs']";
const CONTENT_LINK = "#content a.reference.external";
const CODE = `${MAIN} div.highlight pre`;
const INLINE_CODE = `${MAIN} code:not(pre code)`;
const COPY = `${MAIN} div.highlight button.copy`;
const ICON = "header a img[alt='Logo']:not(.hidden)";
const SIDEBAR_LOGO = ".sidebar-logo img";
const README = "/README.html";
const ROLE_README = "/roles/web-app-listmonk/README.html";
const CURRENT_PAGE = "/CODE_OF_CONDUCT.html#our-pledge";
const GUIDE = "/docs/Docker.html";
const NOT_FOUND = "/design-gallery-missing.html";
const STORE_KEY = "_x_darkMode";
const READY = 10_000;

test.use({ ignoreHTTPSErrors: true });

/**
 * Args:
 *   page: Playwright page whose next documents drop the stored theme choice, so each one follows the emulated color scheme.
 */
async function followScheme(page) {
  await page.addInitScript((key) => {
    if (location.protocol.startsWith("http")) localStorage.removeItem(key);
  }, STORE_KEY);
}

/**
 * Args:
 *   page: Playwright page whose finite animations must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          document
            .getAnimations()
            .some((a) => a.playState === "running" && a.effect?.getComputedTiming().iterations !== Infinity),
        ),
      { message: "every finite animation of the page must have ended", timeout: resolveTimeout(READY) },
    )
    .toBe(false);
}

/**
 * Args:
 *   page: Playwright page that must show the selector without a running animation.
 *   selector: ready selector of the state to capture.
 */
async function shown(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY) });
  await animationsSettled(page);
}

/**
 * Args:
 *   page: Playwright page whose dark class and design theme must equal the emulated color scheme.
 */
async function expectSchemeFollowed(page) {
  const prefersDark = await page.evaluate(() => matchMedia("(prefers-color-scheme: dark)").matches);
  const mode = prefersDark ? "dark" : "light";
  await expect(page.locator("html"), "html.dark must follow the emulated color scheme").toHaveClass(
    prefersDark ? /(^|\s)dark(\s|$)/ : /^(?!.*(^|\s)dark(\s|$))/,
  );
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", mode);
}

/**
 * Args:
 *   page: Playwright page that opens the site path and waits for its content.
 *   path: site path to open.
 */
async function open(page, path) {
  await gotoOnion(page, `${base}${path}`);
  await shown(page, MAIN);
}

/**
 * Args:
 *   page: Playwright page whose sidebar is opened as a drawer when the viewport hides it.
 */
async function openSidebar(page) {
  const menu = page.locator(MENU).first();
  if (await menu.isVisible()) {
    await menu.click({ timeout: resolveTimeout(READY) });
    await shown(page, `${SIDEBAR}.translate-x-0`);
  }
}

/**
 * Args:
 *   page: Playwright page whose body background is returned.
 */
function bodyBackground(page) {
  return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
}

function views() {
  const view = (name, path, selector = MAIN) => ({
    name,
    url: `${base}${path}`,
    prepare: async (page) => {
      await shown(page, selector);
      await expectSchemeFollowed(page);
    },
  });
  const state = (name, path, act) => ({
    name,
    url: `${base}${path}`,
    prepare: async (page) => {
      await shown(page, MAIN);
      await expectSchemeFollowed(page);
      await act(page);
      await animationsSettled(page);
    },
  });
  return [
    view("home", "/"),
    state("home-switch", "/", async (page) => {
      const dark = await page.evaluate(() => document.documentElement.classList.contains("dark"));
      await page.locator(SWITCH).click({ timeout: resolveTimeout(READY) });
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", dark ? "light" : "dark");
    }),
    view("readme", README, CODE),
    view("changelog", "/CHANGELOG.html"),
    view("guide", GUIDE, CODE),
    view("architecture", "/docs/ARCHITECTURE.html"),
    view("roles-index", "/roles/index.html"),
    view("glossary", "/roles/ansible_role_glosar.html"),
    view("role-readme", ROLE_README, BREADCRUMBS),
    view("role-vars", "/roles/web-app-listmonk/vars/main.html"),
    view("group-vars", "/group_vars/all/15_design.html"),
    view("yaml-index", "/generated/yaml_index.html"),
    view("api-package", "/generated/modules/cli.html"),
    view("api-module", "/generated/modules/cli.create.role.html"),
    view("module-index", "/py-modindex.html"),
    view("genindex", "/genindex.html"),
    view("search", "/search.html", SEARCH),
    view("search-results", "/search.html?q=listmonk", "#search-results li"),
    state("search-focus", "/", (page) => page.locator(SEARCH).focus()),
    state("code-copy-hover", GUIDE, async (page) => {
      await page.locator(`${MAIN} div.highlight`).first().hover();
      await page.locator(COPY).first().hover();
    }),
    state("sidebar-current", CURRENT_PAGE.split("#")[0], async (page) => {
      await page.evaluate((hash) => {
        location.hash = hash;
      }, `#${CURRENT_PAGE.split("#")[1]}`);
      await openSidebar(page);
      await shown(page, `${SIDEBAR} a.current`);
    }),
    state("sidebar-expanded", "/", async (page) => {
      await openSidebar(page);
      const item = page.locator(`${SIDEBAR} .full-index li[x-data*='expanded: false']`).first();
      await item.locator(".toggle-button").first().dispatchEvent("click");
      await expect(item.locator("ul").first()).toBeVisible({ timeout: resolveTimeout(READY) });
    }),
    state("nav-focus", "/", async (page) => {
      await openSidebar(page);
      await page.locator(SIDEBAR_LINK).first().focus();
      await page.keyboard.press("Tab");
    }),
    state("mobile-drawer", "/", openSidebar),
    state("header-scrolled", GUIDE, (page) => page.evaluate(() => window.scrollTo(0, 600))),
    { name: "not-found", url: `${base}${NOT_FOUND}`, prepare: (page) => shown(page, "body") },
  ];
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await open(page, "/");
  await assertDesignTokens(page, "sphinx");
});

test("design: a page without the theme switch follows the browser scheme", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}${NOT_FOUND}`);
  await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(READY) });
  await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
  await assertLightAndDark(page, "body", "server error page");
});

test("design: pages take surface, text, link and dividers from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await followScheme(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await open(page, GUIDE);
    await expectSchemeFollowed(page);
    await assertToken(page, INLINE_CODE, "background-color", "--design-surface-3", `inline code ${mode}`);
    await assertToken(page, INLINE_CODE, "color", "--design-text", `inline code text ${mode}`);
    await open(page, README);
    await expectSchemeFollowed(page);
    await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `text ${mode}`);
    await assertToken(page, HEADER, "border-bottom-color", "--design-border", `header divider ${mode}`);
    await assertToken(page, `${MAIN} pre`, "border-top-color", "--design-border", `code block divider ${mode}`);
    await assertToken(page, CONTENT_LINK, "color", "--design-link", `content link ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, MAIN, "sphinx page");
  await assertReadable(
    page,
    [`${MAIN} h1`, `${MAIN} p`, CONTENT_LINK, CODE, { selector: SIDEBAR_LINK, optional: true }, "footer p"],
    "sphinx page",
  );
});

test("design: the native switch drives the palette and the design theme attribute", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await followScheme(page);
  await page.emulateMedia({ colorScheme: "light" });
  await open(page, "/");
  await expectSchemeFollowed(page);
  const light = await bodyBackground(page);
  await expect(page.locator(SWITCH)).toBeVisible({ timeout: resolveTimeout(READY) });
  await page.locator(SWITCH).click();
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
  await assertToken(page, "body", "background-color", "--design-surface-1", "page after the switch");
  expect(await bodyBackground(page), "the switch must change the page surface").not.toBe(light);
  await page.locator(SWITCH).click();
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
  expect(await bodyBackground(page)).toBe(light);
});

test("design: a stored dark choice wins over a light browser and reaches the design theme on load", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.emulateMedia({ colorScheme: "light" });
  await open(page, "/");
  await page.locator(SWITCH).click();
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
  await open(page, ROLE_README);
  await expect(page.locator("html")).toHaveClass(/(^|\s)dark(\s|$)/);
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
  await assertToken(page, "body", "background-color", "--design-surface-1", "stored dark choice");
});

test("design: the selected sidebar entry and the search field keep readable palette states", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await followScheme(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await open(page, CURRENT_PAGE);
    await expectSchemeFollowed(page);
    await shown(page, `${SIDEBAR} a.current`);
    await assertToken(page, `${SIDEBAR} a.current`, "background-color", "--design-surface-active", `current entry ${mode}`);
    await assertToken(page, `${SIDEBAR} a.current`, "color", "--design-text", `current entry text ${mode}`);
    await assertToken(page, SEARCH, "border-top-color", "--design-border-strong", `search field ${mode}`);
    await page.locator(SEARCH).focus();
    await assertToken(page, SEARCH, "background-color", "--design-surface-hover", `focused search field ${mode}`);
    await page.locator(SIDEBAR_LINK).first().focus();
    await page.keyboard.press("Tab");
    await assertToken(page, `${SIDEBAR} :focus-visible`, "outline-color", "--design-link", `focused sidebar entry ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [`${SIDEBAR} a.current`, SEARCH], "sidebar and search states");
});

test("design: the role stylesheet keeps the breadcrumb navigation visible", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await open(page, ROLE_README);
  await expect(page.locator(BREADCRUMBS)).toBeVisible({ timeout: resolveTimeout(READY) });
  await expect(page.locator(SWITCH)).toBeVisible({ timeout: resolveTimeout(READY) });
});

test("design: logo, icon and favicon come from the design lookup", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl, "logo replacement is disabled for this role");
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/");
  await expect(page.locator(SIDEBAR_LOGO)).toHaveCSS("content", `url("${logoUrl}")`);
  const logo = await page.locator(SIDEBAR_LOGO).boundingBox();
  expect(logo.width, "the sidebar logo is a wide lockup").toBeGreaterThan(logo.height * 2);
  await expect(page.locator(ICON)).toHaveCSS("content", `url("${iconUrl}")`);
  const icon = await page.locator(ICON).boundingBox();
  expect(Math.abs(icon.width - icon.height), "the header icon stays square").toBeLessThan(2);
  await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
  for (const url of [logoUrl, iconUrl, faviconUrl]) {
    expect(
      await page.evaluate(
        (src) =>
          new Promise((resolve) => {
            const image = new Image();
            image.onload = () => resolve(image.naturalWidth > 0);
            image.onerror = () => resolve(false);
            image.src = src;
          }),
        url,
      ),
      `the page must be allowed to load ${url}`,
    ).toBe(true);
  }
});

test("design: gallery of index, guides, role pages, generated pages, search, sidebar and switch states", async ({
  page,
}) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(1_800_000));
  await followScheme(page);
  await captureDesignGallery(page, views());
});
