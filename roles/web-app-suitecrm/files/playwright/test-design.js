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
const { samlLoginTo } = require("./saml-login");

const MODES = ["light", "dark"];
const READY = "#content";
const THEME_SHEET = "link[rel='stylesheet'][href*='cache/themes/suite8/css/Dawn/style.css']";
const SHOWCASE = "Design Showcase";
const PANEL = "#EditView .panel-default";
const PANEL_HEAD = `${PANEL} > .panel-heading`;
const PANEL_BODY = `${PANEL} > .panel-body`;
const LABEL = `${PANEL_BODY} .label`;
const FIELD = `${PANEL_BODY} input#name`;
const FIELD_RULE = `${PANEL_BODY} .edit-view-row-item .edit-dotted-border`;
const COLUMN_RULE = `${PANEL_BODY} .edit-view-bordered`;
const CHECKBOX = "#EditView input[type='checkbox']";
const SELECT = "#EditView .edit-view-field select";
const SAVE = "#EditView #SAVE";
const CALENDAR_USER_BAND = ".monthCalBody";
const CALENDAR_USER = `${CALENDAR_USER_BAND} h5.calSharedUser`;
const CALENDAR_DAY = ".fc th.fc-day-header a";
const DASHLET = "#pageContainer .dashletcontainer .dashletPanel";
const DASHLET_HEAD = `${DASHLET} .hd`;
const DASHLET_BAR = "#pageContainer .dashletcontainer .pagination td";
const DASHLET_TITLE = `${DASHLET} .header-title`;
const LIST = "table.list.view";
const LIST_ROW = `${LIST} tr.oddListRowS1, ${LIST} tr.evenListRowS1`;
const LIST_HEAD = `${LIST} tr th`;
const LIST_CELL = `${LIST} tr.oddListRowS1 td`;
const LIST_LINK = `${LIST} tr.oddListRowS1 td[scope='row'] a, ${LIST} tr.oddListRowS1 td a[href*='DetailView']`;
const LIST_BAR = `${LIST} .paginationActionButtons`;
const SHELL_NAVBAR = "scrm-base-navbar nav.navbar";
const SHELL_FRAME = ".classic-view-container iframe";
const SHELL_TABLE = ".list-view scrm-table";
const SHELL_RECORD = ".record-view";
const SHELL_ADMIN_CARD = ".admin-view scrm-admin-card";
const SHELL_USER_TOGGLE = ".global-links .dropdown-toggle";
const SHELL_USER_MENU = ".dropdown-menu.global-links-dropdown";
const SHELL_MODULE = `${SHELL_NAVBAR} li.top-nav.dropdown`;
const SHELL_MODULE_MENU = `${SHELL_NAVBAR} .dropdown-menu.submenu`;
const SHELL_BAR = ".list-view-tableactions";
const SHELL_TOGGLER = "scrm-base-navbar button.navbar-toggler";
const SHELL_SIDEBAR = ".p-sidebar";
const SHELL_NAV_LINK = `${SHELL_NAVBAR} li.top-nav .nav-link`;
const SHELL_ROW_LINK = `${SHELL_TABLE} scrm-field a.field-link`;
const SHELL_FOOTER = "scrm-footer-ui .footer";
const SHELL_LIST_LOADED = `${SHELL_TABLE} a.field-link, ${SHELL_TABLE} :text("No results found")`;

