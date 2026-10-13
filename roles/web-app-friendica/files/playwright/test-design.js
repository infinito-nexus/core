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
const { resolveTimeout } = require("./timeouts");

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
const brandUrl = decodeDotenvQuotedValue(process.env.DESIGN_BRAND_URL);
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);

const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const TOPBAR = "#topbar-first";
const VISITOR_NAV = "nav.navbar";
const CONTENT = "section > .generic-page-wrapper";
const USERNAME = "#login-form input[name='username']";
const SIGN_IN_SUBMIT = "#login-submit-button";
const REGISTER = "#register-link";
const SETTINGS_SUBMIT = "#content button.btn-primary[name='password-submit']";
const ADMIN = ".adminpage";
const ROW_CELL = "table.table > tbody > tr > td";
const SCHEME_PANEL = "#theme-settings-content";
const SHOWCASE = "Infinito design showcase post";

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   shared: the role's _shared.js module.
 *   page: Playwright page that ends signed in as the administrator, through Keycloak first when sso is on.
 */
async function signIn(shared, page) {
  await shared.pickLoginPath()(page, shared.env.adminUsername, shared.env.adminPassword);
}

/**
 * Args:
 *   page: page on /settings/display; opens the theme accordion and waits until its collapse ended.
 */
async function openSchemePanel(page) {
  await shown("#settings-form")(page);
  await page.evaluate((panel) => window.jQuery(panel).collapse("show"), SCHEME_PANEL);
  await expect(page.locator(SCHEME_PANEL)).toHaveClass(/\bin\b/, { timeout: resolveTimeout(10_000) });
  await expect(page.locator(`${SCHEME_PANEL}.collapsing`)).toHaveCount(0, { timeout: resolveTimeout(10_000) });
}

/**
 * Args:
 *   page: signed-in page on /settings/display.
 *   scheme: value of the frio scheme select; it is the only frio field the post carries.
 */
async function saveScheme(page, scheme) {
  await openSchemePanel(page);
  await page.locator("#id_frio_scheme").selectOption(scheme);
  await page
    .locator("#settings-form")
    .evaluate((form) => form.querySelectorAll("[name^='frio_']:not([name='frio_scheme'])").forEach((field) => field.remove()));
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator("button[name='frio-settings-submit']").first().click({ timeout: resolveTimeout(10_000) }),
  ]);
}

/**
 * Args:
 *   shared: the role's _shared.js module.
 *   page: signed-in page; posts one public showcase status on the administrator's wall when none exists.
 */
async function seedShowcase(shared, page) {
  const base = shared.trimmedBaseUrl();
  const wall = `${base}/profile/${shared.env.adminUsername}/conversations`;
  await gotoOnion(page, wall);
  await shown("#content")(page);
  if ((await page.getByText(SHOWCASE).count()) > 0) return;
  await gotoOnion(page, `${base}/compose`);
  const body = page.locator("textarea[name='body']").first();
  await expect(body).toBeEditable({ timeout: resolveTimeout(10_000) });
  await body.fill(SHOWCASE);
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator("form.comment-edit-form button[type='submit'][name='submit']").first().click({ timeout: resolveTimeout(10_000) }),
  ]);
  await gotoOnion(page, wall);
  await expect(page.getByText(SHOWCASE).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
}

