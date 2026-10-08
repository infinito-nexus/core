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
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const logoEnabled = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_ENABLED || "") === "true";

const MODES = ["light", "dark"];
const THEME_URL = "/_custom/infinito/design";
const LOGIN_FORM = "form.oe_login_form";
const LOGIN_FIELD = `${LOGIN_FORM} input[name="login"]`;
const LOGIN_SUBMIT = `${LOGIN_FORM} button[type="submit"].btn-primary`;
const LOGIN_ERROR = `${LOGIN_FORM} .alert-danger`;
const SITE_HEADER = "#wrapwrap > header .navbar.d-lg-block";
const SITE_LOGO = "#wrapwrap > header .navbar-brand img:visible";
const SITE_FOOTER = "#wrapwrap > footer";
const NAVBAR = ".o_main_navbar";
const APPS_TOGGLE = `${NAVBAR} .o_menu_toggle, ${NAVBAR} .o_navbar_apps_menu button`;
const ACTION = ".o_action_manager";
const CONTROL_PANEL = `${ACTION} .o_control_panel`;
const PRIMARY_ACTION = `${CONTROL_PANEL} .btn-primary`;
const KANBAN_RECORD = `${ACTION} .o_kanban_renderer .o_kanban_record`;
const LIST_ROW = `${ACTION} .o_list_renderer .o_data_row`;
const LIST_CELL = `${LIST_ROW} td.o_data_cell`;
const LIST_HEAD = `${ACTION} .o_list_renderer thead th`;
const SELECTED_CELL = `${ACTION} .o_list_renderer .o_data_row_selected td.o_data_cell`;
const SEARCH_BOX = `${CONTROL_PANEL} .o_searchview`;
const BREADCRUMB = `${CONTROL_PANEL} .breadcrumb`;
const FORM_LABEL = `${ACTION} .o_form_view .o_form_label`;
const PALETTE = ".o_command_palette";
const PALETTE_FOCUSED = `${PALETTE} .o_command.focused`;
const SITE_EDIT = `${NAVBAR} .o-website-btn-custo-primary`;
const SITE_NEW = `${NAVBAR} .o-website-btn-custo-secondary`;
const LIST_OR_KANBAN = `${LIST_ROW}, ${KANBAN_RECORD}`;
const LIST_READY = `${ACTION} .o_list_renderer, ${ACTION} .o_kanban_renderer, ${ACTION} .o_view_nocontent`;
const FORM_SHEET = `${ACTION} .o_form_view .o_form_sheet`;
const ACTION_MENU = `${CONTROL_PANEL} .o_cp_action_menus button`;
const MENU = ".o-overlay-container .o-dropdown--menu";
const DIALOG = ".o-overlay-container .modal-dialog .modal-content";
const SHOWCASE = "Design showcase";

