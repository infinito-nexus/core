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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

function toHex(rgb) {
  return `#${rgb
    .match(/\d+/g)
    .slice(0, 3)
    .map((part) => Number(part).toString(16).padStart(2, "0"))
    .join("")}`;
}

const MODES = ["light", "dark"];
const THEME_LINK = 'link[rel="stylesheet"][href*="infinito-design.css"]';
const FAVICON = "link[rel~='icon']";
const LOGIN_SECTION = "section.for-login";
const LOGIN_CARD = `${LOGIN_SECTION} .page-card`;
const LOGIN_EMAIL = `${LOGIN_SECTION} #login_email`;
const LOGIN_PASSWORD = `${LOGIN_SECTION} #login_password`;
const LOGIN_SUBMIT = `${LOGIN_SECTION} .page-card-actions button[type='submit']`;
const LOGIN_LOGO = `${LOGIN_SECTION} img.app-logo`;
const LOGIN_ERROR = `${LOGIN_SECTION} .login-error-banner`;
const LOGIN_ERROR_ICON = `${LOGIN_ERROR} > svg`;
const LOGIN_ERROR_TITLE = `${LOGIN_ERROR} .es-alert__title`;
const FOLDER_TILE = ".desktop-container .folder-icon";
const ACTIVE_FILTER = ".btn.filter-button.btn-primary-light";
const PAGE_HEAD = ".page-head";
const PAGE_TITLE = ".page-head .es-breadcrumbs li:last-child .es-breadcrumbs__item";
const SIDEBAR = ".body-sidebar";
const SIDEBAR_ENTRY = `${SIDEBAR} .standard-sidebar-item:not(.active-sidebar) .sidebar-item-label`;
const SIDEBAR_SELECTED = `${SIDEBAR} .standard-sidebar-item.active-sidebar`;
const SIDEBAR_LINK_ENTRY = `${SIDEBAR} .sidebar-items .standard-sidebar-item:not(.active-sidebar):has(a:not(.section-break))`;
const SIDEBAR_HOVERED = `${SIDEBAR_LINK_ENTRY}:hover`;
const LIST_HEAD = ".frappe-list .list-row-head";
const LIST_ROW = ".frappe-list .list-row-container .list-row";
const LIST_READY = ".frappe-list .result:visible, .frappe-list .no-result:visible";
const FORM_READY = ".form-layout .form-page";
const WORKSPACE_WIDGET = ".layout-main-section .widget";
const CONTENT_RULE = ".layout-main-section hr";
const PAGE_ACTIONS = ".page-head .page-actions";
const PRIMARY_ACTION = `${PAGE_ACTIONS} .primary-action`;
const PRIMARY_ICON = `${PRIMARY_ACTION} .icon`;
const DESKTOP_LOGO = "#brand-logo";
const DESKTOP_READY = ".desktop-wrapper .desktop-container";
const DIALOG = ".modal.show .modal-content";
const THEME_GRID = `${DIALOG} .theme-grid`;
const THEME_CARD = `${THEME_GRID} .theme-card-wrapper .theme-card`;
const THEME_DARK = `${THEME_GRID} .theme-card-wrapper:has([data-theme="dark"]):not(:has([data-theme="light"])) .theme-card`;
const THEME_LIGHT = `${THEME_GRID} .theme-card-wrapper:has([data-theme="light"]):not(:has([data-theme="dark"])) .theme-card`;
const THEME_AUTO = `${THEME_GRID} .theme-card-wrapper:has([data-theme="light"]):has([data-theme="dark"]) .theme-card`;
const RED_PROBE = "#design-red-probe .es-button";
const SHOWCASE_TODO = "Design showcase";

