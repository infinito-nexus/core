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
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const corporateTheme = decodeDotenvQuotedValue(process.env.DESIGN_THEME || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const iconUrl = decodeDotenvQuotedValue(process.env.DESIGN_ICON_URL || "");
const lockupUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOCKUP_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const touchIconUrl = decodeDotenvQuotedValue(process.env.DESIGN_TOUCH_ICON_URL || "");

const MODES = ["light", "dark"];
const PICKED_THEME = "light";
const BLOCK = /\/\*infinito-design\*\/[\s\S]*?\/\*\/infinito-design\*\//g;
const ADD_ON_RULE = ".disclaimerContainer";
const SIGN_IN_NAME = "#loginPage #txtManualName";
const SIGN_IN_SUBMIT = "#loginPage .manualLoginForm .button-submit";
const SIGN_IN_SECONDARY = "#loginPage .btnForgotPassword";
const SIGN_IN_HEADING = "#loginPage .manualLoginForm h1";
const SIGN_IN_LABEL = "#loginPage .manualLoginForm .inputLabel";
const HEADER = ".skinHeader";
const HEADER_LOGO = ".skinHeader .pageTitleWithDefaultLogo";
const HEADER_TAB = ".skinHeader .emby-tab-button";
const HEADER_BUTTON = ".skinHeader .headerSearchButton";
const DRAWER = ".mainDrawer";
const DRAWER_BUTTON = ".skinHeader .mainDrawerButton";
const NAV_ENTRY = ".mainDrawer .navMenuOption";
const NAV_SELECTED = "navMenuOption-selected";
const HOME_MESSAGE = "#indexPage .centerMessage h2";
const HOME_LINK = "#indexPage .centerMessage .button-link";
const THEME_SELECT = "#displayPreferencesPage #selectTheme";
const THEME_SAVE = "#displayPreferencesPage .btnSave";
const ADMIN_BAR = ".MuiAppBar-root";
const ADMIN_BAR_BUTTON = ".MuiAppBar-root .MuiIconButton-root";
const ADMIN_DRAWER = ".MuiDrawer-paper";
const ADMIN_SELECTED = ".MuiDrawer-paper .MuiListItemButton-root.Mui-selected";
const ADMIN_UNSELECTED = ".MuiDrawer-paper [aria-labelledby] .MuiListItemButton-root:not(.Mui-selected)";
const ADMIN_LOGO = ".MuiDrawer-paper .MuiListItemIcon-root > img";
const ADMIN_NAME = ".MuiDrawer-paper .MuiListItemText-primary";
const ADMIN_TEXT = "#dashboardPage .MuiPaper-root .MuiTypography-root";
const ADMIN_PRIMARY = "#dashboardPage .MuiButton-contained.MuiButton-colorPrimary";
const ADMIN_DANGER = "#dashboardPage .MuiButton-contained.MuiButton-colorError";
const ADMIN_PAPER = "#dashboardPage .MuiPaper-root";
const ADMIN_TABLE_CELL = ".mainAnimatedPage .MuiTableCell-body";
const ADMIN_TABLE_HEAD = ".mainAnimatedPage .MuiTableCell-head";
const ADMIN_TABLE_AVATAR = ".mainAnimatedPage .MuiTableCell-body .MuiAvatar-root";
const ADMIN_TABLE_CHIP = ".mainAnimatedPage .MuiTableCell-body .MuiChip-label";
const DIALOG = ".MuiDialog-paper";
const MENU = ".MuiMenu-paper";
const LEGACY_DIALOG = ".dialogContainer .dialog";
const BUSY = ".mdlSpinnerActive, .MuiSkeleton-root, .MuiCircularProgress-indeterminate";

/**
 * Args:
 *   page: Playwright page whose loading indicators must be gone and whose finite animations must have ended.
 */
async function settled(page) {
  await expect(page.locator(BUSY), "every loading indicator must be gone").toHaveCount(0, { timeout: resolveTimeout(30_000) });
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
                      .some((animation) => animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity),
                  ),
                ),
              );
            }),
        ),
      { message: "every finite animation of the page must have ended" },
    )
    .toBe(false);
}

