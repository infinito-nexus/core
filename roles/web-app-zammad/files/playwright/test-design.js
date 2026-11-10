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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion, requireDotenvValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const FOCUS_WALK_LIMIT = 60;
const NAVIGATION = "#navigation";
const MENU_ITEM = `${NAVIGATION} .menu a.menu-item`;
const MENU_SELECTED = `${NAVIGATION} .menu a.menu-item.is-active`;
const NAV_LOGO = `${NAVIGATION} .search .logo`;
const USER_MENU = `${NAVIGATION} .user-menu > li.user`;
const USER_MENU_PANEL = `${USER_MENU} > .dropdown-menu`;
const LOGIN = ".login.fullscreen";
const LOGIN_CARD = `${LOGIN} .hero-unit`;
const LOGIN_SUBMIT = "form#login button.btn--primary";
const LOGIN_LOGO = `${LOGIN} img.company-logo`;
const USERNAME = "#username";
const CONTENT = ".content.active";
const PAGE_TITLE = `${CONTENT} .page-header-title h1`;
const TABLE_HEAD = `${CONTENT} .table > thead > tr > th`;
const TABLE_CELL = `${CONTENT} .table > tbody > tr > td`;
const SETTINGS_ENTRY = `${CONTENT} .settings-entry`;
const PRIMARY_ACTION = `${CONTENT} .settings-entry .btn--primary`;
const ADMIN_SELECTED = `${CONTENT} .nav-pills > li.active > a`;
const THEME_RADIO = (value) => `label.radio-replacement:has(input[name='theme'][value='${value}'])`;
const CLUES = ".js-modal--clue, .modal-backdrop";
const SHOWCASE = "Design showcase";

