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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");

const MODES = ["light", "dark"];
const NARROW = { width: 390, height: 844 };
const HTML = "html";
const TOP_BAR = "nav.navbar:not(.footer-bar)";
const FOOTER_BAR = "nav.footer-bar";
const BRAND = `${TOP_BAR} .navbar-brand`;
const BURGER = `${TOP_BAR} .navbar-toggler`;
const APPS = `${TOP_BAR} .nav-item.dropdown > .nav-link`;
const APPS_MENU = `${TOP_BAR} .nav-item.dropdown > .dropdown-menu.show`;
const GROUP = `${APPS_MENU} > .dropdown-submenu > .dropdown-item`;
const OPEN_GROUP = `${APPS_MENU} > .dropdown-submenu > .dropdown-item:has(+ .dropdown-menu.show)`;
const SUBMENU = `${APPS_MENU} > .dropdown-submenu > .dropdown-menu.show`;
const CARD = "main .app-card";
const CARD_TITLE = `${CARD} h2`;
const CARD_TEXT = `${CARD} p.small`;
const CARD_ICON = `${CARD} .app-icon`;
const CARD_BADGE = `${CARD} .app-badge`;
const START = `${CARD} .btn-primary`;
const FOOTER_LINK = `${FOOTER_BAR} .btn-link`;
const BROWSER_BAR = "#topBar";
const BROWSER_SYMBOL = "#topBar .brand img";
const THEME_BUTTON = "#buttonTheme";
const LIST_BUTTON = "#buttonExamples";
const LIST_ROW = "#listExamples .item";
const SELECTED_ROW = "#listExamples .item.selected";
const SEARCH = "#inputSearch";
const CODE = "#textareaCode";
const PREVIEW = "#iframeContainer iframe";

function hex(color) {
  const channels = color.match(/\d+/g).slice(0, 3);
  return `#${channels.map((value) => Number(value).toString(16).padStart(2, "0")).join("")}`;
}

/**
 * Args:
 *   page: Playwright page; the stored choices of the example browser are removed before every document.
 */
async function forgetBrowserChoices(page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.removeItem("theme");
      window.localStorage.removeItem("LittleJSExamples");
    } catch (error) {
      void error;
    }
  });
}

async function launcherReady(page) {
  await expect(page.locator(CARD).first()).toBeVisible({ timeout: resolveTimeout(20_000) });
  await expect(page.locator(BRAND)).toBeVisible({ timeout: resolveTimeout(20_000) });
  await page.waitForFunction(() => document.fonts.status === "loaded", null, { timeout: resolveTimeout(20_000) });
}

async function browserReady(page) {
  await expect(page.locator("#buttonPrev")).toBeVisible({ timeout: resolveTimeout(20_000) });
  await expect(page.frameLocator(PREVIEW).locator("canvas").first()).toBeAttached({
    timeout: resolveTimeout(20_000),
  });
  await expect(page.locator("#buttonRestart")).toBeEnabled({ timeout: resolveTimeout(20_000) });
}

async function stageReady(page) {
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: resolveTimeout(20_000) });
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        let frames = 0;
        const step = () => (++frames > 45 ? resolve() : requestAnimationFrame(step));
        step();
      }),
  );
}

async function scrollToEnd(page) {
  await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" }));
}

async function openApps(page) {
  await launcherReady(page);
  if (await page.locator(BURGER).isVisible()) {
    await page.locator(BURGER).click();
    await expect(page.locator(`${TOP_BAR} .navbar-collapse.show`)).toBeVisible({ timeout: resolveTimeout(10_000) });
  }
  await page.locator(APPS).click();
  await expect(page.locator(APPS_MENU)).toBeVisible({ timeout: resolveTimeout(10_000) });
}

async function openSubmenu(page) {
  await openApps(page);
  await page.locator(GROUP, { hasText: "GAMES" }).click();
  await expect(page.locator(SUBMENU)).toBeVisible({ timeout: resolveTimeout(10_000) });
}

async function openList(page) {
  await browserReady(page);
  if (await page.locator(LIST_BUTTON).isVisible()) {
    await page.locator(LIST_BUTTON).click();
    await expect(page.locator("#listPanel.open")).toBeVisible({ timeout: resolveTimeout(10_000) });
  }
}

async function runCode(page, code) {
  await browserReady(page);
  const editor = page.locator(".CodeMirror");
  if ((await editor.count()) > 0) {
    await editor.click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type(code);
  } else {
    await page.locator(CODE).fill(code);
  }
}

async function focusByKeyboard(page, locator) {
  await page.keyboard.press("Tab");
  await locator.focus();
}

