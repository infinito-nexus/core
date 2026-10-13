const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
} = require("./design");
const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLogin,
  requireDotenvValue,
} = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = decodeDotenvQuotedValue(requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN"));
const adminUsername = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"));
const adminPassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));
const adminNativePassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_NATIVE_PASSWORD, "ADMIN_NATIVE_PASSWORD"));
const faviconUrl = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_FAVICON_URL, "DESIGN_FAVICON_URL"));
const headerUrl = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_HEADER_URL, "DESIGN_HEADER_URL"));
const iconUrl = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_ICON_URL, "DESIGN_ICON_URL"));
const logoUrl = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_LOGO_URL, "DESIGN_LOGO_URL"));
const designTitle = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_TITLE, "DESIGN_TITLE"));

const MODES = ["light", "dark"];
const CSS_MARKER = ":root{--infinito-design-carrier:1}";
const JS_MARKER = "window.infinitoDesignCarrier = 1;";
const LOGIN_FORM = "section.login form";
const LOGIN_USER = `${LOGIN_FORM} #username`;
const LOGIN_PASSWORD = `${LOGIN_FORM} #password`;
const LOGIN_SUBMIT = `${LOGIN_FORM} button[type='submit']`;
const PANEL = ".container.wrap";
const NAVBAR = "#app .navbar";
const MAIN = "#app .main";
const HEADING = ".main h1.title";
const ROW = ".main table tbody tr";
const CELL = ".main table tbody td";
const PRIMARY = ".main [data-cy=btn-new]";
const NAV_LINK = ".b-sidebar .menu-list a";
const SELECTED_NAV = ".b-sidebar .menu-list ul a.is-active";
const SELECTED_GROUP = ".b-sidebar .menu-list > li > a.is-active";
const LOGO = ".navbar-brand .full";
const SMALL_LOGO = ".navbar-brand .favicon";
const PREF_KEY = "listmonk_pref";

test.use({ ignoreHTTPSErrors: true });

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
      { message: "every finite animation of the page must have ended", timeout: resolveTimeout(10_000) },
    )
    .toBe(false);
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(page.locator(".loading-overlay:visible")).toHaveCount(0, { timeout: resolveTimeout(10_000) });
    await animationsSettled(page);
  };
}

/**
 * Args:
 *   page: Playwright page that ends signed in to the Listmonk administration as its administrator, through Keycloak when sso is on and through the native form with ADMIN_NATIVE_PASSWORD otherwise.
 */