exports.register = function () {
  const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
  const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
  const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
  const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
  const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
  const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");

  function legacy(route) {
    return `${base}/legacy/index.php?${route}`;
  }

  function shown(selector) {
    return async (page) => {
      await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    };
  }

  async function open(page, route, ready = READY) {
    await gotoOnion(page, legacy(route));
    await shown(ready)(page);
  }

  async function signIn(page) {
    const status = await samlLoginTo(page, base, adminUsername, adminPassword, legacy("module=Home&action=index"));
    expect(status.active, "the administrator owns a SuiteCRM session").toBe(true);
  }

  /**
   * Args:
   *   page: signed-in Playwright page.
   *
   * Returns:
   *   The record id of the showcase account, created on the first call.
   */
  async function showcaseAccount(page) {
    await open(page, `module=Accounts&action=index&query=true&name_basic=${encodeURIComponent(SHOWCASE)}`);
    const link = page.locator(LIST_LINK, { hasText: SHOWCASE }).first();
    if (!(await link.isVisible())) {
      await open(page, "module=Accounts&action=EditView", FIELD);
      await page.locator("#EditView input#name").fill(SHOWCASE);
      await page.locator(SAVE).first().click();
      await expect(page, "saving the account opens its detail view").toHaveURL(/record=/, {
        timeout: resolveTimeout(30_000),
      });
      return new URL(page.url()).searchParams.get("record");
    }
    return new URL(await link.evaluate((element) => element.href)).searchParams.get("record");
  }

  /**
   * Args:
   *   page: signed-in Playwright page; the showcase account exists.
   *
   * Returns:
   *   The hash route of the showcase account's record view in the shell.
   */
  async function shellRecord(page) {
    await gotoOnion(page, `${base}/#/accounts`);
    const link = page.locator(`${SHELL_TABLE} a[href*='/record/']`, { hasText: SHOWCASE }).first();
    await expect(link).toBeVisible({ timeout: resolveTimeout(10_000) });
    return (await link.getAttribute("href")).replace(/^.*#/, "#");
  }

  /**
   * Args:
   *   page: Playwright page that shows an opened menu once its animation ended.
   *   selector: selector of the menu panel.
   */
  async function settled(page, selector) {
    await shown(selector)(page);
    await expect
      .poll(() =>
        page
          .locator(selector)
          .first()
          .evaluate((el) => el.getAnimations().length === 0 && getComputedStyle(el).opacity === "1"),
      )
      .toBe(true);
  }

  async function openUserMenu(page) {
    await shown(SHELL_TABLE)(page);
    if (!(await page.locator(SHELL_USER_MENU).first().isVisible())) {
      await page.locator(`${SHELL_USER_TOGGLE}:visible`).first().click();
    }
    await settled(page, SHELL_USER_MENU);
  }

  async function openModuleMenu(page) {
    await shown(SHELL_TABLE)(page);
    const toggler = page.locator(`${SHELL_TOGGLER}:visible`).first();
    if (await toggler.isVisible()) {
      if (!(await page.locator(SHELL_SIDEBAR).first().isVisible())) await toggler.click();
      await settled(page, SHELL_SIDEBAR);
      return;
    }
    await page.locator(`${SHELL_MODULE}:visible`).first().hover();
    await settled(page, SHELL_MODULE_MENU);
  }

  async function shellHome(page) {
    await gotoOnion(page, "about:blank");
    await gotoOnion(page, `${base}/?view=home#/home`);
    await shown(SHELL_FRAME)(page);
    await expect(page.frameLocator(SHELL_FRAME).locator("table.dashletPanel").first()).toBeVisible({
      timeout: resolveTimeout(10_000),
    });
  }

  async function openShell(page, hash, ready) {
    await gotoOnion(page, `${base}/?view=design#${hash}`);
    await shown(ready)(page);
  }

  test("design: the shell takes frame, bars, rows, links and menus from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await showcaseAccount(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openShell(page, "/accounts", SHELL_ROW_LINK);
      await assertToken(page, SHELL_NAVBAR, "background-color", "--design-frame", `navigation bar ${mode}`);
      await assertToken(page, SHELL_NAV_LINK, "color", "--design-on-frame", `navigation entry ${mode}`);
      await assertToken(page, SHELL_BAR, "background-color", "--design-surface-3", `list bar ${mode}`);
      await assertToken(page, SHELL_ROW_LINK, "color", "--design-link", `row link ${mode}`);
      await assertToken(page, SHELL_FOOTER, "background-color", "--design-surface-3", `footer ${mode}`);
      await openUserMenu(page);
      await assertToken(page, SHELL_USER_MENU, "background-color", "--design-surface-2", `user menu ${mode}`);
      await assertToken(page, `${SHELL_USER_MENU} a`, "color", "--design-text", `user menu entry ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await openShell(page, "/accounts", SHELL_ROW_LINK);
    await assertLightAndDark(page, SHELL_ROW_LINK, "shell list");
    await assertReadable(page, [SHELL_ROW_LINK, `${SHELL_TABLE} th`], "shell list");
  });

  test("design: the shell administration overview takes surfaces and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openShell(page, "/administration", SHELL_ADMIN_CARD);
      await assertToken(page, ".admin-view", "background-color", "--design-surface-1", `administration ${mode}`);
      await assertToken(page, `${SHELL_ADMIN_CARD} .admin-card-title`, "color", "--design-text", `card title ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await openShell(page, "/administration", SHELL_ADMIN_CARD);
    await assertReadable(page, [`${SHELL_ADMIN_CARD} .admin-card-title`, `${SHELL_ADMIN_CARD} a`], "administration");
  });

  test("design: every focus stop inside the shell navigation bar draws its indicator in the on-frame tone", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await openShell(page, "/accounts", SHELL_ROW_LINK);
    const onFrame = await tokenValue(page, "--design-on-frame", "color");
    const link = await tokenValue(page, "--design-link", "color");
    await page.locator(`${SHELL_NAVBAR} a:visible`).first().focus();
    for (let index = 0; index < 12; index += 1) {
      const indicator = await page.evaluate((navbar) => {
        const el = document.activeElement;
        const style = getComputedStyle(el);
        return {
          inside: Boolean(el.closest(navbar)),
          surface: Boolean(el.closest(".search-focused")),
          classes: String(el.className),
          color: style.outlineColor,
          line: style.outlineStyle,
        };
      }, SHELL_NAVBAR);
      if (!indicator.inside) break;
      expect(
        { color: indicator.color, line: indicator.line },
        `navigation focus stop ${index} (${indicator.classes}) draws its outline in the tone of the surface it sits on`,
      ).toEqual({ color: indicator.surface ? link : onFrame, line: "solid" });
      await page.keyboard.press("Tab");
    }
  });

  test("design: the calendar head reads in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await open(page, "module=Calendar&action=index", CALENDAR_DAY);
      await assertToken(page, CALENDAR_USER_BAND, "background-color", "--design-surface-3", `user band ${mode}`);
      await assertToken(page, CALENDAR_USER, "color", "--design-text", `user band ${mode}`);
      await assertToken(page, CALENDAR_DAY, "color", "--design-text", `weekday ${mode}`);
      await assertToken(page, ".fc .fc-divider", "background-color", "--design-border", `all-day divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await open(page, "module=Calendar&action=index", CALENDAR_DAY);
    await assertReadable(page, [CALENDAR_DAY, CALENDAR_USER, ".monthHeader"], "calendar");
  });

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await open(page, "module=Accounts&action=EditView", FIELD);
    await assertDesignTokens(page, "SuiteCRM legacy page");
  });

  test("design: the palette rides in the app's own custom theme sheet", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await open(page, "module=Accounts&action=EditView", FIELD);
    const href = await page.locator(THEME_SHEET).first().getAttribute("href");
    const served = await apiGetOnion(page.request, new URL(href, page.url()).toString());
    expect(served.status(), "the app serves its cached theme sheet").toBe(200);
    expect(await served.text(), "the cached theme sheet carries the token mapping of the custom theme sheet").toContain(
      "var(--design-surface-2)",
    );
  });

  test("design: forms take surfaces, panel heads, labels, dividers and the primary action from the palette", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await open(page, "module=Accounts&action=EditView", FIELD);
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, PANEL, "background-color", "--design-surface-2", `panel ${mode}`);
      await assertToken(page, PANEL_HEAD, "background-color", "--design-surface-3", `panel head ${mode}`);
      await assertToken(page, `${PANEL_HEAD} a`, "color", "--design-text", `panel head ${mode}`);
      await assertToken(page, LABEL, "color", "--design-text", `field label ${mode}`);
      await assertToken(page, FIELD, "border-top-color", "--design-border-strong", `field ${mode}`);
      await assertToken(page, COLUMN_RULE, "border-right-color", "--design-border", `column divider ${mode}`);
      const border = await tokenValue(page, "--design-border", "color");
      expect(
        await page.locator(FIELD_RULE).first().evaluate((element) => getComputedStyle(element).backgroundImage),
        `field divider ${mode}: the dotted rule is drawn in --design-border`,
      ).toContain(border);
      await assertToken(page, CHECKBOX, "accent-color", "--design-primary", `checkbox ${mode}`);
      await expect(page.locator(CHECKBOX).first(), `the checkbox draws no upstream sprite in ${mode} mode`).toHaveCSS(
        "background-image",
        "none",
      );
      await expect(page.locator(SELECT).first(), `selects draw no upstream arrow image in ${mode} mode`).toHaveCSS(
        "background-image",
        "none",
      );
      await assertToken(page, SAVE, "background-color", "--design-primary", `save ${mode}`);
      await assertToken(page, SAVE, "color", "--design-on-primary", `save ${mode}`);
      await page.locator(SAVE).first().hover();
      await assertToken(page, SAVE, "background-color", "--design-primary-hover", `hovered save ${mode}`);
      await assertToken(page, SAVE, "color", "--design-on-primary", `hovered save ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await open(page, "module=Accounts&action=EditView", FIELD);
    await assertLightAndDark(page, PANEL_BODY, "account form");
    await assertReadable(page, [LABEL, `${PANEL_HEAD} a`, SAVE, ".moduleTitle h2"], "account form");
  });

  test("design: lists keep large bars neutral and take rows and links from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await showcaseAccount(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await open(page, "module=Accounts&action=index", LIST_ROW);
      await assertToken(page, LIST_BAR, "background-color", "--design-surface-3", `pagination bar ${mode}`);
      await assertToken(page, LIST_CELL, "background-color", "--design-surface-2", `list row ${mode}`);
      await assertToken(page, LIST_CELL, "color", "--design-text", `list row ${mode}`);
      await assertToken(page, LIST_LINK, "color", "--design-link", `row link ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await open(page, "module=Accounts&action=index", LIST_ROW);
    await assertLightAndDark(page, LIST_CELL, "account list");
    await assertReadable(page, [LIST_LINK, LIST_HEAD, `${LIST_BAR} .pageNumbers, ${LIST} .pageNumbers`], "account list");
  });

  test("design: dashlets keep head and pagination bars neutral", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await open(page, "module=Home&action=index", DASHLET_HEAD);
      await assertToken(page, DASHLET_HEAD, "background-color", "--design-surface-3", `dashlet head ${mode}`);
      await assertToken(page, DASHLET_TITLE, "color", "--design-text", `dashlet title ${mode}`);
      await assertToken(page, DASHLET_BAR, "background-color", "--design-surface-3", `dashlet pagination ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await open(page, "module=Home&action=index", DASHLET_HEAD);
    await assertLightAndDark(page, DASHLET_TITLE, "dashlet");
    await assertReadable(page, [DASHLET_TITLE, `${DASHLET} table.list tr th`], "dashlet");
  });

  test("design: system name, logo and favicons are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!title && !logoUrl, "logo and title replacement are disabled for this role");
    await signIn(page);
    if (title) {
      await open(page, "module=Configurator&action=EditView", "input[name='system_name']");
      await expect(page.locator("input[name='system_name']"), "the system name the shell shows as title").toHaveValue(title);
    }
    if (logoUrl) {
      const expected = async (url) => (await apiGetOnion(page.request, url)).body();
      const served = async (path) => {
        const response = await apiGetOnion(page.request, `${base}/${path}`);
        expect(response.status(), `${path} is served`).toBe(200);
        return response.body();
      };
      const logo = await expected(logoUrl);
      const favicon = await expected(faviconUrl);
      expect(
        Buffer.compare(await served("legacy/custom/themes/default/images/company_logo.png"), logo),
        "the company logo is the generated lockup",
      ).toBe(0);
      expect(
        Buffer.compare(await served("dist/themes/suite8/images/favicon.ico"), favicon),
        "the shell favicon is the generated icon",
      ).toBe(0);
      await open(page, "module=Accounts&action=EditView", FIELD);
      const icon = await page.locator("link[rel~='icon']").first().getAttribute("href");
      const legacyIcon = await apiGetOnion(page.request, new URL(icon, page.url()).toString());
      expect(Buffer.compare(await legacyIcon.body(), favicon), "the legacy favicon is the generated icon").toBe(0);
    }
  });

  test("design: gallery of dashboard, lists, records, forms and administration", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_500_000));
    await signIn(page);
    await showcaseAccount(page);
    const record = await shellRecord(page);
    const view = (name, route, ready = READY) => ({ name, url: legacy(route), prepare: shown(ready) });
    const shellView = (name, hash, ready) => ({ name, url: `${base}/${hash}`, prepare: shown(ready) });
    await captureDesignGallery(page, [
      { name: "shell-home", url: `${base}/#/home`, prepare: shellHome },
      shellView("shell-accounts-list", "#/accounts", SHELL_TABLE),
      shellView("shell-accounts-record", record, SHELL_RECORD),
      shellView("shell-accounts-create", "#/accounts/edit", SHELL_RECORD),
      shellView("shell-contacts-list", "#/contacts", SHELL_LIST_LOADED),
      shellView("shell-administration", "#/administration", SHELL_ADMIN_CARD),
      { name: "shell-module-menu-open", url: `${base}/?view=module-menu#/accounts`, prepare: openModuleMenu },
      { name: "shell-user-menu-open", url: `${base}/?view=user-menu#/accounts`, prepare: openUserMenu },
      view("home-dashboard", "module=Home&action=index", ".dashletPanel"),
      view("accounts-list", "module=Accounts&action=index", LIST_ROW),
      view("accounts-create", "module=Accounts&action=EditView", FIELD),
      {
        name: "accounts-create-focus",
        url: legacy("module=Accounts&action=EditView"),
        prepare: async (target) => {
          await shown(FIELD)(target);
          await target.locator(FIELD).focus();
        },
      },
      view("contacts-list", "module=Contacts&action=index"),
      view("leads-create", "module=Leads&action=EditView"),
      view("opportunities-list", "module=Opportunities&action=index"),
      view("cases-create", "module=Cases&action=EditView", FIELD),
      view("calendar", "module=Calendar&action=index"),
      view("meetings-create", "module=Meetings&action=EditView", FIELD),
      view("tasks-list", "module=Tasks&action=index"),
      view("reports-list", "module=AOR_Reports&action=index"),
      view("projects-list", "module=Project&action=index"),
      view("administration", "module=Administration&action=index"),
      view("admin-users", "module=Users&action=index"),
      view("admin-user-profile", "module=Users&action=DetailView&record=1"),
      view("admin-user-edit", "module=Users&action=EditView&record=1"),
      view("admin-system-settings", "module=Configurator&action=EditView", "input[name='system_name']"),
      view("admin-security-groups", "module=SecurityGroups&action=index"),
      view("admin-roles", "module=ACLRoles&action=index"),
      view("employees-list", "module=Employees&action=index"),
      view("admin-currencies", "module=Currencies&action=index"),
      view("admin-schedulers", "module=Schedulers&action=index"),
    ]);
  });
};