async function focusIndicatorUses(locator, color) {
  return locator.evaluate((element, expected) => {
    const style = getComputedStyle(element);
    const outlined =
      style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0 && style.outlineColor === expected;
    return outlined || style.boxShadow.includes(expected);
  }, color);
}

async function assertFrameFocus(page, selector, least) {
  const onFrame = await tokenValue(page, "--design-on-frame", "color");
  const stops = page.locator(selector);
  let checked = 0;
  for (let index = 0; index < (await stops.count()); index += 1) {
    const stop = stops.nth(index);
    if (!(await stop.isVisible()) || (await stop.evaluate((element) => element.closest(".dropdown-menu") !== null))) {
      continue;
    }
    await focusByKeyboard(page, stop);
    expect(
      await focusIndicatorUses(stop, onFrame),
      `focus stop ${index} of '${selector}' must draw its indicator in --design-on-frame`,
    ).toBe(true);
    checked += 1;
  }
  expect(checked, `'${selector}' must hold focus stops`).toBeGreaterThanOrEqual(least);
}

exports.register = function () {
  const launcher = `${base}/`;
  const browser = (query = "") => `${base}/examples/${query}`;
  const short = (file) => `${base}/examples/shorts/run.html?file=${file}`;

  async function openLauncher(page) {
    await gotoOnion(page, launcher);
    await launcherReady(page);
  }

  async function openBrowser(page, query = "") {
    await gotoOnion(page, browser(query));
    await browserReady(page);
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLauncher(page);
    await assertDesignTokens(page, "littlejs");
  });

  test("design: the launcher takes surfaces, text, dividers and the primary action from the palette", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await openLauncher(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `page ${mode}`);
      await assertToken(page, CARD, "background-color", "--design-surface-2", `card ${mode}`);
      await expect(page.locator(CARD).first(), `card ${mode}: no gradient`).toHaveCSS("background-image", "none");
      await assertToken(page, CARD, "border-top-color", "--design-border", `card border ${mode}`);
      await assertToken(page, CARD_TITLE, "color", "--design-text", `card title ${mode}`);
      await assertToken(page, CARD_TEXT, "color", "--design-text-muted", `card text ${mode}`);
      await assertToken(page, CARD_ICON, "color", "--design-link", `card icon ${mode}`);
      await assertToken(page, CARD_BADGE, "background-color", "--design-surface-3", `badge ${mode}`);
      await assertToken(page, CARD_BADGE, "color", "--design-text-muted", `badge ${mode}`);
      await assertToken(page, START, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, START, "color", "--design-on-primary", `primary action ${mode}`);
      await page.locator(START).first().hover();
      await assertToken(page, START, "background-color", "--design-primary-hover", `hovered primary action ${mode}`);
      await assertToken(page, START, "color", "--design-on-primary", `hovered primary action ${mode}`);
      await page.mouse.move(2, 200);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, CARD, "littlejs launcher");
    await assertReadable(
      page,
      ["main h1", "main header p", CARD_TITLE, CARD_TEXT, CARD_ICON, CARD_BADGE, START],
      "littlejs launcher",
    );
    await page.locator(CARD).first().hover();
    await assertToken(page, CARD, "border-top-color", "--design-primary", "hovered card");
    await assertReadable(page, [CARD_TITLE, CARD_TEXT], "littlejs hovered card");
  });

  test("design: every icon of the launcher exists in the icon font", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLauncher(page);
    const empty = await page.evaluate(() =>
      Array.from(document.querySelectorAll("i[class*='fa-']"))
        .filter((icon) => ["none", "normal", '""'].includes(getComputedStyle(icon, "::before").content))
        .map((icon) => icon.className),
    );
    expect(empty, "icons without a glyph render as an empty box").toEqual([]);
  });

  test("design: both bars are the frame and every focus stop in them is drawn in the frame text tone", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await openLauncher(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, TOP_BAR, "background-color", "--design-frame", `top bar ${mode}`);
      await assertToken(page, APPS, "color", "--design-on-frame", `top bar entry ${mode}`);
      await assertToken(page, FOOTER_BAR, "background-color", "--design-frame", `footer bar ${mode}`);
      await assertToken(page, FOOTER_LINK, "color", "--design-on-frame", `footer link ${mode}`);
      await page.locator(FOOTER_LINK).first().hover();
      await assertToken(page, FOOTER_LINK, "background-color", "--design-frame-hover", `hovered footer link ${mode}`);
      await assertToken(page, FOOTER_LINK, "color", "--design-on-frame", `hovered footer link ${mode}`);
      await page.mouse.move(2, 200);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [APPS, FOOTER_LINK], "littlejs frame", 7);
    await assertFrameFocus(page, `${TOP_BAR} a, ${TOP_BAR} button, ${FOOTER_BAR} a`, 6);

    await page.setViewportSize(NARROW);
    await expect(page.locator(BURGER)).toBeVisible();
    await assertToken(page, BURGER, "color", "--design-on-frame", "burger");
    await assertFrameFocus(page, BURGER, 1);
    await scrollToEnd(page);
    const overlap = await page.evaluate(() => {
      const cards = document.querySelectorAll("main .app-card");
      const last = cards[cards.length - 1].getBoundingClientRect();
      return last.bottom - document.querySelector("nav.footer-bar").getBoundingClientRect().top;
    });
    expect(overlap, "the footer bar must not cover the last tile on a narrow screen").toBeLessThanOrEqual(0);
  });

  test("design: the open menu is a panel and marks its open group", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, launcher);
    await openSubmenu(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, APPS, "background-color", "--design-frame-active", `open entry ${mode}`);
      await assertToken(page, APPS_MENU, "background-color", "--design-surface-2", `menu ${mode}`);
      await assertToken(page, GROUP, "color", "--design-text", `menu entry ${mode}`);
      await assertToken(page, `${APPS_MENU} .dropdown-divider`, "border-top-color", "--design-border", `menu divider ${mode}`);
      await assertToken(page, SUBMENU, "background-color", "--design-surface-2", `submenu ${mode}`);
      await assertToken(page, OPEN_GROUP, "background-color", "--design-surface-active", `open group ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [GROUP, OPEN_GROUP, `${SUBMENU} .dropdown-item`], "littlejs menu");
    const entry = page.locator(`${SUBMENU} .dropdown-item`).first();
    await focusByKeyboard(page, entry);
    expect(
      await focusIndicatorUses(entry, await tokenValue(page, "--design-link", "color")),
      "a focus stop inside the menu must draw its indicator in --design-link",
    ).toBe(true);
  });

  test("design: the launcher shows the generated lockup, icon and title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await openLauncher(page);
    if (title) {
      expect(await page.title(), "the launcher title must carry the configured title").toContain(title);
    }
    if (logoUrl) {
      const lockup = page.locator(`${BRAND} img`);
      await expect(lockup).toHaveAttribute("src", logoUrl);
      await expect
        .poll(() => lockup.evaluate((image) => image.complete && image.naturalWidth > 0), {
          message: "the lockup must load",
        })
        .toBe(true);
      const box = await lockup.boundingBox();
      expect(box.width, "the lockup box must be wider than high").toBeGreaterThan(box.height * 1.5);
      await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
      const onFrame = hex(await tokenValue(page, "--design-on-frame", "color"));
      const served = await apiGetOnion(page.request, logoUrl);
      expect(served.status(), "the lockup must be served").toBe(200);
      const svg = (await served.text()).toLowerCase();
      expect(svg, "the lockup carries the title as text").toContain("<text");
      expect(svg, "the lockup text on the frame").toContain(`fill="${onFrame}"`);
      await gotoOnion(page, short("shapes.js"));
      await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    }
  });

  test("design: the example browser takes panels, dividers and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await forgetBrowserChoices(page);
    await openBrowser(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator(HTML)).toHaveAttribute("data-theme", mode);
      await assertToken(page, "body", "background-color", "--design-surface-1", `browser page ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `browser page ${mode}`);
      await assertToken(page, BROWSER_BAR, "background-color", "--design-surface-2", `browser bar ${mode}`);
      await assertToken(page, BROWSER_BAR, "border-bottom-color", "--design-border", `browser divider ${mode}`);
      await assertToken(page, "#divEditor", "border-top-color", "--design-border", `editor border ${mode}`);
      await assertToken(page, "#buttonPrev", "background-color", "--design-surface-2", `browser button ${mode}`);
      await assertToken(page, "#buttonPrev", "border-top-color", "--design-border-strong", `browser button ${mode}`);
      await assertToken(page, "#exampleInfoBox", "color", "--design-text", `info box ${mode}`);
      await assertToken(page, "#exampleLink", "color", "--design-text-muted", `bar link ${mode}`);
      await assertToken(page, CODE, "background-color", "--design-surface-2", `code ${mode}`);
      await assertToken(page, CODE, "color", "--design-text", `code ${mode}`);
      await page.locator("#buttonPrev").hover();
      await assertToken(page, "#buttonPrev", "background-color", "--design-surface-hover", `hovered button ${mode}`);
      await page.mouse.move(2, 200);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, BROWSER_BAR, "littlejs example browser");
    await assertReadable(
      page,
      [
        "#topBar .brand",
        "#topBar .brand span",
        "#exampleLink",
        THEME_BUTTON,
        "#buttonPrev",
        "#divCodeOptions label",
        "#exampleInfoBox",
        "#exampleInfoBox code",
        CODE,
      ],
      "littlejs example browser",
    );
    if (faviconUrl) {
      await expect(page.locator(BROWSER_SYMBOL)).toHaveAttribute("src", faviconUrl);
      await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    }
    if (title) {
      expect(await page.title()).toContain(title);
    }
  });

  test("design: list, search and the boxes under the code follow the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await forgetBrowserChoices(page);
    await openBrowser(page);
    await openList(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#listPanel", "background-color", "--design-surface-2", `list ${mode}`);
      await assertToken(page, "#listExamples h4", "border-bottom-color", "--design-border", `list divider ${mode}`);
      await assertToken(page, SELECTED_ROW, "background-color", "--design-surface-active", `selected row ${mode}`);
      await assertToken(page, SELECTED_ROW, "border-left-color", "--design-primary", `selected row ${mode}`);
      await assertToken(page, SEARCH, "background-color", "--design-surface-1", `search ${mode}`);
      await assertToken(page, SEARCH, "border-top-color", "--design-border-strong", `search ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(
      page,
      [SELECTED_ROW, `${LIST_ROW}:not(.selected)`, `${LIST_ROW} span`, "#listExamples h4", SEARCH],
      "littlejs example list",
    );

    await openBrowser(page);
    await runCode(page, "throw new Error('Design sample error');");
    await expect(page.locator("#textareaError")).toBeVisible({ timeout: resolveTimeout(15_000) });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#textareaError", "background-color", "--design-surface-3", `error box ${mode}`);
      await assertToken(page, "#textareaError", "color", "--design-danger", `error box ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["#textareaError"], "littlejs error box");

    await openBrowser(page);
    await runCode(page, "console.log('Design sample output');");
    await expect(page.locator("#textareaConsole")).toBeVisible({ timeout: resolveTimeout(15_000) });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#textareaConsole", "background-color", "--design-surface-3", `console box ${mode}`);
      await assertToken(page, "#textareaConsole", "color", "--design-warning", `console box ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["#textareaConsole"], "littlejs console box");
  });

  test("design: the example browser fills the window", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await forgetBrowserChoices(page);
    await openBrowser(page);
    const gap = await page.evaluate(
      () => window.innerHeight - document.getElementById("container1").getBoundingClientRect().bottom,
    );
    expect(gap, "no band may open under the columns of the example browser").toBeLessThan(2);
  });

  test("design: the theme switch of the example browser is respected and mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await gotoOnion(page, browser());
    await page.evaluate(() => {
      window.localStorage.removeItem("theme");
    });
    await openBrowser(page);
    const html = page.locator(HTML);
    const surface = () => tokenValue(page, "--design-surface-1", "background-color");
    const lightSurface = await surface();
    await expect(html).toHaveAttribute("data-theme", "light");
    await expect(html, "the palette follows the browser until a theme is picked").not.toHaveAttribute(
      "data-design-theme",
      /.+/,
    );

    await page.locator(THEME_BUTTON).click();
    await expect(html).toHaveAttribute("data-theme", "dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    await expect.poll(surface, { message: "a picked dark theme in a light browser must switch the tokens" }).not.toBe(
      lightSurface,
    );
    await assertToken(page, "body", "background-color", "--design-surface-1", "picked dark theme");
    await assertToken(page, BROWSER_BAR, "background-color", "--design-surface-2", "picked dark theme");

    await openBrowser(page);
    await expect(html, "the picked theme survives a new document").toHaveAttribute("data-design-theme", "dark");
    await expect(html).toHaveAttribute("data-theme", "dark");

    await page.locator(THEME_BUTTON).click();
    await expect(html).toHaveAttribute("data-design-theme", "light");
    await expect.poll(surface).toBe(lightSurface);

    await openLauncher(page);
    await expect(html, "a theme picked in the example browser must not reach the launcher").not.toHaveAttribute(
      "data-design-theme",
      /.+/,
    );
    await page.evaluate(() => {
      window.localStorage.removeItem("theme");
    });
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: a canvas page keeps the stage the engine paints", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, short("shapes.js"));
    await stageReady(page);
    const stage = await page.evaluate(() => {
      const canvas = document.querySelector("canvas").getBoundingClientRect();
      return {
        background: getComputedStyle(document.body).backgroundColor,
        scrollable: document.documentElement.scrollHeight > window.innerHeight,
        centered: Math.abs(canvas.top + canvas.height / 2 - window.innerHeight / 2) < 2,
      };
    });
    expect(stage, "the injected styles must leave the stage alone").toEqual({
      background: "rgb(0, 0, 0)",
      scrollable: false,
      centered: true,
    });
  });

  function galleryViews() {
    const launcherView = (name, prepare) => ({ name, url: launcher, prepare });
    const browserView = (name, prepare, query = "") => ({ name, url: browser(query), prepare });
    return [
      launcherView("launcher", launcherReady),
      launcherView("launcher-cards", async (page) => {
        await launcherReady(page);
        await page
          .locator(CARD, { hasText: "Pong Game" })
          .first()
          .evaluate((card) => card.scrollIntoView({ behavior: "instant", block: "center" }));
      }),
      launcherView("launcher-card-hover", async (page) => {
        await launcherReady(page);
        await page.locator(CARD).first().hover();
      }),
      launcherView("launcher-button-hover", async (page) => {
        await launcherReady(page);
        await page.locator(START).first().hover();
      }),
      launcherView("launcher-button-focus", async (page) => {
        await launcherReady(page);
        await focusByKeyboard(page, page.locator(START).first());
      }),
      launcherView("launcher-nav-apps", openApps),
      launcherView("launcher-nav-submenu", openSubmenu),
      launcherView("launcher-nav-item-hover", async (page) => {
        await openSubmenu(page);
        await page.locator(`${SUBMENU} .dropdown-item`).nth(1).hover();
      }),
      launcherView("launcher-nav-focus", async (page) => {
        await launcherReady(page);
        await focusByKeyboard(page, page.locator(BRAND));
      }),
      launcherView("launcher-footer", async (page) => {
        await launcherReady(page);
        await scrollToEnd(page);
      }),
      launcherView("launcher-footer-hover", async (page) => {
        await launcherReady(page);
        await page.locator(FOOTER_LINK).first().hover();
      }),
      launcherView("launcher-footer-focus", async (page) => {
        await launcherReady(page);
        await focusByKeyboard(page, page.locator(FOOTER_LINK).first());
      }),
      browserView("browser", browserReady),
      browserView("browser-shapes", browserReady, "?example=Shapes"),
      browserView("browser-game", browserReady, "?example=Platformer%20Game"),
      browserView("browser-search", async (page) => {
        await openList(page);
        await page.locator(SEARCH).fill("game");
        await expect(page.locator(LIST_ROW).first()).toBeVisible();
      }),
      browserView("browser-search-empty", async (page) => {
        await openList(page);
        await page.locator(SEARCH).fill("zzzz");
        await expect(page.locator("#listExamples .empty")).toBeVisible();
      }),
      browserView("browser-list-hover", async (page) => {
        await openList(page);
        await page.locator(LIST_ROW).nth(3).hover();
      }),
      browserView("browser-search-focus", async (page) => {
        await openList(page);
        await page.locator(SEARCH).focus();
      }),
      browserView("browser-info-hidden", async (page) => {
        await browserReady(page);
        await page.locator("#checkboxShowInfo").uncheck();
        await expect(page.locator("#exampleInfoBox")).toBeHidden();
      }),
      browserView("browser-error", async (page) => {
        await runCode(page, "throw new Error('Design gallery sample error');");
        await expect(page.locator("#textareaError")).toBeVisible({ timeout: resolveTimeout(15_000) });
      }),
      browserView("browser-console", async (page) => {
        await runCode(page, "console.log('Design gallery sample output');");
        await expect(page.locator("#textareaConsole")).toBeVisible({ timeout: resolveTimeout(15_000) });
      }),
      browserView("browser-button-hover", async (page) => {
        await browserReady(page);
        await page.locator("#buttonPrev").hover();
      }),
      browserView("browser-button-focus", async (page) => {
        await browserReady(page);
        await focusByKeyboard(page, page.locator("#buttonNext"));
      }),
      browserView("browser-theme-picked", async (page) => {
        await browserReady(page);
        const before = await page.locator(HTML).getAttribute("data-theme");
        await page.locator(THEME_BUTTON).click();
        await expect(page.locator(HTML)).not.toHaveAttribute("data-theme", before || "");
      }),
      { name: "stage-short", url: short("shapes.js"), prepare: stageReady },
      { name: "stage-game", url: `${base}/examples/breakout/`, prepare: stageReady },
    ];
  }

  test("design: gallery of the launcher, its menus, the example browser and two stages", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_800_000));
    await forgetBrowserChoices(page);
    await captureDesignGallery(page, galleryViews());
  });
};