async function signIn(page) {
  await gotoOnion(page, `${base}/admin/login`);
  if (isServiceEnabled("sso")) {
    await page.waitForURL(/openid-connect\/auth/, { timeout: resolveTimeout(30_000) });
    await performKeycloakLogin(page, adminUsername, adminPassword, canonicalDomain);
    await gotoOnion(page, `${base}/admin/`);
  } else {
    await expect(page.locator(LOGIN_PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(LOGIN_USER).fill(adminUsername);
    await page.locator(LOGIN_PASSWORD).fill(adminNativePassword);
    await page.locator(LOGIN_SUBMIT).click({ timeout: resolveTimeout(10_000) });
  }
  await expect(page.locator(NAVBAR)).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(page).toHaveURL(/\/admin/);
}

/**
 * Args:
 *   page: Playwright page on the administration whose stored settings tab is set.
 *   tab: index of the settings tab the next settings page opens on.
 */
async function settingsTab(page, tab) {
  await page.evaluate(
    ([key, index]) => {
      const pref = JSON.parse(localStorage.getItem(key) || "{}");
      pref["settings.tab"] = index;
      localStorage.setItem(key, JSON.stringify(pref));
    },
    [PREF_KEY, tab],
  );
}

async function served(page, url) {
  return page.evaluate(
    (src) =>
      new Promise((resolve) => {
        const image = new Image();
        image.onload = () => resolve(image.naturalWidth > 0);
        image.onerror = () => resolve(false);
        image.src = src;
      }),
    url,
  );
}

function publicViews() {
  return [
    { name: "public-home", url: `${base}/`, prepare: shown("section.center a.button") },
    { name: "public-login", url: `${base}/admin/login`, prepare: shown(LOGIN_PASSWORD) },
    {
      name: "public-login-error",
      url: `${base}/admin/login`,
      prepare: async (page) => {
        await expect(page.locator(LOGIN_PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
        await page.locator(LOGIN_USER).fill("design-gallery-nobody");
        await page.locator(LOGIN_PASSWORD).fill(`gallery-${Date.now()}`);
        await page.locator(LOGIN_SUBMIT).click({ timeout: resolveTimeout(10_000) });
        await shown(".login .error")(page);
      },
    },
    { name: "public-subscription", url: `${base}/subscription/form`, prepare: shown("ul.lists li") },
    { name: "public-archive", url: `${base}/archive`, prepare: shown(`${PANEL} h2`) },
    { name: "public-404", url: `${base}/design-gallery-missing`, prepare: shown(PANEL) },
  ];
}

function adminViews() {
  const view = (name, path, selector) => ({ name, url: `${base}/admin${path}`, prepare: shown(selector) });
  const lists = `${base}/admin/lists`;
  const settings = `${base}/admin/settings`;
  const tabView = (name, index, selector) => ({
    name,
    url: settings,
    prepare: async (page) => {
      await shown(".settings-tabs .tab-content")(page);
      await page
        .locator(".settings-tabs > nav.tabs li")
        .nth(index)
        .locator("a")
        .click({ timeout: resolveTimeout(10_000) });
      await shown(selector)(page);
      await settingsTab(page, 0);
    },
  });
  return [
    view("dashboard", "/", "section.dashboard .counts"),
    view("lists", "/lists", ROW),
    {
      name: "list-new",
      url: lists,
      prepare: async (page) => {
        await shown(ROW)(page);
        await page.locator(PRIMARY).first().click({ timeout: resolveTimeout(10_000) });
        await shown(".modal-card")(page);
      },
    },
    view("list-forms", "/lists/forms", HEADING),
    view("subscribers", "/subscribers", ROW),
    view("subscriber-detail", "/subscribers/1", ".modal-card"),
    view("import", "/subscribers/import", "section.import form"),
    view("bounces", "/subscribers/bounces", HEADING),
    view("campaigns", "/campaigns", ROW),
    view("campaign", "/campaigns/1", "section.campaign form"),
    {
      name: "campaign-content",
      url: `${base}/admin/campaigns/1`,
      prepare: async (page) => {
        await shown("section.campaign form")(page);
        await page
          .locator("section.campaign nav.tabs li")
          .nth(1)
          .locator("a")
          .click({ timeout: resolveTimeout(10_000) });
        await shown(".tox-tinymce, .code-editor .cm-editor")(page);
      },
    },
    view("campaign-new", "/campaigns/new", "section.campaign form"),
    view("media", "/campaigns/media", HEADING),
    view("templates", "/campaigns/templates", ROW),
    view("analytics", "/campaigns/analytics", HEADING),
    view("users", "/users", ROW),
    view("user-roles", "/users/roles/users", ROW),
    {
      name: "settings",
      url: settings,
      prepare: async (page) => {
        await settingsTab(page, 0);
        await gotoOnion(page, settings);
        await shown(".settings-tabs .tab-content")(page);
      },
    },
    tabView("settings-smtp", 5, ".settings-tabs .tab-item:not([style*='none']) .box, .settings-tabs .tab-content"),
    tabView("settings-appearance", 8, ".settings .code-editor .cm-editor"),
    view("maintenance", "/settings/maintenance", HEADING),
    view("logs", "/settings/logs", ".log-view"),
    view("profile", "/user/profile", HEADING),
    {
      name: "user-menu",
      url: lists,
      prepare: async (page) => {
        await shown(ROW)(page);
        const burger = page.locator(".navbar-burger");
        if (await burger.isVisible()) {
          await burger.click({ timeout: resolveTimeout(10_000) });
          await shown(".navbar-menu.is-active")(page);
        }
        await page.locator(".navbar-item.user .navbar-link").first().click({ timeout: resolveTimeout(10_000) });
        await shown(".navbar-item.user .navbar-dropdown")(page);
      },
    },
    {
      name: "nav-hover",
      url: lists,
      prepare: async (page) => {
        await shown(ROW)(page);
        const entry = page.locator(`${NAV_LINK}:visible`).nth(2);
        if (await entry.isVisible()) {
          await entry.hover({ timeout: resolveTimeout(10_000) });
          await animationsSettled(page);
        }
      },
    },
  ];
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base}/`);
    await shown("section.center a.button")(page);
    await assertDesignTokens(page, "listmonk");
  });

  test("design: the public pages take surface, panel, form, primary action and text from the palette", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    const form = "form.form";
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/subscription/form`);
      await shown("ul.lists li")(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `subscription ${mode}`);
      await assertToken(page, PANEL, "background-color", "--design-surface-2", `subscription ${mode}`);
      await assertToken(page, PANEL, "border-top-color", "--design-border", `subscription ${mode}`);
      await assertToken(page, ".header", "border-bottom-color", "--design-border", `subscription divider ${mode}`);
      await assertToken(page, `${form} label`, "color", "--design-text", `subscription ${mode}`);
      await assertToken(page, `${form} input[name=name]`, "border-top-color", "--design-border-strong", `field ${mode}`);
      await page.locator(`${form} input[type=email]`).focus();
      await assertToken(page, `${form} input[type=email]`, "border-top-color", "--design-link", `focused field ${mode}`);
      await assertToken(page, `${form} .button`, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, `${form} .button`, "color", "--design-on-primary", `primary action ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, PANEL, "listmonk public panel");
    await assertReadable(
      page,
      [
        `${form} label`,
        `${form} .button`,
        "footer.container",
        { selector: ".lists .description", optional: true },
        { selector: "footer.container a", optional: true },
      ],
      "listmonk public",
    );
  });

  test("design: the administration takes surfaces, primary action, text and dividers from the palette", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/admin/lists`);
      await shown(ROW)(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, MAIN, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, NAVBAR, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, HEADING, "color", "--design-text", `shell ${mode}`);
      await assertToken(page, CELL, "color", "--design-text", `shell ${mode}`);
      await assertToken(page, CELL, "border-bottom-color", "--design-border", `content divider ${mode}`);
      await assertToken(page, PRIMARY, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, PRIMARY, "color", "--design-on-primary", `primary action ${mode}`);
      await page.locator(PRIMARY).first().hover({ timeout: resolveTimeout(10_000) });
      await assertToken(page, PRIMARY, "background-color", "--design-primary-hover", `hovered primary ${mode}`);
      await page.mouse.move(0, 0);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, MAIN, "listmonk shell");
    await assertReadable(page, [HEADING, CELL, PRIMARY, { selector: NAV_LINK, optional: true }], "listmonk shell");
  });

  test("design: the selected navigation entry and the status tags keep readable palette states", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${base}/admin/campaigns/1`);
    await shown("section.campaign form")(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      for (const entry of [SELECTED_NAV, SELECTED_GROUP]) {
        await assertToken(page, entry, "color", "--design-link", `selected entry ${mode}`);
        await assertToken(page, entry, "background-color", "--design-surface-active", `selected entry ${mode}`);
      }
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [SELECTED_NAV, SELECTED_GROUP], "listmonk navigation states");
    await gotoOnion(page, `${base}/admin/lists`);
    await shown(ROW)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".main .tag.public", "background-color", "--design-info-subtle", `public tag ${mode}`);
      await assertToken(page, ".main .tag.private", "background-color", "--design-warning-subtle", `private tag ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [".main .tag.public", ".main .tag.private"], "listmonk states");
  });

  test("design: the code editors take surface, gutter and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await settingsTab(page, 8);
    const editor = ".settings .code-editor .cm-editor";
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/admin/settings`);
      await shown(editor)(page);
      await assertToken(page, editor, "background-color", "--design-surface-2", `code editor ${mode}`);
      await assertToken(page, editor, "color", "--design-text", `code editor ${mode}`);
      await assertToken(page, `${editor} .cm-gutters`, "background-color", "--design-surface-2", `code gutter ${mode}`);
      await assertToken(page, `${editor} .cm-gutters`, "color", "--design-text-muted", `code gutter ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, editor, "listmonk code editor");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const weak = await page.evaluate((selector) => {
        const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
        const rgb = (value) => {
          ctx.clearRect(0, 0, 1, 1);
          ctx.fillStyle = value;
          ctx.fillRect(0, 0, 1, 1);
          return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
        };
        const lum = (c) =>
          c
            .map((v) => v / 255)
            .map((s) => (s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4))
            .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
        const editorElement = document.querySelector(selector);
        const background = lum(rgb(getComputedStyle(editorElement).backgroundColor));
        const found = {};
        for (const span of editorElement.querySelectorAll(".cm-line span")) {
          const fg = lum(rgb(getComputedStyle(span).color));
          const ratio = (Math.max(fg, background) + 0.05) / (Math.min(fg, background) + 0.05);
          if (ratio < 4.5) found[span.className] = ratio.toFixed(2);
        }
        return found;
      }, editor);
      expect(weak, `${mode}: every highlighted token reaches 4.5:1 against the editor surface`).toEqual({});
    }
    await page.emulateMedia({ colorScheme: null });
    await settingsTab(page, 0);
  });

  test("design: logo, favicon and title come from the design lookup", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base}/`);
    await shown("section.center a.button")(page);
    await expect(page.locator(".header .logo img")).toHaveAttribute("src", headerUrl);
    await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
    await expect(page).toHaveTitle(new RegExp(`${designTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
    await signIn(page);
    await gotoOnion(page, `${base}/admin/lists`);
    await shown(ROW)(page);
    await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
    await expect.poll(() => page.title(), { message: "the admin title ends with the design title" }).toMatch(
      new RegExp(`${designTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
    );
    const visible = (await page.locator(LOGO).isVisible()) ? LOGO : SMALL_LOGO;
    await expect(page.locator(visible)).toHaveCSS("content", `url("${visible === LOGO ? logoUrl : iconUrl}")`);
    if (visible === LOGO) {
      const box = await page.locator(LOGO).boundingBox();
      expect(box.width, "the navbar logo is a wide lockup").toBeGreaterThan(box.height * 3);
      expect(box.height, "the navbar lockup is tall enough to read its title").toBeGreaterThan(24);
    }
    for (const url of [logoUrl, headerUrl, iconUrl, faviconUrl]) {
      expect(await served(page, url), `the page must be allowed to load ${url}`).toBe(true);
    }
  });

  test("design: the role writes only its own marked appearance settings", async ({ page, request }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    const fetchText = (url) => page.evaluate(async (target) => (await fetch(target)).text(), url);
    const adminCss = await fetchText(`${base}/admin/custom.css`);
    expect(adminCss.startsWith(CSS_MARKER), "the admin custom CSS carries the role marker first").toBe(true);
    expect(/#[0-9a-fA-F]{3,8}\b(?![\w-])/.test(adminCss.replace(/url\([^)]*\)/g, "")), "no literal color").toBe(false);
    expect((await fetchText(`${base}/admin/custom.js`)).startsWith(JS_MARKER), "the admin custom JS carries the marker").toBe(
      true,
    );
    const publicCss = await apiGetOnion(request, `${base}/public/custom.css`, { timeout: resolveTimeout(30_000) });
    expect((await publicCss.text()).startsWith(CSS_MARKER), "the public custom CSS carries the role marker first").toBe(
      true,
    );
  });

  test("design: gallery of public pages, lists, subscribers, campaigns, users and settings", async ({
    browser,
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    const failures = [];
    const visitor = await browser.newContext({ ignoreHTTPSErrors: true });
    const publicSide = publicViews().filter((v) => !(isServiceEnabled("sso") && v.name.startsWith("public-login")));
    await captureDesignGallery(await visitor.newPage(), publicSide).catch((error) => failures.push(error.message));
    await visitor.close();
    await signIn(page);
    await captureDesignGallery(page, adminViews()).catch((error) => failures.push(error.message));
    expect(failures, "design gallery views failed").toEqual([]);
  });
};