exports.register = function (shared) {
  const base = () => shared.trimmedBaseUrl();

  test("design: the administrator signs in with the password the role provisions", async ({ page }) => {
    await signIn(shared, page);
    await expect(page.locator(TOPBAR)).toBeVisible({ timeout: resolveTimeout(10_000) });
    await gotoOnion(page, `${base()}/admin`);
    await expect(page.locator(ADMIN), "the provisioned administrator holds admin rights").toBeVisible({ timeout: resolveTimeout(10_000) });
  });

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base()}/about`);
    await shown(VISITOR_NAV)(page);
    await assertDesignTokens(page, "friendica");
  });

  test("design: the sign-in page takes frame, surface, primary action and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(shared.isServiceEnabled("sso"), "oauth2-proxy gates /login; the signed-in tests cover the palette");
    await gotoOnion(page, `${base()}/login`);
    await shown(SIGN_IN_SUBMIT)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in page ${mode}`);
      await expect(page.locator("body"), `the backdrop image and gradient are dropped in ${mode} mode`).toHaveCSS("background-image", "none");
      await assertToken(page, VISITOR_NAV, "background-color", "--design-frame", `visitor navbar ${mode}`);
      await assertToken(page, USERNAME, "background-color", "--design-surface-2", `username field ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary", `sign-in button ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "color", "--design-on-primary", `sign-in button text ${mode}`);
      await page.locator(SIGN_IN_SUBMIT).hover();
      await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in button ${mode}`);
      await page.mouse.move(0, 0);
      if (await page.locator(REGISTER).isVisible()) {
        await assertToken(page, REGISTER, "background-color", "--design-success", `create-account button ${mode}`);
        await assertToken(page, REGISTER, "color", "--design-on-success", `create-account button text ${mode}`);
      }
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, USERNAME, "friendica sign-in");
    await assertReadable(page, [SIGN_IN_SUBMIT, "#login-form label", { selector: "#lost-password-link", optional: true }], "friendica sign-in");
  });

  test("design: the signed-in shell takes frame, surfaces, dividers and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/moderation/users`);
    await shown(ROW_CELL)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, TOPBAR, "background-color", "--design-frame", `top bar ${mode}`);
      await assertToken(page, `${TOPBAR} .nav > li > a`, "color", "--design-on-frame", `top bar icon ${mode}`);
      await assertToken(page, "#topbar-second", "background-color", "--design-surface-2", `second bar ${mode}`);
      await assertToken(page, ADMIN, "background-color", "--design-surface-2", `content panel ${mode}`);
      await assertToken(page, ROW_CELL, "border-top-color", "--design-border", `row divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ADMIN, "friendica moderation list");
    await assertReadable(page, [`${ADMIN} h1`, ROW_CELL, { selector: "aside .widget li a", optional: true }], "friendica shell");
  });

  test("design: a settings form saves through a primary control in the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/settings`);
    await shown(SETTINGS_SUBMIT)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, CONTENT, "background-color", "--design-surface-2", `settings panel ${mode}`);
      await assertToken(page, SETTINGS_SUBMIT, "background-color", "--design-primary", `save ${mode}`);
      await assertToken(page, SETTINGS_SUBMIT, "color", "--design-on-primary", `save text ${mode}`);
      await assertToken(page, "#content .form-control", "background-color", "--design-surface-2", `field ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [SETTINGS_SUBMIT, "#content .accordion-toggle", { selector: "#content label", optional: true }], "friendica settings form");
  });

  test("design: the calendar marks today with a palette surface in light and dark mode", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/calendar`);
    await shown(".fc-unthemed td.fc-today")(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".fc-unthemed td.fc-today", "background-color", "--design-surface-active", `today cell ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: frio carries the provisioned light palette as its site default", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/network`);
    await shown(TOPBAR)(page);
    await page.emulateMedia({ colorScheme: "light" });
    const meta = await page.locator("meta[name='theme-color']").first().getAttribute("content");
    const asColor = await page.evaluate((value) => {
      const probe = document.createElement("span");
      probe.style.color = value;
      document.body.appendChild(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    }, meta);
    expect(asColor, "frio.nav_bg must hold the light frame color").toBe(await tokenValue(page, "--design-frame", "color"));
    await expect(page.locator("html"), "the site default scheme leaves the mode to the browser").not.toHaveAttribute("data-design-theme", /.+/);
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: every focus stop in the top bar draws its indicator in the frame text color", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/network`);
    await shown(TOPBAR)(page);
    const expected = await tokenValue(page, "--design-on-frame", "outline-color");
    await page.locator(`${TOPBAR} a, ${TOPBAR} button`).first().focus();
    const seen = [];
    for (let step = 0; step < 30 && seen.length < 6; step += 1) {
      const stop = await page.evaluate((bar) => {
        const element = document.activeElement;
        if (!element || !element.closest(bar) || element.closest(".dropdown-menu")) return null;
        const style = getComputedStyle(element);
        return { style: style.outlineStyle, color: style.outlineColor, name: element.id || element.className };
      }, TOPBAR);
      if (stop) seen.push(stop);
      await page.keyboard.press("Tab");
    }
    expect(seen.length, "the top bar must hold keyboard focus stops").toBeGreaterThan(0);
    for (const stop of seen) {
      expect(stop.style, `focus indicator style of ${stop.name}`).not.toBe("none");
      expect(stop.color, `focus indicator of ${stop.name}`).toBe(expected);
    }
  });

  test("design: navigation shows the generated logos, the configured title and favicon", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!logoUrl, "logo replacement is disabled for this role");
    await page.setViewportSize(DESKTOP);
    await gotoOnion(page, `${base()}/about`);
    await shown(VISITOR_NAV)(page);
    const brand = page.locator(".navbar-brand #logo-img").first();
    await expect(brand).toHaveCSS("background-image", `url("${brandUrl}")`);
    await expect(page.locator("#navbar-brand-text").first()).toBeHidden();
    const box = await brand.boundingBox();
    expect(box, "the visitor brand box renders").not.toBeNull();
    expect(box.width, "the visitor brand box carries a wide lockup").toBeGreaterThan(box.height * 1.5);
    await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    if (title) await expect(page).toHaveTitle(new RegExp(`\\| ${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/network`);
    await shown(TOPBAR)(page);
    await expect(page.locator("header #banner #logo-img").first()).toHaveCSS("background-image", `url("${logoUrl}")`);
  });

  test("design: picking the dark frio scheme keeps the palette and switches to dark tokens", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/settings/display`);
    await openSchemePanel(page);
    const original = await page.locator("#id_frio_scheme").inputValue();
    try {
      await saveScheme(page, "dark");
      await gotoOnion(page, `${base()}/network`);
      await shown(TOPBAR)(page);
      await page.emulateMedia({ colorScheme: "light" });
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark", { timeout: resolveTimeout(10_000) });
      await assertToken(page, "body", "background-color", "--design-surface-1", "dark scheme under a light browser");
      await assertToken(page, TOPBAR, "background-color", "--design-frame", "top bar of the dark scheme");
    } finally {
      await page.emulateMedia({ colorScheme: null });
      await gotoOnion(page, `${base()}/settings/display`);
      await saveScheme(page, original);
    }
  });

  function visitorViews() {
    return [
      { name: "home-sign-in", url: `${base()}/`, prepare: shown(SIGN_IN_SUBMIT) },
      { name: "sign-in", url: `${base()}/login`, prepare: shown(SIGN_IN_SUBMIT) },
      {
        name: "sign-in-focus",
        url: `${base()}/login`,
        prepare: async (page) => {
          await shown(USERNAME)(page);
          await page.locator(USERNAME).focus();
        },
      },
      { name: "lost-password", url: `${base()}/lostpass`, prepare: shown("#content form") },
      { name: "about", url: `${base()}/about`, prepare: shown("#content") },
    ];
  }

  function signedInViews() {
    const nick = shared.env.adminUsername;
    const view = (name, path, selector) => ({ name, url: `${base()}${path}`, prepare: shown(selector) });
    return [
      view("network", "/network", "#content"),
      view("own-wall", `/profile/${nick}/conversations`, "#content"),
      view("own-profile", `/profile/${nick}/profile`, "#content"),
      view("photos", `/profile/${nick}/photos`, "#content"),
      view("compose", "/compose", "textarea[name='body']"),
      view("contacts", "/contact", "#content"),
      view("circle-new", "/circle/new", "#content"),
      view("calendar", "/calendar", "#content"),
      view("event-new", "/calendar/event/new", "#content form"),
      view("notes", "/notes", "#content"),
      view("notifications", "/notifications/system", "#content"),
      view("search", "/search?q=infinito", "#content"),
      view("settings-account", "/settings", SETTINGS_SUBMIT),
      { name: "settings-theme", url: `${base()}/settings/display`, prepare: openSchemePanel },
      view("settings-profile", "/settings/profile", "#profile-edit-form"),
      view("settings-features", "/settings/features", CONTENT),
      view("admin-summary", "/admin", ADMIN),
      view("admin-site", "/admin/site", `${ADMIN} form`),
      view("admin-addons", "/admin/addons", "#content h1"),
      view("admin-theme-frio", "/admin/themes/frio", "#content h1"),
      view("admin-federation", "/admin/federation", "#content h1"),
      view("moderation-users", "/moderation/users", ROW_CELL),
      {
        name: "user-menu-open",
        url: `${base()}/network`,
        afterOnly: true,
        prepare: async (page) => {
          await shown(TOPBAR)(page);
          const desktop = await page.locator("#main-menu").isVisible();
          const panel = desktop ? page.locator("#nav-user-menu") : page.locator("#offcanvasUsermenu");
          await page.locator(desktop ? "#main-menu" : ".offcanvas-right-toggle").first().click({ timeout: resolveTimeout(10_000) });
          await expect(panel).toBeVisible({ timeout: resolveTimeout(10_000) });
          await expect
            .poll(() => panel.evaluate((element) => element.getAnimations({ subtree: true }).length + (getComputedStyle(element).opacity === "1" ? 0 : 1)), {
              timeout: resolveTimeout(10_000),
            })
            .toBe(0);
        },
      },
    ];
  }

  test("design: gallery of sign-in, stream, profile, settings, administration and moderation", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_500_000));
    const failures = [];
    await captureDesignGallery(page, visitorViews()).catch((error) => failures.push(error.message));
    await signIn(shared, page);
    await seedShowcase(shared, page);
    await captureDesignGallery(page, signedInViews()).catch((error) => failures.push(error.message));
    expect(failures, "design gallery captures").toEqual([]);
  });
};