/**
 * Args:
 *   page: Playwright page that shows the element.
 *   selector: element that must be visible before the page counts as settled.
 */
async function shown(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
  await settled(page);
}

/**
 * Args:
 *   page: Playwright page that shows the panel.
 *   panel: dialog, menu or drawer that must have finished opening.
 */
async function opened(page, panel) {
  await expect(page.locator(panel).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(page.locator(panel).first()).toHaveCSS("opacity", "1");
  await settled(page);
}

/**
 * Args:
 *   page: Playwright page that shows the element.
 *   selector: element whose computed style is read.
 *   property: CSS property to read.
 *
 * Returns:
 *   The computed value of the property on the first match.
 */
async function computed(page, selector, property) {
  return page
    .locator(selector)
    .first()
    .evaluate((element, name) => getComputedStyle(element).getPropertyValue(name), property);
}

/**
 * Args:
 *   page: Playwright page that resolves the expression.
 *   expression: CSS color expression, tokens included.
 *
 * Returns:
 *   The computed background color of a probe styled with the expression.
 */
async function colorOf(page, expression) {
  return page.evaluate((value) => {
    const probe = document.createElement("span");
    probe.style.backgroundColor = value;
    document.body.appendChild(probe);
    const color = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return color;
  }, expression);
}

/**
 * Args:
 *   page: Playwright page that can load the image.
 *   url: image URL the content security policy of the page must allow.
 */
async function assertLoads(page, url) {
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

/**
 * Args:
 *   page: Playwright page that shows the web client; a closed navigation drawer gets opened.
 */
async function navigationOpened(page) {
  const drawer = page.locator(DRAWER);
  if (!(await drawer.evaluate((element) => element.classList.contains("drawer-open")))) {
    await page.locator(DRAWER_BUTTON).click();
  }
  await expect(drawer).toHaveClass(/drawer-open/);
  await expect.poll(async () => (await drawer.boundingBox()).x, { message: "the navigation drawer must have slid in" }).toBe(0);
  await settled(page);
}

/**
 * Args:
 *   page: Playwright page that shows the administration; a hidden drawer gets opened.
 */
async function administrationOpened(page) {
  const drawer = page.locator(ADMIN_DRAWER).first();
  if (!(await drawer.isVisible())) await page.locator(`${ADMIN_BAR} .MuiIconButton-edgeStart`).first().click();
  await opened(page, ADMIN_DRAWER);
  await expect.poll(async () => (await drawer.boundingBox()).x, { message: "the administration drawer must have slid in" }).toBe(0);
}

/**
 * Args:
 *   page: Playwright page that shows the display settings.
 *   theme: id of the theme the account stores.
 */
async function pickTheme(page, theme) {
  await page.locator(THEME_SELECT).selectOption(theme);
  await page.locator(THEME_SAVE).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

exports.register = function (shared) {
  const base = shared.env.jellyfinBaseUrl;
  const route = (name, hash) => `${base}/web/?view=${name}#/${hash}`;
  const signIn = (page) => shared.signInViaLocal(page, shared.env.adminUsername, shared.env.adminNativePassword, "design");
  const signInPage = async (page) => {
    await gotoOnion(page, route("sign-in", "login"));
    await shown(page, SIGN_IN_NAME);
  };
  const view = (name, hash, selector, extra) => ({
    name,
    url: route(name, hash),
    prepare: async (page) => {
      await shown(page, selector);
      if (extra) await extra(page);
    },
  });
  const panel = (name, hash, opener, target) => ({
    name,
    url: route(name, hash),
    prepare: async (page) => {
      await shown(page, opener);
      if (!(await page.locator(target).first().isVisible())) await page.locator(opener).first().click();
      await opened(page, target);
    },
  });
  const visitorViews = () => [
    view("sign-in", "login", SIGN_IN_NAME),
    view("sign-in-focus", "login", SIGN_IN_NAME, async (page) => {
      await page.locator(SIGN_IN_NAME).fill(shared.env.adminUsername);
      await page.keyboard.press("Tab");
      await settled(page);
    }),
  ];
  const memberViews = () => [
    view("home", "home", HOME_MESSAGE),
    view("navigation", "home", HOME_MESSAGE, async (page) => {
      await navigationOpened(page);
      await page.locator(NAV_ENTRY).nth(1).hover();
      await settled(page);
    }),
    view("search", "search", "#searchPage input"),
    view("user-menu", "mypreferencesmenu", ".userPreferencesPage .lnkUserProfile"),
    view("settings-display", "mypreferencesdisplay", THEME_SELECT),
    view("settings-home", "mypreferenceshome", "#homeScreenPreferencesPage select:visible"),
    view("settings-playback", "mypreferencesplayback", ".userPreferencesPage form select"),
    view("admin-dashboard", "dashboard", ADMIN_PRIMARY),
    view("admin-navigation", "dashboard", ADMIN_PRIMARY, async (page) => {
      await administrationOpened(page);
      await page.locator(ADMIN_UNSELECTED).first().hover();
      await settled(page);
    }),
    panel("admin-restart-dialog", "dashboard", ADMIN_DANGER, DIALOG),
    panel("admin-user-menu", "dashboard", `${ADMIN_BAR} [aria-haspopup='true']`, MENU),
    view("admin-general", "dashboard/settings", ".mainAnimatedPage .MuiInputBase-input"),
    view("admin-branding", "dashboard/branding", ".mainAnimatedPage .MuiInputBase-input"),
    view("admin-users", "dashboard/users", "#userProfilesPage .card"),
    view("admin-libraries", "dashboard/libraries", "#mediaLibraryPage .MuiButton-contained"),
    panel("admin-library-dialog", "dashboard/libraries", "#mediaLibraryPage .MuiButton-contained", LEGACY_DIALOG),
    view("admin-plugins", "dashboard/plugins", "#pluginsPage .MuiInputBase-input"),
    view("admin-networking", "dashboard/networking", "#networkingPage input"),
    view("admin-activity", "dashboard/activity", ".mainAnimatedPage .MuiTableCell-root"),
    view("admin-logs", "dashboard/logs", ".mainAnimatedPage .MuiListItemButton-root"),
    panel("admin-key-dialog", "dashboard/keys", "#apiKeysPage .MuiButton-root", DIALOG),
  ];

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signInPage(page);
    await assertDesignTokens(page, "jellyfin");
  });

  test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await signInPage(page);
      await expect(page.locator("html")).toHaveAttribute("data-theme", corporateTheme);
      await expect(page.locator("html")).toHaveAttribute("data-design-palette", "");
      await assertToken(page, "html", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, SIGN_IN_HEADING, "color", "--design-text", `sign-in ${mode}`);
      await assertToken(page, SIGN_IN_NAME, "background-color", "--design-surface-2", `field ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "color", "--design-on-primary", `primary action ${mode}`);
      await assertToken(page, SIGN_IN_SECONDARY, "background-color", "--design-surface-3", `secondary action ${mode}`);
      await assertToken(page, SIGN_IN_SECONDARY, "color", "--design-text", `secondary action ${mode}`);
      await page.locator(SIGN_IN_NAME).focus();
      await assertToken(page, SIGN_IN_NAME, "border-top-color", "--design-link", `focused field ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await signInPage(page);
    await assertLightAndDark(page, SIGN_IN_HEADING, "jellyfin sign-in");
    await assertReadable(page, [SIGN_IN_HEADING, SIGN_IN_NAME, SIGN_IN_LABEL, SIGN_IN_SUBMIT, SIGN_IN_SECONDARY], "jellyfin sign-in");
  });

  test("design: header, navigation and their states follow the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    const first = page.locator(NAV_ENTRY).first();
    const second = page.locator(NAV_ENTRY).nth(1);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, route(`home-${mode}`, "home"));
      await shown(page, HOME_MESSAGE);
      await assertToken(page, HEADER, "background-color", "--design-surface-2", `header ${mode}`);
      await assertToken(page, HOME_MESSAGE, "color", "--design-text", `empty library state ${mode}`);
      await assertToken(page, HOME_LINK, "color", "--design-link", `link ${mode}`);
      await assertToken(page, `${HEADER_TAB}.emby-tab-button-active`, "color", "--design-text", `selected tab ${mode}`);
      await assertToken(page, `${HEADER_TAB}:not(.emby-tab-button-active)`, "color", "--design-text-muted", `unselected tab ${mode}`);
      await page.locator(HEADER_BUTTON).hover();
      await assertToken(page, HEADER_BUTTON, "background-color", "--design-surface-hover", `hovered header button ${mode}`);
      await navigationOpened(page);
      await assertToken(page, DRAWER, "background-color", "--design-surface-2", `navigation ${mode}`);
      await assertToken(page, NAV_ENTRY, "color", "--design-text", `navigation entry ${mode}`);
      await second.hover();
      await expect
        .poll(async () => second.evaluate((element) => getComputedStyle(element).backgroundColor), {
          message: `a hovered navigation entry must take --design-surface-hover ${mode}`,
        })
        .toBe(await tokenValue(page, "--design-surface-hover", "background-color"));
      await first.evaluate((element, name) => element.classList.add(name), NAV_SELECTED);
      await assertToken(page, NAV_ENTRY, "background-color", "--design-primary", `selected navigation entry ${mode}`);
      await assertToken(page, NAV_ENTRY, "color", "--design-on-primary", `selected navigation entry ${mode}`);
      await first.evaluate((element, name) => element.classList.remove(name), NAV_SELECTED);
    }
    await page.emulateMedia({ colorScheme: null });
    await gotoOnion(page, route("home", "home"));
    await shown(page, HOME_MESSAGE);
    await navigationOpened(page);
    await assertLightAndDark(page, DRAWER, "jellyfin navigation");
    await assertReadable(page, [HOME_MESSAGE, HOME_LINK, NAV_ENTRY, `${HEADER_TAB}.emby-tab-button-active`, `${HEADER_TAB}:not(.emby-tab-button-active)`], "jellyfin shell");
  });

  test("design: the administration takes its Material palette from the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, route("admin-dashboard", "dashboard"));
      await shown(page, ADMIN_PRIMARY);
      await assertToken(page, "html", "background-color", "--design-surface-1", `administration ${mode}`);
      await assertToken(page, ADMIN_BAR, "color", "--design-text", `app bar ${mode}`);
      await assertToken(page, ADMIN_DRAWER, "background-color", "--design-surface-2", `drawer ${mode}`);
      await assertToken(page, ADMIN_PAPER, "background-color", "--design-surface-2", `card ${mode}`);
      await expect(page.locator(ADMIN_PAPER).first(), `a card must carry no elevation overlay ${mode}`).toHaveCSS("background-image", "none");
      await assertToken(page, ADMIN_TEXT, "color", "--design-text", `text ${mode}`);
      await assertToken(page, ADMIN_PRIMARY, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, ADMIN_PRIMARY, "color", "--design-on-primary", `primary action ${mode}`);
      await assertToken(page, ADMIN_DANGER, "background-color", "--design-danger", `destructive action ${mode}`);
      await assertToken(page, ADMIN_DANGER, "color", "--design-on-danger", `destructive action ${mode}`);
      await assertToken(page, ADMIN_SELECTED, "background-color", "--design-surface-active", `selected entry ${mode}`);
      await page.locator(ADMIN_UNSELECTED).first().hover();
      await assertToken(page, ADMIN_UNSELECTED, "background-color", "--design-surface-hover", `hovered entry ${mode}`);
      await page.locator(ADMIN_BAR_BUTTON).first().hover();
      const tint = await colorOf(page, "rgba(from var(--design-text) r g b / 0.08)");
      await expect
        .poll(() => computed(page, ADMIN_BAR_BUTTON, "background-color"), {
          message: `a hovered app bar button must tint with the channels of --design-text ${mode}`,
        })
        .toBe(tint);
    }
    await page.emulateMedia({ colorScheme: null });
    await gotoOnion(page, route("admin-dashboard", "dashboard"));
    await shown(page, ADMIN_PRIMARY);
    await assertLightAndDark(page, ADMIN_PAPER, "jellyfin administration");
    await assertReadable(page, [ADMIN_TEXT, ADMIN_PRIMARY, ADMIN_DANGER, ADMIN_SELECTED, ADMIN_UNSELECTED, ADMIN_NAME], "jellyfin administration");

    await gotoOnion(page, route("admin-activity", "dashboard/activity"));
    await shown(page, ADMIN_TABLE_CELL);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ADMIN_TABLE_CELL, "background-color", "--design-surface-2", `table cell ${mode}`);
      await assertToken(page, ADMIN_TABLE_HEAD, "background-color", "--design-surface-2", `table head ${mode}`);
      await assertToken(page, ADMIN_TABLE_AVATAR, "background-color", "--design-surface-3", `user symbol ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [ADMIN_TABLE_CELL, ADMIN_TABLE_HEAD, ADMIN_TABLE_AVATAR, ADMIN_TABLE_CHIP], "jellyfin activity table");
  });

  test("design: a theme picked on purpose stays untouched and is mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "dark" });
    await signIn(page);
    await gotoOnion(page, route("settings-display", "mypreferencesdisplay"));
    await shown(page, THEME_SELECT);
    const html = page.locator("html");
    const surface = () => tokenValue(page, "--design-surface-1", "background-color");
    const darkSurface = await surface();
    try {
      await pickTheme(page, PICKED_THEME);
      await expect(html, "a picked theme must not carry the corporate palette").not.toHaveAttribute("data-design-palette");
      await expect(html).toHaveAttribute("data-design-theme", "light");
      const lightSurface = await surface();
      expect(lightSurface, "the tokens must follow the picked light theme while the browser prefers dark").not.toBe(darkSurface);
      await expect(page.locator(`link[href*="themes/${PICKED_THEME}/theme.css"]`), "the picked theme must load its own stylesheet").toHaveCount(1);
      await expect
        .poll(() => computed(page, HEADER, "background-color"), { message: "the picked theme must paint its own header" })
        .not.toBe("rgba(0, 0, 0, 0)");
      expect(await computed(page, HEADER, "background-color"), "the picked theme must keep its own header color").not.toBe(
        await tokenValue(page, "--design-surface-2", "background-color"),
      );
      expect(await computed(page, ".backgroundContainer", "background-color"), "the picked theme must keep its own page color").not.toBe(lightSurface);
    } finally {
      await pickTheme(page, corporateTheme);
    }
    await expect(html).toHaveAttribute("data-design-palette", "");
    await expect(html, "the default theme follows the browser preference").not.toHaveAttribute("data-design-theme");
    await assertToken(page, "html", "background-color", "--design-surface-1", "default theme restored");
    expect(await surface(), "the default theme must show the dark tokens while the browser prefers dark").toBe(darkSurface);
  });

  test("design: title, lockup and icons are the corporate ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!lockupUrl && !title, "logo and title replacement are disabled for this role");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signInPage(page);
    if (title) {
      await expect(page).toHaveTitle(title);
      const info = await (await page.request.get(`${base}/System/Info/Public`)).json();
      expect(info.ServerName, "the server must be named after the corporate title").toBe(title);
    }
    if (lockupUrl) {
      const logo = page.locator(HEADER_LOGO);
      await expect(logo).toHaveCSS("background-image", `url("${lockupUrl}")`);
      const box = await logo.boundingBox();
      expect(box.width, `the header gives the lockup a ${box.width}x${box.height} box that must be at least twice as wide as high`).toBeGreaterThanOrEqual(
        2 * box.height,
      );
      const source = await (await page.request.get(lockupUrl)).text();
      const natural = { width: Number(/width="(\d+)"/.exec(source)[1]), height: Number(/height="(\d+)"/.exec(source)[1]) };
      expect(natural.width / natural.height, "the lockup must be wide enough to carry the title next to the symbol").toBeGreaterThanOrEqual(1.5);
      expect((box.height * natural.width) / natural.height, "the lockup must fit the width of its box at full height").toBeLessThanOrEqual(box.width);
      expect(
        (Number(/font-size="(\d+)"/.exec(source)[1]) * box.height) / natural.height,
        "the title of the lockup must not be painted smaller than 12px",
      ).toBeGreaterThanOrEqual(12);
      await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
      await expect(page.locator("link[rel='apple-touch-icon']")).toHaveAttribute("href", touchIconUrl);
      for (const url of [lockupUrl, iconUrl, faviconUrl, touchIconUrl]) await assertLoads(page, url);
    }
  });

  test("design: the start screen shows the lockup before the client has booted", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!lockupUrl, "logo replacement is disabled for this role");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.route("**/main.jellyfin.bundle.js*", (request) => request.abort());
    await gotoOnion(page, `${base}/web/`);
    await expect(page.locator(".splashLogo")).toHaveCSS("background-image", `url("${lockupUrl}")`);
    await assertToken(page, "html", "background-color", "--design-surface-1", "start screen");
  });

  test("design: the administration drawer shows the corporate symbol next to the title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!iconUrl, "logo replacement is disabled for this role");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    await gotoOnion(page, route("admin-dashboard", "dashboard"));
    await shown(page, ADMIN_LOGO);
    await expect(page.locator(ADMIN_LOGO)).toHaveCSS("content", `url("${iconUrl}")`);
    const box = await page.locator(ADMIN_LOGO).boundingBox();
    expect(Math.abs(box.width - box.height), `the drawer gives the symbol a ${box.width}x${box.height} box that must be square`).toBeLessThanOrEqual(2);
    if (title) await expect(page.locator(ADMIN_NAME).first()).toHaveText(title);
  });

  test("design: the server carries the palette once in its custom CSS", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const branding = await (await page.request.get(`${base}/Branding/Configuration`)).json();
    const css = branding.CustomCss || "";
    const blocks = css.match(BLOCK) || [];
    expect(blocks, "the custom CSS of the server must carry exactly one corporate block").toHaveLength(1);
    const foreign = css.replace(BLOCK, "").trim();
    if (isServiceEnabled("sso")) {
      expect(foreign, "the rules of the single sign-on add-on must survive next to the corporate block").toContain(ADD_ON_RULE);
    } else {
      expect(foreign, "nothing but the corporate block belongs into the custom CSS of this deployment").toBe("");
    }

    await signIn(page);
    await gotoOnion(page, route("admin-dashboard", "dashboard"));
    await shown(page, ADMIN_PRIMARY);
    await expect(
      page.locator('link[rel="stylesheet"][href*="/_shared/css/bootstrap.css"]'),
      "the Bootstrap component mapping must stay off for a role that does not opt in",
    ).toHaveCount(0);
    const declared = await page.evaluate(() => {
      const names = new Set();
      for (const sheet of document.styleSheets) {
        let rules;
        try {
          rules = sheet.cssRules;
        } catch {
          continue;
        }
        for (const rule of rules) {
          if (!rule.style || (rule.selectorText || "").includes("data-design-palette")) continue;
          for (const name of rule.style) if (name.startsWith("--jf-")) names.add(name);
        }
      }
      return [...names];
    });
    const assigned = [...new Set([...blocks[0].matchAll(/(--jf-[\w-]+)\s*:/g)].map((match) => match[1]))];
    expect(assigned.length, "the corporate block must map the Material variables of the administration").toBeGreaterThan(0);
    expect(
      assigned.filter((name) => !declared.includes(name)),
      "Material variables the corporate block assigns although the web client does not declare them",
    ).toEqual([]);
  });

  test("design: gallery of sign-in, home, settings, administration, dialogs and menus", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));

    const failures = [];
    const capture = async (views) => {
      try {
        await captureDesignGallery(page, views);
      } catch (error) {
        failures.push(error.message);
      }
    };
    await capture(visitorViews());
    await signIn(page);
    await capture(memberViews());
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