exports.register = function (shared) {
  const base = shared.env.zammadBaseUrl;
  const botAuth = {
    Authorization: `Basic ${Buffer.from(`${shared.env.adminApiUsername}:${shared.env.adminApiPassword}`).toString("base64")}`,
    "Content-Type": "application/json",
  };

  function shown(selector) {
    return async (page) => {
      await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    };
  }

  /**
   * Args:
   *   page: Playwright page showing the dashboard, the only view that starts the clue tour, and only for an agent.
   */
  async function dropClues(page) {
    await page.evaluate((clues) => document.querySelectorAll(clues).forEach((element) => element.remove()), CLUES);
  }

  /**
   * Args:
   *   hash: route of the legacy interface.
   *   view: name that makes the document URL unique, so opening it loads a fresh document instead of changing the hash of the current one.
   *
   * Returns:
   *   The URL of that route.
   */
  function legacyUrl(hash, view) {
    return `${base}/?design=${view}#${hash}`;
  }

  /**
   * Args:
   *   page: Playwright page that ends signed in as the platform administrator: through the identity provider when sso is on, through Zammad's own sign-in API otherwise.
   */
  async function signInAsAdministrator(page) {
    if (shared.env.oidcEnabled) {
      await shared.signInViaZammadOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");
      return;
    }
    const signin = await shared.signInWithZammadPassword(page, shared.env.adminUsername, shared.env.adminPassword);
    expect(signin.ok(), `the administrator sign-in answered ${signin.status()}`).toBe(true);
  }

  /**
   * Args:
   *   page: signed-in Playwright page of the legacy interface.
   *   url: URL to open again once every onboarding tour of the dashboard is marked as seen.
   */
  async function skipIntro(page, url) {
    const pending = await page.evaluate(() => {
      const keys = ["intro", ...Object.values(window.App.Config.get("Clues") || {}).map((clue) => clue.preference_key)];
      return fetch(`${window.App.Config.get("api_path")}/users/me`, { headers: { Accept: "application/json" } })
        .then((response) => response.json())
        .then((account) => keys.filter((key) => key && !(account.preferences || {})[key]));
    });
    if (pending.length === 0) return;
    const saved = page.waitForResponse((response) => response.url().includes("/users/preferences"));
    await page.evaluate(
      (keys) =>
        window.App.Ajax.request({
          id: "design-intro",
          type: "PUT",
          url: `${window.App.Config.get("api_path")}/users/preferences`,
          data: JSON.stringify(Object.fromEntries(keys.map((key) => [key, true]))),
          processData: true,
        }),
      pending,
    );
    await saved;
    await gotoOnion(page, url);
    await shown(MENU_ITEM)(page);
  }

  /**
   * Args:
   *   page: Playwright page that ends on the dashboard signed in as the administrator, the account's theme following the browser.
   */
  async function signIn(page) {
    await signInAsAdministrator(page);
    await gotoOnion(page, legacyUrl("dashboard", "sign-in"));
    await shown(MENU_ITEM)(page);
    await skipIntro(page, legacyUrl("dashboard", "signed-in"));
    const stored = await page.evaluate(() => (window.App.Session.get("preferences") || {}).theme || "auto");
    if (stored !== "auto") {
      const saved = page.waitForResponse((response) => response.url().includes("/users/preferences"));
      await page.evaluate(() => window.App.Event.trigger("ui:theme:set", { theme: "auto", save: true }));
      await saved;
    }
  }

  /**
   * Args:
   *   request: Playwright API context without a session; the call authenticates as the API bot.
   *   method: HTTP verb.
   *   path: path below `/api/v1`.
   *   data: JSON body of a writing call.
   *
   * Returns:
   *   The parsed JSON body.
   */
  async function api(request, method, path, data) {
    const response = await apiFetchOnion(request, `${base}/api/v1${path}`, {
      method,
      headers: botAuth,
      data,
      timeout: resolveTimeout(30_000),
    });
    expect(response.ok(), `${method} /api/v1${path} answered ${response.status()}`).toBe(true);
    return response.json();
  }

  /**
   * Args:
   *   request: Playwright API context without a session.
   *
   * Returns:
   *   The id of the showcase ticket, created when no ticket carries its title.
   */
  async function seedShowcase(request) {
    const tickets = await api(request, "GET", "/tickets?per_page=200&page=1");
    const found = tickets.find((ticket) => ticket.title === SHOWCASE);
    if (found) return found.id;
    const created = await api(request, "POST", "/tickets", {
      title: SHOWCASE,
      group: "Users",
      customer: shared.env.adminApiUsername,
      article: { subject: SHOWCASE, body: "Seeded for the corporate design review.", type: "note", internal: false },
    });
    return created.id;
  }

  /**
   * Args:
   *   page: Playwright page that shows the navigation; resolves once the navigation stayed unchanged for a second.
   */
  async function navigationSettled(page) {
    await page.evaluate((frame) => {
      window.designNavigationChanged = performance.now();
      new MutationObserver(() => {
        window.designNavigationChanged = performance.now();
      }).observe(document.querySelector(frame), { childList: true, subtree: true });
    }, NAVIGATION);
    await page.waitForFunction(
      (quiet) => performance.now() - window.designNavigationChanged > quiet,
      resolveTimeout(1_000),
      { timeout: resolveTimeout(15_000) },
    );
  }

  /**
   * Args:
   *   page: Playwright page that shows the navigation; the keyboard walks forward through every stop of it.
   *   mode: color scheme the failure messages name.
   */
  async function assertFrameFocus(page, mode) {
    const ring = await tokenValue(page, "--design-on-frame", "color");
    const stops = [];
    await navigationSettled(page);
    await page.locator("#global-search").focus();
    for (let step = 0; step < FOCUS_WALK_LIMIT; step += 1) {
      const stop = await page.evaluate((frame) => {
        const element = document.activeElement;
        const framed = Boolean(element && element.closest(frame)) && !element.closest(".dropdown-menu");
        return {
          framed,
          name: element ? [element.tagName.toLowerCase(), ...element.classList].join(".") : "none",
          shadow: element ? getComputedStyle(element).boxShadow : "",
        };
      }, NAVIGATION);
      if (!stop.framed && stops.length > 0) break;
      if (stop.framed) {
        stops.push(stop.name);
        expect(stop.shadow, `keyboard stop ${stop.name} of the navigation ${mode} must draw its indicator in --design-on-frame`).toContain(ring);
      }
      await page.keyboard.press("Tab");
    }
    expect(stops.length, `the keyboard walk must find stops inside the navigation ${mode}`).toBeGreaterThan(3);
  }

  function signedOutView(name, hash, ready, after) {
    const url = legacyUrl(hash, name);
    return {
      name,
      url,
      prepare: async (page) => {
        await page.locator(`${ready}, ${MENU_ITEM}`).first().waitFor({ timeout: resolveTimeout(10_000) });
        if (await page.locator(MENU_ITEM).first().isVisible()) {
          await page.context().clearCookies();
          await gotoOnion(page, "about:blank");
          await gotoOnion(page, url);
        }
        await shown(ready)(page);
        if (after) await after(page);
      },
    };
  }

  function signedInView(name, hash, ready, after) {
    const url = legacyUrl(hash, name);
    return {
      name,
      url,
      prepare: async (page) => {
        await page.locator(`${MENU_ITEM}, ${LOGIN_SUBMIT}`).first().waitFor({ timeout: resolveTimeout(10_000) });
        if (!(await page.locator(MENU_ITEM).first().isVisible())) {
          await signInAsAdministrator(page);
          await gotoOnion(page, url);
        }
        await shown(MENU_ITEM)(page);
        await skipIntro(page, url);
        await shown(ready)(page);
        await dropClues(page);
        if (after) await after(page);
      },
    };
  }

  function views(ticketId) {
    const admin = (name, hash) => signedInView(name, hash, `${PAGE_TITLE}:visible`);
    return [
      signedOutView("sign-in", "login", LOGIN_SUBMIT),
      signedOutView("sign-in-focus", "login", LOGIN_SUBMIT, (page) => page.locator(USERNAME).focus()),
      signedOutView("password-reset", "password_reset", ".reset_password .hero-unit"),
      signedInView("ticket-overview", "ticket/view/all_unassigned", `${CONTENT} .overview-table .page-header:visible`),
      signedInView("ticket-detail", `ticket/zoom/${ticketId}`, `${CONTENT} .ticketZoom`),
      signedInView("ticket-create", "ticket/create", `${CONTENT} .newTicket`),
      signedInView("navigation-hover", "dashboard", MENU_ITEM, (page) => page.locator(MENU_ITEM).nth(1).hover()),
      signedInView("user-menu", "dashboard", USER_MENU, async (page) => {
        if (!(await page.locator(USER_MENU_PANEL).isVisible())) await page.locator(`${USER_MENU} > a`).click();
        await shown(USER_MENU_PANEL)(page);
        await expect
          .poll(() => page.locator(USER_MENU_PANEL).evaluate((element) => getComputedStyle(element).opacity), {
            timeout: resolveTimeout(10_000),
          })
          .toBe("1");
      }),
      admin("admin-users", "manage/users"),
      admin("admin-groups", "manage/groups"),
      admin("admin-roles", "manage/roles"),
      admin("admin-organizations", "manage/organizations"),
      admin("admin-overviews", "manage/overviews"),
      admin("admin-macros", "manage/macros"),
      admin("admin-triggers", "manage/trigger"),
      admin("admin-text-modules", "manage/text_modules"),
      signedInView("settings-branding", "settings/branding", SETTINGS_ENTRY),
      signedInView("settings-system", "settings/system", SETTINGS_ENTRY),
      signedInView("settings-security", "settings/security", SETTINGS_ENTRY),
      admin("system-integrations", "system/integration"),
      admin("system-objects", "system/object_manager"),
      admin("system-maintenance", "system/maintenance"),
      signedInView("profile-appearance", "profile/appearance", THEME_RADIO("auto")),
      admin("profile-password", "profile/password"),
      admin("profile-notifications", "profile/notifications"),
    ];
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await gotoOnion(page, legacyUrl("login", "tokens"));
    await shown(LOGIN_SUBMIT)(page);
    await assertDesignTokens(page, "zammad");
  });

  test("design: the sign-in page takes frame, card, primary action and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, legacyUrl("login", `sign-in-${mode}`));
      await shown(LOGIN_SUBMIT)(page);
      await expect(page.locator("html"), "a visitor's page follows the browser").toHaveAttribute("data-theme", mode);
      await assertToken(page, LOGIN,"background-color", "--design-frame", `sign-in ${mode}`);
      await assertToken(page, LOGIN_CARD, "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, LOGIN_CARD, "color", "--design-text", `sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await assertToken(page, USERNAME, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
      await page.locator(LOGIN_SUBMIT).hover();
      await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `hovered sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, LOGIN_CARD, "zammad sign-in");
    await assertReadable(
      page,
      [LOGIN_SUBMIT, `${LOGIN_CARD} label[for='username']`, `${LOGIN} .fullscreen-body > p`, { selector: `${LOGIN} .js-footer p`, optional: true }, ".poweredBy"],
      "zammad sign-in",
    );
  });

  test("design: the administration takes frame, surfaces, dividers, primary action and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(240_000));
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await page.mouse.move(900, 600);
      await gotoOnion(page, legacyUrl("dashboard", `dashboard-${mode}`));
      await shown(MENU_SELECTED)(page);
      await dropClues(page);
      await assertToken(page, MENU_SELECTED, "background-color", "--design-frame-active", `selected entry ${mode}`);
      await assertToken(page, MENU_SELECTED, "color", "--design-on-frame", `selected entry ${mode}`);
      await gotoOnion(page, legacyUrl("manage/users", `users-${mode}`));
      await shown(TABLE_CELL)(page);
      await expect(page.locator("html"), "an account without a stored theme follows the browser").toHaveAttribute("data-theme", mode);
      await assertFrameFocus(page, mode);
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, NAVIGATION, "background-color", "--design-frame", `frame ${mode}`);
      await assertToken(page, MENU_ITEM, "color", "--design-on-frame", `frame ${mode}`);
      await assertToken(page, PAGE_TITLE, "color", "--design-text", `shell ${mode}`);
      await assertToken(page, TABLE_HEAD, "background-color", "--design-surface-3", `list head ${mode}`);
      await assertToken(page, TABLE_CELL, "color", "--design-text", `list ${mode}`);
      await assertToken(page, TABLE_CELL, "border-top-color", "--design-border", `list row divider ${mode}`);
      await assertToken(page, ADMIN_SELECTED, "background-color", "--design-surface-active", `selected administration entry ${mode}`);
      await assertToken(page, ADMIN_SELECTED, "color", "--design-text", `selected administration entry ${mode}`);
      await page.locator(`${MENU_ITEM}:not(.is-active)`).first().hover();
      await assertToken(page, `${MENU_ITEM}:not(.is-active)`, "background-color", "--design-frame-hover", `hovered entry ${mode}`);
      await gotoOnion(page, legacyUrl("settings/branding", `branding-${mode}`));
      await shown(PRIMARY_ACTION)(page);
      await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `primary action ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await page.mouse.move(900, 600);
    await gotoOnion(page, legacyUrl("dashboard", "dashboard"));
    await shown(MENU_SELECTED)(page);
    await dropClues(page);
    await assertReadable(page, [MENU_ITEM, { selector: MENU_SELECTED, optional: true }], "zammad navigation");
    await gotoOnion(page, legacyUrl("manage/users", "users"));
    await shown(TABLE_CELL)(page);
    await assertLightAndDark(page, TABLE_CELL, "zammad shell");
    await assertReadable(page, [PAGE_TITLE, TABLE_HEAD, TABLE_CELL, ADMIN_SELECTED], "zammad shell");
  });

  test("design: a theme picked in the profile overrides the browser and is mirrored", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(180_000));
    await page.emulateMedia({ colorScheme: "light" });
    await signIn(page);
    await gotoOnion(page, legacyUrl("profile/appearance", "appearance"));
    await shown(THEME_RADIO("dark"))(page);
    const root = page.locator("html");
    const light = await tokenValue(page, "--design-surface-1", "color");
    const pick = async (value) => {
      const saved = page.waitForResponse((response) => response.url().includes("/users/preferences"));
      await page.locator(THEME_RADIO(value)).click();
      await saved;
    };
    try {
      await pick("dark");
      await expect(root).toHaveAttribute("data-theme", "dark");
      await expect(root).toHaveAttribute("data-design-theme", "dark");
      await assertToken(page, "body", "background-color", "--design-surface-1", "dark theme picked in zammad");
      expect(await tokenValue(page, "--design-surface-1", "color"), "the dark palette must differ").not.toBe(light);
      await page.emulateMedia({ colorScheme: "dark" });
      await pick("light");
      await expect(root).toHaveAttribute("data-design-theme", "light");
      expect(await tokenValue(page, "--design-surface-1", "color"), "a light theme must keep the light palette").toBe(light);
    } finally {
      await pick("auto");
    }
    await expect(root).toHaveAttribute("data-theme", "dark");
    await expect.poll(() => root.getAttribute("data-design-theme"), { message: "auto hands the palette back to the browser" }).toBeNull();
    expect(await tokenValue(page, "--design-surface-1", "color"), "auto follows the dark browser").not.toBe(light);
  });

  test("design: sign-in page, navigation and browser tab show the generated logo and the configured title", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    test.setTimeout(resolveTimeout(180_000));
    await gotoOnion(page, legacyUrl("login", "branding"));
    await shown(LOGIN_SUBMIT)(page);
    if (title) {
      await expect.poll(() => page.title(), { message: "the sign-in title must carry the configured title" }).toContain(title);
      await expect(page.locator(LOGIN_LOGO)).toHaveAttribute("alt", title);
    }
    if (logoUrl) {
      const brandUrl = requireDotenvValue(process.env.DESIGN_BRAND_URL, "DESIGN_BRAND_URL");
      const faviconUrl = requireDotenvValue(process.env.DESIGN_FAVICON_URL, "DESIGN_FAVICON_URL");
      const image = page.locator(LOGIN_LOGO);
      await expect
        .poll(() => image.evaluate((element) => element.complete && element.naturalWidth > 0), {
          message: "the product logo of the sign-in page must load",
        })
        .toBe(true);
      const box = await image.boundingBox();
      expect(box.width, "the sign-in logo is the lockup of logo and title, wider than high").toBeGreaterThan(box.height * 1.5);
      const served = await apiGetOnion(page.request, new URL(await image.getAttribute("src"), `${base}/`).toString());
      const generated = await apiGetOnion(page.request, brandUrl);
      expect(generated.ok(), "the generated lockup is published on the CDN").toBe(true);
      expect(await served.text(), "Zammad must serve the generated lockup as its product logo").toBe(await generated.text());
      await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    }
    await signIn(page);
    if (title) await expect.poll(() => page.title(), { message: "a signed-in title must carry the configured title" }).toContain(title);
    if (logoUrl) {
      await expect(page.locator(NAV_LOGO)).toHaveCSS("background-image", `url("${logoUrl}")`);
      await expect(page.locator(`${NAV_LOGO} .icon-logo`)).toHaveCSS("visibility", "hidden");
    }
  });

  test("design: gallery of sign-in, tickets, administration, settings and profile", async ({ page, request }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    await captureDesignGallery(page, views(await seedShowcase(request)));
  });
};