exports.register = function (shared) {
  const base = shared.baseUrl();

  function shown(selector) {
    return async (page) => {
      await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(120_000) });
    };
  }

  /**
   * Args:
   *   page: Playwright page that shows an opened overlay once its animation ended.
   *   selector: selector of the overlay panel.
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

  /**
   * Args:
   *   page: signed-in Playwright page on a backend route.
   *   model: model name.
   *   method: ORM method.
   *   args: positional arguments.
   *
   * Returns:
   *   The `result` of the JSON-RPC answer.
   */
  async function rpc(page, model, method, args) {
    return page.evaluate(
      async ([m, f, a]) => {
        const response = await fetch(`/web/dataset/call_kw/${m}/${f}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { model: m, method: f, args: a, kwargs: {} } }),
        });
        const answer = await response.json();
        if (answer.error) throw new Error(answer.error.data ? answer.error.data.message : answer.error.message);
        return answer.result;
      },
      [model, method, args],
    );
  }

  /**
   * Args:
   *   page: signed-in Playwright page on a backend route.
   *   model: model whose showcase record is ensured.
   *   values: values of the record; `name` identifies it.
   *
   * Returns:
   *   The id of the record.
   */
  async function seed(page, model, values) {
    const found = await rpc(page, model, "search", [[["name", "=", values.name]]]);
    if (found.length > 0) return found[0];
    const created = await rpc(page, model, "create", [[values]]);
    return created[0];
  }

  async function seedShowcase(page) {
    return {
      partner: await seed(page, "res.partner", { name: SHOWCASE, email: "design-showcase@example.org" }),
      lead: await seed(page, "crm.lead", { name: SHOWCASE, type: "opportunity" }),
      project: await seed(page, "project.project", { name: SHOWCASE }),
    };
  }

  /**
   * Args:
   *   page: signed-in Playwright page on a backend route.
   *   enabled: whether the onboarding tours of the signed-in account run.
   *
   * Returns:
   *   The value the account had before.
   */
  async function setTours(page, enabled) {
    const { uid } = await rpc(page, "res.users", "context_get", []);
    const [user] = await rpc(page, "res.users", "read", [[uid], ["tour_enabled"]]);
    if (user.tour_enabled !== enabled) await rpc(page, "res.users", "write", [[uid], { tour_enabled: enabled }]);
    return user.tour_enabled;
  }

  async function openBackend(page, route, ready) {
    await gotoOnion(page, `${base}/odoo/${route}`);
    await shown(ready)(page);
  }

  /**
   * Args:
   *   browser: Playwright browser.
   *   body: receives the signed-in page. The onboarding tours of the account are off while it runs, because their pointer covers the first control of a view and takes its hover; the previous value is written back afterwards.
   */
  async function signedIn(browser, body) {
    const { context, page } = await shared.authenticatedContext(browser);
    let tours = false;
    try {
      await openBackend(page, "contacts", LIST_OR_KANBAN);
      tours = await setTours(page, false);
      await body(page);
    } finally {
      if (tours) await setTours(page, true).catch(() => {});
      await context.close();
    }
  }

  async function openLogin(page) {
    await gotoOnion(page, `${base}/web/login`);
    await shown(`${LOGIN_FIELD}, .o_login_auth`)(page);
  }

  async function openActionMenu(page) {
    await shown(FORM_SHEET)(page);
    await page.locator(ACTION_MENU).first().click();
    await settled(page, MENU);
  }

  /**
   * Args:
   *   page: Playwright page that links the bundle.
   *   link: name of the bundle in the stylesheet link of the page.
   *   bundle: asset bundle the design appends its sheet to.
   *   mapping: declaration the sheet must carry.
   */
  async function assertBundle(page, link, bundle, mapping) {
    const href = await page.locator(`link[rel="stylesheet"][href*="/${link}."]`).first().getAttribute("href");
    const served = await apiGetOnion(page.request, new URL(href, `${base}/`).toString());
    expect(served.status(), `${link}: the app serves its compiled bundle`).toBe(200);
    const text = await served.text();
    expect(text, `${link}: the bundle carries the theme sheet of the design`).toContain(`${THEME_URL}/${bundle}.css`);
    expect(text, `${link}: the theme sheet maps the app variables onto the tokens`).toContain(mapping);
  }

  function publicViews() {
    const login = `${base}/web/login`;
    const views = [
      { name: "website-home", url: `${base}/`, prepare: shown(SITE_FOOTER) },
      { name: "sign-in", url: login, prepare: shown(`${LOGIN_FIELD}, .o_login_auth`) },
      { name: "contact-us", url: `${base}/contactus`, prepare: shown("#wrapwrap main form") },
      { name: "not-found", url: `${base}/design-showcase-missing`, prepare: shown("#wrapwrap main") },
    ];
    if (!isServiceEnabled("sso")) {
      views.push(
        {
          name: "sign-in-focus",
          url: login,
          prepare: async (page) => {
            await shown(LOGIN_FIELD)(page);
            await page.locator(LOGIN_FIELD).focus();
          },
        },
        {
          name: "sign-in-error",
          url: login,
          prepare: async (page) => {
            await shown(LOGIN_FIELD)(page);
            await page.locator(LOGIN_FIELD).fill("design-showcase-unknown");
            await page.locator(`${LOGIN_FORM} input[name="password"]`).fill("not-a-real-password");
            await page.locator(LOGIN_SUBMIT).click();
            await shown(LOGIN_ERROR)(page);
          },
        },
        { name: "reset-password", url: `${base}/web/reset_password`, prepare: shown("form.oe_reset_password_form") },
      );
    }
    return views;
  }

  function signedInViews(ids) {
    const backend = (name, route, ready) => ({ name, url: `${base}/odoo/${route}`, prepare: shown(ready) });
    const contact = `${base}/odoo/contacts/${ids.partner}`;
    return [
      { name: "portal-home", url: `${base}/my`, prepare: shown("#wrapwrap main") },
      { name: "portal-account", url: `${base}/my/account`, prepare: shown("#wrapwrap main form") },
      { name: "portal-security", url: `${base}/my/security`, prepare: shown("#wrapwrap main form") },
      backend("discuss", "discuss", `${ACTION} .o-mail-Discuss`),
      backend("contacts-list", "contacts", LIST_OR_KANBAN),
      backend("contacts-kanban", "contacts?view_type=kanban", KANBAN_RECORD),
      {
        name: "contacts-row-selected",
        url: `${base}/odoo/contacts`,
        prepare: async (page) => {
          await shown(LIST_OR_KANBAN)(page);
          const box = page.locator(`${LIST_ROW} .o_list_record_selector input`).first();
          if (await box.isVisible()) await box.check();
          else await page.locator(KANBAN_RECORD).first().hover();
        },
      },
      backend("contact-detail", `contacts/${ids.partner}`, FORM_SHEET),
      {
        name: "contact-new-focus",
        url: `${base}/odoo/contacts/new`,
        prepare: async (page) => {
          await shown(FORM_SHEET)(page);
          await page.locator(`${FORM_SHEET} input.o_input`).first().focus();
        },
      },
      { name: "contact-action-menu", url: contact, prepare: openActionMenu },
      {
        name: "contact-delete-dialog",
        url: contact,
        prepare: async (page) => {
          await openActionMenu(page);
          await page.locator(`${MENU} .dropdown-item`).filter({ hasText: "Delete" }).first().click();
          await settled(page, DIALOG);
        },
      },
      backend("crm-pipeline", "crm", KANBAN_RECORD),
      backend("crm-lead-detail", `crm/${ids.lead}`, FORM_SHEET),
      backend("sales-quotations", "sales", LIST_READY),
      backend("invoices-list", "invoicing", LIST_READY),
      backend("inventory-overview", "inventory", KANBAN_RECORD),
      backend("project-kanban", "project", KANBAN_RECORD),
      backend("settings-general", "settings", `${ACTION} .o_form_view .settings`),
      backend("users-list", "users", LIST_OR_KANBAN),
      backend("user-detail", "users/2", FORM_SHEET),
      backend("companies-list", "companies", LIST_OR_KANBAN),
      backend("apps-list", "apps", KANBAN_RECORD),
      {
        name: "website-preview",
        url: `${base}/odoo/website`,
        prepare: async (page) => {
          await shown(`${NAVBAR} .o_website_publish_container`)(page);
          await expect
            .poll(
              async () => {
                const framed = page.frames().filter((frame) => frame !== page.mainFrame());
                const loaded = await Promise.all(
                  framed.map((frame) =>
                    frame
                      .locator(SITE_FOOTER)
                      .first()
                      .isVisible()
                      .catch(() => false),
                  ),
                );
                return loaded.includes(true);
              },
              { message: "the preview frame shows the website", timeout: resolveTimeout(120_000) },
            )
            .toBe(true);
        },
      },
      {
        name: "apps-menu-open",
        url: `${base}/odoo/contacts`,
        prepare: async (page) => {
          await shown(LIST_OR_KANBAN)(page);
          await page.locator(APPS_TOGGLE).first().click();
          await settled(page, `${MENU}, .o_app_menu_sidebar`);
        },
      },
      {
        name: "user-menu-open",
        url: `${base}/odoo/contacts`,
        prepare: async (page) => {
          await shown(LIST_OR_KANBAN)(page);
          await page.locator(`${NAVBAR} .o_user_menu:visible, ${NAVBAR} .o_mobile_menu_toggle:visible`).first().click();
          await settled(page, `${MENU}, .o_burger_menu`);
        },
      },
      {
        name: "command-palette",
        url: `${base}/odoo/contacts`,
        prepare: async (page) => {
          await shown(LIST_OR_KANBAN)(page);
          await page.keyboard.press("Control+k");
          await settled(page, PALETTE);
        },
      },
    ];
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLogin(page);
    await assertDesignTokens(page, "odoo");
  });

  test("design: the app compiles the theme sheets into its own frontend and backend bundle", async ({
    page,
    browser,
  }) => {
    skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(300_000));
    await openLogin(page);
    await assertBundle(page, "web.assets_frontend", "web.assets_frontend", "--body-bg: var(--design-surface-2)");
    await signedIn(browser, async (admin) => {
      await assertBundle(admin, "web.assets_web", "web.assets_backend", "--body-bg: var(--design-surface-1)");
    });
  });

  test("design: the sign-in page takes surfaces, text and primary action from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(isServiceEnabled("sso"), "the native form stays hidden behind the provider list when sso is on");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openLogin(page);
      await shown(LOGIN_FIELD)(page);
      await assertToken(page, "body", "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, SITE_HEADER, "background-color", "--design-surface-2", `site header ${mode}`);
      await assertToken(page, SITE_FOOTER, "background-color", "--design-surface-1", `site footer ${mode}`);
      await assertToken(page, LOGIN_FIELD, "color", "--design-text", `sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await page.locator(LOGIN_SUBMIT).hover();
      await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `hovered sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await openLogin(page);
    await assertLightAndDark(page, LOGIN_FIELD, "odoo sign-in");
    await assertReadable(
      page,
      [`${LOGIN_FORM} label[for="login"]`, LOGIN_FIELD, LOGIN_SUBMIT, `${SITE_FOOTER} a`, `${SITE_HEADER} .nav-link`],
      "odoo sign-in",
    );
  });

  test("design: the backend takes frame, surfaces, text, dividers and primary action from the palette", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(600_000));
    await signedIn(browser, async (page) => {
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        await openBackend(page, "contacts", LIST_ROW);
        await assertToken(page, "body", "background-color", "--design-surface-1", `backend ${mode}`);
        await assertToken(page, NAVBAR, "background-color", "--design-frame", `navbar ${mode}`);
        await assertToken(page, APPS_TOGGLE, "color", "--design-on-frame", `navbar entry ${mode}`);
        await assertToken(page, CONTROL_PANEL, "background-color", "--design-surface-2", `control panel ${mode}`);
        await assertToken(page, SEARCH_BOX, "background-color", "--design-surface-2", `search box ${mode}`);
        await assertToken(page, LIST_HEAD, "background-color", "--design-surface-3", `list head ${mode}`);
        await assertToken(page, LIST_CELL, "background-color", "--design-surface-2", `list cell ${mode}`);
        await assertToken(page, LIST_CELL, "color", "--design-text", `list cell ${mode}`);
        await assertToken(page, LIST_ROW, "border-bottom-color", "--design-border", `list row divider ${mode}`);
        await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary", `primary action ${mode}`);
        await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `primary action ${mode}`);
        await page.locator(PRIMARY_ACTION).first().hover();
        await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary-hover", `hovered ${mode}`);
        await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `hovered ${mode}`);
        await page.mouse.down();
        await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary-active", `pressed ${mode}`);
        await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `pressed ${mode}`);
        await page.locator(`${CONTROL_PANEL} .o_breadcrumb`).first().hover();
        await page.mouse.up();
      }
      await page.emulateMedia({ colorScheme: null });
      await openBackend(page, "contacts", LIST_ROW);
      await assertLightAndDark(page, LIST_CELL, "odoo backend");
      await assertReadable(
        page,
        [LIST_CELL, PRIMARY_ACTION, `${CONTROL_PANEL} .o_breadcrumb`, `${NAVBAR} .o_menu_brand`, `${NAVBAR} .o_menu_sections .o_nav_entry`],
        "odoo backend",
      );
    });
  });

  test("design: selected rows, forms, the command palette, dialogs and the website buttons of the navbar follow the palette", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(600_000));
    await signedIn(browser, async (page) => {
      const ids = await seedShowcase(page);
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        await openBackend(page, "contacts", LIST_ROW);
        await page.locator(`${LIST_ROW} .o_list_record_selector input`).first().check();
        await assertToken(page, SELECTED_CELL, "background-color", "--design-surface-active", `selected row ${mode}`);
        await assertToken(page, SELECTED_CELL, "color", "--design-text", `selected row ${mode}`);
        await page.keyboard.press("Control+k");
        await settled(page, PALETTE);
        await assertToken(page, PALETTE, "background-color", "--design-surface-2", `command palette ${mode}`);
        await assertToken(page, PALETTE_FOCUSED, "background-color", "--design-surface-active", `focused command ${mode}`);
        await assertToken(page, PALETTE_FOCUSED, "color", "--design-text", `focused command ${mode}`);
        await openBackend(page, `contacts/${ids.partner}`, FORM_SHEET);
        await assertToken(page, FORM_SHEET, "background-color", "--design-surface-2", `form sheet ${mode}`);
        await assertToken(page, FORM_LABEL, "color", "--design-text", `form label ${mode}`);
        await assertToken(page, BREADCRUMB, "background-color", "--design-surface-2", `breadcrumb ${mode}`);
        await openActionMenu(page);
        await assertToken(page, MENU, "background-color", "--design-surface-2", `action menu ${mode}`);
        await page.locator(`${MENU} .dropdown-item`).filter({ hasText: "Delete" }).first().click();
        await settled(page, DIALOG);
        await assertToken(page, DIALOG, "background-color", "--design-surface-2", `dialog ${mode}`);
        await assertToken(page, `${DIALOG} .btn-danger`, "background-color", "--design-danger", `dialog ${mode}`);
        await assertToken(page, `${DIALOG} .btn-danger`, "color", "--design-on-danger", `dialog ${mode}`);
        await expect(page.locator(`${DIALOG} .btn-close`), `the close icon takes the text tone in ${mode} mode`).toHaveCSS(
          "filter",
          `brightness(0) invert(${mode === "dark" ? 1 : 0})`,
        );
        await openBackend(page, "website", SITE_EDIT);
        await assertToken(page, SITE_EDIT, "background-color", "--design-primary", `website edit button ${mode}`);
        await assertToken(page, SITE_EDIT, "color", "--design-on-primary", `website edit button ${mode}`);
        await assertToken(page, SITE_NEW, "background-color", "--design-frame-active", `website new button ${mode}`);
        await assertToken(page, SITE_NEW, "color", "--design-on-frame", `website new button ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
      await openBackend(page, `contacts/${ids.partner}`, FORM_SHEET);
      await assertReadable(
        page,
        [
          { selector: `${FORM_SHEET} .o_form_label.o_td_label`, optional: true },
          `${FORM_SHEET} .nav-link.active`,
          `${FORM_SHEET} .nav-link:not(.active)`,
        ],
        "odoo form",
      );
    });
  });

  test("design: every focus stop inside the navbar draws its indicator in the on-frame tone", async ({ browser }) => {
    skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(300_000));
    await signedIn(browser, async (page) => {
      await openBackend(page, "contacts", LIST_ROW);
      const expected = await tokenValue(page, "--design-on-frame", "color");
      const stops = page.locator(`${NAVBAR} a[href]:visible, ${NAVBAR} button:not([disabled]):visible`);
      const count = await stops.count();
      expect(count, "the navbar hosts focusable entries").toBeGreaterThan(2);
      await page.locator(APPS_TOGGLE).first().focus();
      await page.keyboard.press("Shift+Tab");
      for (let index = 0; index < count; index += 1) {
        await page.keyboard.press("Tab");
        const indicator = await page.evaluate((navbar) => {
          const el = document.activeElement;
          const style = getComputedStyle(el);
          return {
            inside: Boolean(el.closest(navbar)),
            visible: el.matches(":focus-visible"),
            classes: el.className,
            color: style.outlineColor,
            line: style.outlineStyle,
            width: parseFloat(style.outlineWidth),
          };
        }, NAVBAR);
        if (!indicator.inside) break;
        expect(indicator.visible, `navbar focus stop ${index} (${indicator.classes}) is reached by the keyboard`).toBe(true);
        expect(
          { color: indicator.color, line: indicator.line, wide: indicator.width >= 2 },
          `navbar focus stop ${index} (${indicator.classes}) draws its outline in --design-on-frame`,
        ).toEqual({ color: expected, line: "solid", wide: true });
      }
    });
  });

  test("design: website header, favicon and titles carry the configured logo and title", async ({ page, browser }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoEnabled && !title, "logo and title replacement are disabled for this role");
    test.setTimeout(resolveTimeout(300_000));
    await gotoOnion(page, `${base}/`);
    await shown(SITE_FOOTER)(page);
    if (title) {
      await expect(page, "website pages end with the configured title").toHaveTitle(
        new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
      );
    }
    let icon = "";
    if (logoEnabled) {
      const image = page.locator(SITE_LOGO).first();
      await expect(image, "the website header shows the logo of the website record").toBeVisible();
      await expect
        .poll(() => image.evaluate((element) => element.complete && element.naturalWidth > 0), {
          message: "the page must be allowed to load the logo",
        })
        .toBe(true);
      const natural = await image.evaluate((element) => element.naturalWidth / element.naturalHeight);
      expect(natural, "the stored logo is the generated lockup with the title next to the symbol").toBeGreaterThan(3);
      const box = await image.boundingBox();
      expect(box.width, "the rendered header logo is a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
      icon = (await page.locator('link[rel="shortcut icon"]').first().getAttribute("href")).replace(/\?.*$/, "");
      const served = await apiGetOnion(page.request, new URL(icon, `${base}/`).toString());
      expect(served.status(), "the app serves the favicon of the website record").toBe(200);
      expect(served.headers()["content-type"], "the favicon is an image").toMatch(/^image\//);
    }
    await signedIn(browser, async (admin) => {
      const shell = await (await apiGetOnion(admin.request, `${base}/odoo`)).text();
      if (title) expect(shell, "the backend shell carries the configured title").toContain(`<title>${title}</title>`);
      if (logoEnabled) expect(shell, "the backend shell links the favicon of the website record").toContain(`href="${icon}?`);
    });
  });

  test("design: gallery of website, sign-in, portal, lists, forms and settings", async ({ page, browser }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(3_600_000));
    const failures = [];
    try {
      await captureDesignGallery(page, publicViews());
    } catch (error) {
      failures.push(error.message);
    }
    await signedIn(browser, async (backend) => {
      const ids = await seedShowcase(backend);
      try {
        await captureDesignGallery(backend, signedInViews(ids));
      } catch (error) {
        failures.push(error.message);
      }
    });
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