exports.register = function (shared) {
  const base = shared.env.erpnextBaseUrl;

  function shown(selector) {
    return async (page) => {
      await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    };
  }

  /**
   * Args:
   *   page: Playwright page on a desk route; resolves once the desk booted and resolved its theme.
   */
  async function deskBooted(page) {
    await page.waitForFunction(
      () =>
        Boolean(window.frappe && window.frappe.boot && window.frappe.xcall) &&
        ["light", "dark"].includes(document.documentElement.getAttribute("data-theme")),
      null,
      { timeout: resolveTimeout(60_000) },
    );
  }

  /**
   * Args:
   *   page: signed-in Playwright page on a booted desk.
   *   theme: desk theme the account stores, `Automatic`, `Light` or `Dark`.
   */
  async function switchTheme(page, theme) {
    await page.evaluate(
      (choice) => window.frappe.xcall("frappe.core.doctype.user.user.switch_theme", { theme: choice }),
      theme,
    );
  }

  /**
   * Args:
   *   page: Playwright page that ends signed in as the native Administrator, the break-glass account every variant keeps, on a desk that links the theme file and whose theme follows the browser.
   */
  async function signIn(page) {
    await shared.signInViaErpnextLocal(page, "Administrator", shared.env.adminNativePassword, "design");
    await expect
      .poll(
        async () => {
          await gotoOnion(page, `${base}/desk/user`);
          return page.locator(THEME_LINK).count();
        },
        {
          message: "the desk must link the theme file the site config names in app_include_css",
          timeout: resolveTimeout(120_000),
          intervals: [10_000],
        },
      )
      .toBe(1);
    await deskBooted(page);
    await switchTheme(page, "Automatic");
  }

  /**
   * Args:
   *   page: signed-in Playwright page on a desk route; one open ToDo with the showcase text exists afterwards.
   */
  async function seedShowcase(page) {
    await page.evaluate(async (description) => {
      const found = await window.frappe.db.get_list("ToDo", { filters: { description }, limit: 1 });
      if (found.length === 0) {
        await window.frappe.db.insert({ doctype: "ToDo", description, priority: "High" });
      }
    }, SHOWCASE_TODO);
  }

  /**
   * Args:
   *   page: Playwright page to open a desk route on.
   *   route: path below `/desk`.
   *   ready: selector that is visible once the route rendered.
   */
  async function openDesk(page, route, ready) {
    await gotoOnion(page, `${base}/desk/${route}`);
    await deskBooted(page);
    await shown(ready)(page);
  }

  /**
   * Args:
   *   page: signed-in Playwright page on a desk route; its page actions hold one destructive solid button that Frappe's own button component rendered.
   */
  async function addRedAction(page) {
    const markup = await page.evaluate(() =>
      window.frappe.ui.button.html({ label: "Delete", variant: "solid", theme: "red" }),
    );
    await page.evaluate(
      ([html, actions]) => {
        document.getElementById("design-red-probe")?.remove();
        const holder = document.createElement("div");
        holder.id = "design-red-probe";
        holder.innerHTML = html;
        document.querySelector(actions).appendChild(holder);
      },
      [markup, PAGE_ACTIONS],
    );
  }

  async function openLogin(page) {
    await gotoOnion(page, `${base}/login`);
    await shown(LOGIN_EMAIL)(page);
  }

  /**
   * Args:
   *   page: Playwright page that shows the open theme dialog once its fade ended.
   */
  async function themeDialogOpened(page) {
    await page.keyboard.press("Control+Shift+G");
    await shown(THEME_GRID)(page);
    await expect(page.locator(".modal.show")).toHaveCSS("opacity", "1");
  }

  /**
   * Args:
   *   page: Playwright page with the open theme dialog.
   *   tile: selector of the theme tile to pick; resolves once the server stored the choice.
   */
  async function pickTheme(page, tile) {
    const stored = page.waitForResponse((response) => response.url().includes("switch_theme"));
    await page.locator(tile).click();
    await stored;
  }

  /**
   * Args:
   *   page: Playwright page that shows the logo.
   *   selector: selector of the logo image.
   *   logoUrl: URL of the generated lockup the image must load.
   *   label: place the failure messages name.
   */
  async function assertLockup(page, selector, logoUrl, label) {
    const image = page.locator(selector).first();
    await expect(image).toHaveAttribute("src", logoUrl);
    await expect
      .poll(() => image.evaluate((element) => element.complete && element.naturalWidth > 0), {
        message: `${label}: the page must be allowed to load the logo`,
      })
      .toBe(true);
    const box = await image.boundingBox();
    expect(box.width, `${label}: the logo is a lockup, wider than high`).toBeGreaterThan(box.height * 1.5);
  }

  /**
   * Args:
   *   page: Playwright page on the sign-in form; ends with the banner of a rejected sign-in.
   */
  async function failedSignIn(page) {
    await shown(LOGIN_EMAIL)(page);
    await page.locator(LOGIN_EMAIL).fill("design-showcase-unknown");
    await page.locator(LOGIN_PASSWORD).fill("not-a-real-password");
    await page.locator(LOGIN_SUBMIT).click();
    await shown(LOGIN_ERROR)(page);
  }

  function publicViews() {
    const url = `${base}/login`;
    return [
      { name: "sign-in", url, prepare: shown(LOGIN_EMAIL) },
      {
        name: "sign-in-focus",
        url,
        prepare: async (page) => {
          await shown(LOGIN_EMAIL)(page);
          await page.locator(LOGIN_EMAIL).focus();
        },
      },
      { name: "sign-in-error", url, prepare: failedSignIn },
      { name: "forgot-password", url: `${base}/login#forgot`, prepare: shown("#forgot_email") },
    ];
  }

  function deskViews() {
    const view = (name, route, ready) => ({
      name,
      url: `${base}/desk/${route}`,
      prepare: async (page) => {
        await deskBooted(page);
        await shown(ready)(page);
      },
    });
    const workspace = (name, route) => ({
      name,
      url: `${base}/desk/${route}`,
      prepare: async (page) => {
        await deskBooted(page);
        await shown(WORKSPACE_WIDGET)(page);
        await expect(page.locator(".workspace-skeleton")).toHaveCount(0);
      },
    });
    return [
      { name: "desktop", url: `${base}/desk`, prepare: shown(DESKTOP_READY) },
      workspace("workspace-stock", "stock"),
      workspace("workspace-selling", "selling"),
      view("user-list", "user", LIST_ROW),
      view("user-detail", "user/Administrator", FORM_READY),
      view("user-new", "user/new", FORM_READY),
      view("role-list", "role", LIST_ROW),
      view("todo-list", "todo", LIST_ROW),
      view("todo-new", "todo/new", FORM_READY),
      view("todo-report", "todo/view/report", PAGE_HEAD),
      view("item-list", "item", LIST_READY),
      view("item-new", "item/new", FORM_READY),
      view("sales-invoice-new", "sales-invoice/new", FORM_READY),
      view("system-settings", "system-settings", FORM_READY),
      view("website-settings", "website-settings", FORM_READY),
      view("permission-manager", "permission-manager", PAGE_HEAD),
      view("error-log-list", "error-log", LIST_READY),
      {
        name: "theme-switcher",
        url: `${base}/desk/user`,
        prepare: async (page) => {
          await deskBooted(page);
          await shown(LIST_ROW)(page);
          await themeDialogOpened(page);
        },
      },
    ];
  }

  function chosenThemeViews() {
    return [
      {
        name: "desktop-theme-dark",
        url: `${base}/desk`,
        prepare: async (page) => {
          await deskBooted(page);
          await switchTheme(page, "Dark");
          await gotoOnion(page, page.url());
          await deskBooted(page);
          await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
          await shown(DESKTOP_READY)(page);
        },
      },
    ];
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await openLogin(page);
    await assertDesignTokens(page, "erpnext");
  });

  test("design: the app links the theme file itself on the sign-in page and on the desk", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await openLogin(page);
    await expect(page.locator(THEME_LINK), "head_html of the Website Settings links the theme file").toHaveCount(1);
    const href = await page.locator(THEME_LINK).getAttribute("href");
    const served = await apiGetOnion(page.request, new URL(href, `${base}/`).toString());
    expect(served.status(), "the site serves the theme file from its public files").toBe(200);
    expect(await served.text(), "the theme file maps the app variables onto the tokens").toContain(
      "--bg-color: var(--design-surface-2)",
    );
    await signIn(page);
    await expect
      .poll(
        async () => {
          await gotoOnion(page, `${base}/desk/user`);
          return page.locator(THEME_LINK).getAttribute("href");
        },
        {
          message: "the desk must link the same version of the theme file once the site config cache expired",
          timeout: resolveTimeout(120_000),
          intervals: [10_000],
        },
      )
      .toBe(href);
  });

  test("design: the sign-in page takes surface, text and primary action from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openLogin(page);
      await assertToken(page, "body", "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, LOGIN_CARD, "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, LOGIN_EMAIL, "background-color", "--design-surface-2", `sign-in field ${mode}`);
      await assertToken(page, LOGIN_EMAIL, "color", "--design-text", `sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await page.locator(LOGIN_SUBMIT).hover();
      await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `hovered sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await openLogin(page);
    await assertLightAndDark(page, LOGIN_CARD, "erpnext sign-in");
    await assertReadable(
      page,
      [
        `${LOGIN_CARD} h4`,
        `${LOGIN_CARD} .page-card-subtitle`,
        `${LOGIN_CARD} label[for='login_email']`,
        `${LOGIN_CARD} a[href='#forgot']`,
        LOGIN_SUBMIT,
        { selector: `${LOGIN_CARD} .btn-login-option`, optional: true },
      ],
      "erpnext sign-in",
    );
  });

  test("design: the desk takes surfaces, text, dividers and primary action from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(300_000));
    await signIn(page);
    await seedShowcase(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openDesk(page, "todo", LIST_ROW);
      await expect(
        page.locator("html"),
        "an account on the automatic theme follows the browser",
      ).toHaveAttribute("data-theme", mode);
      await assertToken(page, "body", "background-color", "--design-surface-2", `desk ${mode}`);
      await assertToken(page, PAGE_HEAD, "background-color", "--design-surface-2", `page head ${mode}`);
      await assertToken(page, SIDEBAR, "background-color", "--design-surface-1", `sidebar ${mode}`);
      await assertToken(page, SIDEBAR, "border-right-color", "--design-border", `sidebar divider ${mode}`);
      await assertToken(
        page,
        SIDEBAR_SELECTED,
        "background-color",
        "--design-surface-active",
        `selected sidebar entry ${mode}`,
      );
      await assertToken(page, PAGE_TITLE, "color", "--design-text", `desk ${mode}`);
      await assertToken(page, LIST_HEAD, "background-color", "--design-surface-3", `list head ${mode}`);
      await assertToken(page, LIST_ROW, "border-bottom-color", "--design-border", `list row divider ${mode}`);
      await assertToken(page, PAGE_HEAD, "border-bottom-color", "--design-border", `page head divider ${mode}`);
      await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `primary action ${mode}`);
      await assertToken(page, PRIMARY_ICON, "stroke", "--design-on-primary", `primary action icon ${mode}`);
      await page.locator(PRIMARY_ACTION).hover();
      await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary-hover", `hovered ${mode}`);
      await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `hovered ${mode}`);
      await page.mouse.down();
      await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary-active", `pressed ${mode}`);
      await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `pressed ${mode}`);
      await page.locator(PAGE_TITLE).hover();
      await page.mouse.up();
      await page.locator(SIDEBAR_LINK_ENTRY).first().hover();
      await assertToken(page, SIDEBAR_HOVERED, "background-color", "--design-surface-hover", `hovered entry ${mode}`);
      await addRedAction(page);
      await assertToken(page, RED_PROBE, "background-color", "--design-danger", `destructive action ${mode}`);
      await assertToken(page, RED_PROBE, "color", "--design-on-danger", `destructive action ${mode}`);
      await openDesk(page, "permission-manager", CONTENT_RULE);
      await assertToken(page, CONTENT_RULE, "border-top-color", "--design-border", `content rule ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await openDesk(page, "todo", LIST_ROW);
    await assertLightAndDark(page, LIST_ROW, "erpnext desk");
    await assertReadable(
      page,
      [PAGE_TITLE, LIST_HEAD, LIST_ROW, PRIMARY_ACTION, SIDEBAR_ENTRY, `${SIDEBAR_SELECTED} .sidebar-item-label`],
      "erpnext desk",
    );
  });

  test("design: the rejected sign-in banner, the folder tile and the active filter take their fills from the palette", async ({
    page,
  }) => {
    shared.skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(240_000));
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/login`);
      await failedSignIn(page);
      await assertToken(page, LOGIN_ERROR, "background-color", "--design-danger-subtle", `rejected sign-in ${mode}`);
      await assertToken(page, LOGIN_ERROR_ICON, "color", "--design-danger", `rejected sign-in icon ${mode}`);
      await assertToken(page, LOGIN_ERROR_TITLE, "color", "--design-text", `rejected sign-in text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/desk`);
      await deskBooted(page);
      await shown(DESKTOP_READY)(page);
      if ((await page.locator(FOLDER_TILE).count()) > 0) {
        await assertToken(page, FOLDER_TILE, "background-color", "--design-surface-3", `folder tile ${mode}`);
      }
      await openDesk(page, "user", ACTIVE_FILTER);
      await assertToken(page, ACTIVE_FILTER, "background-color", "--design-surface-active", `active filter ${mode}`);
      await assertToken(page, ACTIVE_FILTER, "color", "--design-text", `active filter ${mode}`);
      await page.locator(ACTIVE_FILTER).hover();
      await assertToken(page, ACTIVE_FILTER, "background-color", "--design-surface-hover", `hovered filter ${mode}`);
    }
  });

  test("design: the native theme switch drives the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(240_000));
    await page.emulateMedia({ colorScheme: "light" });
    await signIn(page);
    await openDesk(page, "user", LIST_ROW);
    const root = page.locator("html");
    await expect(root, "on the automatic theme the palette follows the browser").not.toHaveAttribute(
      "data-design-theme",
      /.+/,
    );
    const light = await tokenValue(page, "--design-surface-2", "color");
    await themeDialogOpened(page);
    await assertToken(page, THEME_CARD, "background-color", "--design-surface-2", "theme tile light");
    await pickTheme(page, THEME_DARK);
    await expect(root).toHaveAttribute("data-theme", "dark");
    await expect(root).toHaveAttribute("data-design-theme", "dark");
    await expect(root, "the chosen dark theme hands images such as the lockup the dark color scheme").toHaveCSS(
      "color-scheme",
      "dark",
    );
    await assertToken(page, "body", "background-color", "--design-surface-2", "switched to dark");
    await assertToken(page, THEME_CARD, "background-color", "--design-surface-2", "theme tile dark");
    expect(await tokenValue(page, "--design-surface-2", "color"), "the dark palette must differ").not.toBe(light);
    await pickTheme(page, THEME_LIGHT);
    await expect(root).toHaveAttribute("data-theme", "light");
    await expect(root).toHaveAttribute("data-design-theme", "light");
    await expect(root).toHaveCSS("color-scheme", "light");
    expect(await tokenValue(page, "--design-surface-2", "color")).toBe(light);
    await pickTheme(page, THEME_AUTO);
    await expect(root).toHaveAttribute("data-theme", "light");
    await expect(root).not.toHaveAttribute("data-design-theme", /.+/);
  });

  test("design: sign-in page and desktop show the generated lockup, favicon and title", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    test.setTimeout(resolveTimeout(240_000));
    await openLogin(page);
    if (title) {
      const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      await expect(page, "the browser shows the configured title on the sign-in page").toHaveTitle(
        new RegExp(`^${escaped} - `),
      );
    }
    if (logoUrl) {
      await assertLockup(page, LOGIN_LOGO, logoUrl, "sign-in");
      expect(faviconUrl, "DESIGN_FAVICON_URL must accompany a configured logo").toBeTruthy();
      await expect(page.locator(FAVICON).first()).toHaveAttribute("href", faviconUrl);
      const lockup = await (await apiGetOnion(page.request, logoUrl)).text();
      if (title) {
        const xml = title.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        expect(lockup, "the visible lockup carries the configured title").toContain(`>${xml}</text>`);
      }
      const colors = {};
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        await openLogin(page);
        colors[mode] = {
          fill: toHex(await tokenValue(page, "--design-link", "color")),
          stroke: toHex(await tokenValue(page, "--design-surface-1", "color")),
        };
      }
      await page.emulateMedia({ colorScheme: null });
      const svg = lockup.toLowerCase();
      expect(svg, "the lockup text takes --design-link on --design-surface-1 in light mode").toContain(
        `fill="${colors.light.fill}" stroke="${colors.light.stroke}"`,
      );
      expect(svg, "the lockup text takes --design-link on --design-surface-1 in dark mode").toContain(
        `text{fill:${colors.dark.fill};stroke:${colors.dark.stroke}}`,
      );
    }
    await signIn(page);
    await gotoOnion(page, `${base}/desk`);
    await shown(DESKTOP_READY)(page);
    if (logoUrl) {
      await assertLockup(page, DESKTOP_LOGO, logoUrl, "desktop");
      await expect(page.locator(FAVICON).first()).toHaveAttribute("href", faviconUrl);
    }
    if (title) {
      const shell = await apiGetOnion(page.request, `${base}/desk`);
      expect(await shell.text(), "the desk shell carries the configured title").toContain(`<title>${title}</title>`);
    }
  });

  test("design: gallery of sign-in, desktop, workspaces, lists, forms and settings", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    const failures = [];
    try {
      await captureDesignGallery(page, publicViews());
    } catch (error) {
      failures.push(error.message);
    }
    await signIn(page);
    await seedShowcase(page);
    try {
      await captureDesignGallery(page, deskViews());
    } catch (error) {
      failures.push(error.message);
    }
    try {
      await captureDesignGallery(page, chosenThemeViews());
    } catch (error) {
      failures.push(error.message);
    }
    await openDesk(page, "user", LIST_ROW);
    await switchTheme(page, "Automatic");
    expect(failures, failures.join("\n")).toEqual([]);
  });

};
