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
const { apiFetchOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const FOCUS_WALK_LIMIT = 40;
const APP = ".v-application";
const SIGN_IN_PAGE = ".auth";
const SIGN_IN_CARD = ".auth .v-card";
const USERNAME = "#auth-username";
const SUBMIT = '[data-testid="auth-signin"]';
const BRAND = ".auth .v-image__image";
const FRAME = ".NavDrawer";
const NAV_DASHBOARD = `${FRAME} [data-testid="sidebar-dashboard"]`;
const NAV_SELECTED = `${FRAME} [data-testid="sidebar-keys"]`;
const PROJECT_MENU = `${FRAME} [data-testid="sidebar-currentProject"]`;
const USER_MENU = `${FRAME} .v-navigation-drawer__append .v-list-item:has(.mdi-account)`;
const THEME_SWITCH = `${FRAME} .DarkModeSwitch .v-input--selection-controls__input`;
const MENU = ".menuable__content__active";
const DIALOG = ".v-dialog--active";
const TOOLBAR_TITLE = ".v-toolbar__title";
const TABLE = ".v-data-table";
const TABLE_HEAD = `${TABLE} > .v-data-table__wrapper > table > thead > tr:last-child > th`;
const TABLE_CELL = `${TABLE} > .v-data-table__wrapper > table > tbody > tr > td`;
const PRIMARY_ACTION = ".v-toolbar .v-btn.primary";
const EDITOR = ".CodeMirror";
const NAV_ICON = ".v-app-bar__nav-icon";
const OUTLINED_CHIP = `${DIALOG} .v-chip.v-chip--outlined.green`;
const SHOWCASE = "Design Showcase";

exports.register = function (shared) {
  const base = shared.env.semaphoreBaseUrl;

  /**
   * Args:
   *   page: Playwright page whose finite animations and transitions must have ended.
   */
  async function animationsSettled(page) {
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
                        .some(
                          (animation) =>
                            animation.playState === "running" &&
                            animation.effect?.getComputedTiming().iterations !== Infinity,
                        ),
                    ),
                  ),
                );
              }),
          ),
        { message: "every finite animation of the page must have ended" },
      )
      .toBe(false);
  }

  function shown(selector) {
    return async (page) => {
      await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
      await animationsSettled(page);
    };
  }

  /**
   * Args:
   *   page: Playwright page to open the sign-in form on.
   */
  async function openSignIn(page) {
    await gotoOnion(page, `${base}${shared.LOGIN_PATH}`);
    await shown(USERNAME)(page);
  }

  /**
   * Args:
   *   page: Playwright page that ends signed in as an administrator, through Keycloak when SSO is on and through the break-glass account otherwise.
   */
  async function signIn(page) {
    if (shared.env.oidcEnabled) {
      await shared.signInViaOidc(page, shared.env.adminUsername, shared.env.adminPassword, "design");
    } else {
      await shared.signInViaLocal(page, shared.env.breakglassUsername, shared.env.breakglassPassword, "design");
    }
  }

  /**
   * Args:
   *   page: signed-in Playwright page whose session cookie authorizes the call.
   *   method: HTTP verb.
   *   path: path below `/api`.
   *   data: JSON body for writing calls.
   *
   * Returns:
   *   The parsed JSON body, or null for an empty response.
   */
  async function api(page, method, path, data) {
    const response = await apiFetchOnion(page.request, `${base}/api${path}`, {
      method,
      data,
      timeout: resolveTimeout(30_000),
    });
    expect(response.ok(), `${method} /api${path} answered ${response.status()}`).toBe(true);
    const body = await response.text();
    return body ? JSON.parse(body) : null;
  }

  /**
   * Args:
   *   page: signed-in Playwright page.
   *   path: collection path below `/api`.
   *   name: value of the `name` field that identifies the showcase object.
   *   body: JSON body that creates it when it is missing.
   *
   * Returns:
   *   The existing or the created object.
   */
  async function ensure(page, path, name, body) {
    const existing = ((await api(page, "GET", path)) || []).find((item) => item.name === name);
    return existing || (await api(page, "POST", path, { name, ...body }));
  }

  /**
   * Args:
   *   page: signed-in Playwright page that seeds the showcase project the signed-in views show.
   *
   * Returns:
   *   The ids of the showcase project and its first template.
   */
  async function seedShowcase(page) {
    const project = await ensure(page, "/projects", SHOWCASE, {
      alert: false,
      max_parallel_tasks: 0,
      type: "",
      demo: true,
    });
    const scope = `/project/${project.id}`;
    const templates = await api(page, "GET", `${scope}/templates`);
    expect(templates.length, "the demo content of the showcase project carries templates").toBeGreaterThan(0);
    await ensure(page, `${scope}/schedules`, "showcase-schedule", {
      project_id: project.id,
      template_id: templates[0].id,
      cron_format: "0 3 * * 0",
      active: false,
    });
    await ensure(page, `${scope}/environment`, "showcase-variables", {
      project_id: project.id,
      json: "{}",
      env: "{}",
      secrets: [],
    });
    return { project: project.id, template: templates[0].id };
  }

  /**
   * Args:
   *   page: Playwright page that shows a project page; a drawer the viewport hides gets opened.
   */
  async function navigationOpened(page) {
    if (!(await page.locator(NAV_DASHBOARD).isVisible())) {
      await page.locator(NAV_ICON).first().click();
    }
    await shown(NAV_DASHBOARD)(page);
  }

  /**
   * Args:
   *   page: Playwright page that shows a project page and ends with the menu of one drawer entry open.
   *   trigger: selector of the drawer entry that opens the menu.
   */
  async function menuOpened(page, trigger) {
    await navigationOpened(page);
    await page.locator(trigger).click();
    await shown(MENU)(page);
    await expect(page.locator(MENU)).toHaveCSS("opacity", "1");
  }

  /**
   * Args:
   *   page: Playwright page whose focused element is inspected.
   *
   * Returns:
   *   The name of the focused element, whether the navigation drawer holds it, and the color its focus indicator is drawn in: its own outline, or for the hidden input of a switch the outline of the track.
   */
  async function focusStop(page) {
    return page.evaluate((frame) => {
      const element = document.activeElement;
      const drawn = element.matches('input[role="switch"]')
        ? element.closest(".v-input--switch").querySelector(".v-input--switch__track")
        : element;
      const style = getComputedStyle(drawn);
      return {
        name: [element.tagName.toLowerCase(), ...element.classList].join("."),
        framed: Boolean(element.closest(frame)),
        color: style.outlineStyle === "none" || parseFloat(style.outlineWidth) === 0 ? "none" : style.outlineColor,
      };
    }, FRAME);
  }

  /**
   * Args:
   *   page: Playwright page that shows the navigation drawer on a freshly loaded document; the keyboard walks forward through every stop of the drawer.
   *   mode: color scheme the failure messages name.
   */
  async function assertFrameFocus(page, mode) {
    const ring = await tokenValue(page, "--design-on-frame", "color");
    const stops = [];
    for (let step = 0; step < FOCUS_WALK_LIMIT; step += 1) {
      await page.keyboard.press("Tab");
      const stop = await focusStop(page);
      if (!stop.framed && stops.length > 0) {
        break;
      }
      if (stop.framed) {
        stops.push(stop.name);
        await expect
          .poll(async () => (await focusStop(page)).color, {
            message: `keyboard stop ${stop.name} of the navigation ${mode}: the focus indicator must be drawn in --design-on-frame`,
          })
          .toBe(ring);
      }
    }
    expect(stops.length, `the keyboard walk must find stops inside the navigation ${mode}`).toBeGreaterThan(3);
  }

  /**
   * Args:
   *   page: signed-in Playwright page; the colors the app writes as literals for hints, placeholders, neutral buttons and inset tables are compared with the tokens.
   *   seeded: ids of the showcase project and its first template.
   *   mode: color scheme the failure messages name.
   *   assert: comparison with the signature of `assertToken`.
   */
  async function assertLiteralColors(page, { project, template }, mode, assert = assertToken) {
    const scope = `${base}/project/${project}`;
    await gotoOnion(page, `${scope}/settings`);
    await shown('[data-testid="settings-deleteProject"]')(page);
    await assert(page, '[style*="color: rgb(255, 82, 82)"]', "color", "--design-danger", `danger hint ${mode}`);
    await gotoOnion(page, `${scope}/templates`);
    await shown(TABLE_CELL)(page);
    await assert(page, `${TABLE} [style*="color: gray"]`, "color", "--design-text-muted", `list hint ${mode}`);
    await gotoOnion(page, `${scope}/templates/${template}/tasks`);
    await shown('[data-testid="template-run"]')(page);
    await assert(page, ".v-btn.grey", "background-color", "--design-surface-3", `neutral button ${mode}`);
    await assert(page, ".v-btn.grey", "color", "--design-text", `neutral button ${mode}`);
    await assert(
      page,
      ".SingleLineEditable__content--placeholder",
      "color",
      "--design-text-muted",
      `placeholder ${mode}`,
    );
    await gotoOnion(page, `${scope}/environment`);
    await shown(TABLE_CELL)(page);
    await page.locator(PRIMARY_ACTION).first().click();
    await shown(`${DIALOG} .FieldTable`)(page);
    await assert(page, `${DIALOG} .FieldTable`, "background-color", "--design-surface-3", `inset table ${mode}`);
    await gotoOnion(page, `${scope}/keys`);
    await shown(TABLE_CELL)(page);
    await menuOpened(page, USER_MENU);
    await assert(page, `${MENU} .mdi-professional-hexagon`, "color", "--design-link", `upgrade hint ${mode}`);
    await page.locator(`${MENU} .v-list-item:has(.mdi-pencil)`).click();
    await shown(`${DIALOG} input`)(page);
    if ((await page.locator(OUTLINED_CHIP).count()) > 0) {
      await assert(page, OUTLINED_CHIP, "color", "--design-success", `outlined chip ${mode}`);
    }
  }

  /**
   * Args:
   *   page: Playwright page whose every document boots the app in the theme of the emulated color scheme, also when the injected design script is stripped.
   */
  async function nativeThemeFollowsScheme(page) {
    await page.addInitScript(() => {
      if (!window.location.protocol.startsWith("http")) return;
      if (window.localStorage.getItem("infinito.design.theme") === "explicit") return;
      if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
        window.localStorage.setItem("darkMode", "1");
      } else {
        window.localStorage.removeItem("darkMode");
      }
    });
  }

  function signInViews() {
    const url = `${base}${shared.LOGIN_PATH}`;
    return [
      { name: "sign-in", url, prepare: shown(USERNAME) },
      {
        name: "sign-in-focus",
        url,
        prepare: async (page) => {
          await shown(USERNAME)(page);
          await page.locator(USERNAME).focus();
          await animationsSettled(page);
        },
      },
      {
        name: "sign-in-error",
        url,
        prepare: async (page) => {
          await shown(USERNAME)(page);
          await page.locator(USERNAME).fill("design-showcase-unknown");
          await page.locator("#auth-password").fill("not-a-real-password");
          await page.locator(SUBMIT).click();
          await shown(`${SIGN_IN_PAGE} .v-alert`)(page);
        },
      },
    ];
  }

  function signedInViews({ project, template }) {
    const scope = `${base}/project/${project}`;
    const view = (name, url, selector) => ({ name, url, prepare: shown(selector) });
    const opened = (name, url, ready, trigger, panel) => ({
      name,
      url,
      prepare: async (page) => {
        await shown(ready)(page);
        await page.locator(trigger).first().click();
        await shown(panel)(page);
      },
    });
    return [
      view("dashboard-history", `${scope}/history`, TABLE),
      view("dashboard-activity", `${scope}/activity`, TABLE_CELL),
      view("project-settings", `${scope}/settings`, '[data-testid="settings-deleteProject"]'),
      view("templates", `${scope}/templates`, `${TABLE} tbody tr a`),
      view("template-tasks", `${scope}/templates/${template}/tasks`, '[data-testid="template-run"]'),
      opened(
        "template-run-dialog",
        `${scope}/templates/${template}/tasks`,
        '[data-testid="template-run"]',
        '[data-testid="template-run"]',
        DIALOG,
      ),
      view("schedule", `${scope}/schedule`, TABLE_CELL),
      view("inventory", `${scope}/inventory`, TABLE_CELL),
      opened("inventory-new", `${scope}/inventory`, TABLE_CELL, PRIMARY_ACTION, `${DIALOG}, ${MENU}`),
      view("variable-groups", `${scope}/environment`, TABLE_CELL),
      {
        name: "variable-group-new",
        url: `${scope}/environment`,
        prepare: async (page) => {
          await shown(TABLE_CELL)(page);
          await page.locator(PRIMARY_ACTION).first().click();
          await shown(DIALOG)(page);
          await page.locator(`${DIALOG} .v-btn-toggle .v-btn`, { hasText: "JSON" }).click();
          await shown(`${DIALOG} ${EDITOR}`)(page);
        },
      },
      view("key-store", `${scope}/keys`, TABLE_CELL),
      opened("key-new", `${scope}/keys`, TABLE_CELL, PRIMARY_ACTION, DIALOG),
      view("repositories", `${scope}/repositories`, TABLE_CELL),
      view("team", `${scope}/team`, TABLE_CELL),
      view("project-new", `${base}/project/new`, '[data-testid="newProject-name"]'),
      view("users", `${base}/users`, TABLE_CELL),
      view("runners", `${base}/runners`, TOOLBAR_TITLE),
      view("api-tokens", `${base}/tokens`, TOOLBAR_TITLE),
      {
        name: "navigation",
        url: `${scope}/keys`,
        prepare: async (page) => {
          await shown(TABLE_CELL)(page);
          await navigationOpened(page);
          await page.locator(NAV_DASHBOARD).hover();
          await animationsSettled(page);
        },
      },
      {
        name: "navigation-focus",
        url: `${scope}/keys`,
        prepare: async (page) => {
          await shown(TABLE_CELL)(page);
          await navigationOpened(page);
          await page.locator(NAV_DASHBOARD).focus();
          await page.keyboard.press("Tab");
          await animationsSettled(page);
        },
      },
      {
        name: "project-menu",
        url: `${scope}/keys`,
        prepare: async (page) => {
          await shown(TABLE_CELL)(page);
          await menuOpened(page, PROJECT_MENU);
        },
      },
      {
        name: "user-menu",
        url: `${scope}/keys`,
        prepare: async (page) => {
          await shown(TABLE_CELL)(page);
          await menuOpened(page, USER_MENU);
        },
      },
      {
        name: "system-info",
        url: `${scope}/keys`,
        prepare: async (page) => {
          await shown(TABLE_CELL)(page);
          await menuOpened(page, USER_MENU);
          await page.locator(`${MENU} .v-list-item:has(.mdi-server)`).click();
          await shown(`${DIALOG} .v-data-table`)(page);
        },
      },
      {
        name: "account-edit",
        url: `${scope}/keys`,
        prepare: async (page) => {
          await shown(TABLE_CELL)(page);
          await menuOpened(page, USER_MENU);
          await page.locator(`${MENU} .v-list-item:has(.mdi-pencil)`).click();
          await shown(`${DIALOG} input`)(page);
        },
      },
    ];
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await openSignIn(page);
    await assertDesignTokens(page, "semaphore");
  });

  test("design: the sign-in page takes frame, card, primary action and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openSignIn(page);
      await assertToken(page, SIGN_IN_PAGE, "background-color", "--design-frame", `sign-in ${mode}`);
      await expect(page.locator(SIGN_IN_PAGE)).toHaveCSS("background-image", "none");
      await assertToken(page, SIGN_IN_CARD, "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, USERNAME, "color", "--design-text", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await page.locator(SUBMIT).hover();
      await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await openSignIn(page);
    await assertLightAndDark(page, SIGN_IN_CARD, "semaphore sign-in");
    await assertReadable(
      page,
      [`${SIGN_IN_CARD} h2`, `${SIGN_IN_CARD} .v-label`, SUBMIT, { selector: ".auth__divider", optional: true }],
      "semaphore sign-in",
    );
  });

  test("design: the signed-in interface takes frame, surfaces, primary action, text and dividers from the palette", async ({
    page,
  }) => {
    shared.skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(240_000));
    await signIn(page);
    const { project } = await seedShowcase(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/project/${project}/keys`);
      await shown(TABLE_CELL)(page);
      await assertFrameFocus(page, mode);
      await assertToken(page, APP, "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, FRAME, "background-color", "--design-frame", `frame ${mode}`);
      await assertToken(page, NAV_DASHBOARD, "color", "--design-on-frame", `frame ${mode}`);
      await assertToken(page, NAV_SELECTED, "background-color", "--design-frame-active", `selected entry ${mode}`);
      await assertToken(page, TOOLBAR_TITLE, "color", "--design-text", `shell ${mode}`);
      await assertToken(page, TABLE_CELL, "color", "--design-text", `list ${mode}`);
      await assertToken(page, TABLE_HEAD, "border-bottom-color", "--design-border", `list head divider ${mode}`);
      await assertToken(page, TABLE_CELL, "border-bottom-color", "--design-border", `list row divider ${mode}`);
      await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `primary action ${mode}`);
      await page.locator(NAV_DASHBOARD).hover();
      await assertToken(page, NAV_DASHBOARD, "background-color", "--design-frame-hover", `hovered entry ${mode}`);
      await menuOpened(page, PROJECT_MENU);
      await expect(page.locator(`${FRAME} ${MENU}`), "the menu of a drawer entry lives outside the frame").toHaveCount(0);
      await assertToken(page, `${MENU} .v-list`, "background-color", "--design-surface-2", `drawer menu ${mode}`);
      await assertToken(
        page,
        `${MENU} [data-testid="sidebar-newProject"]`,
        "color",
        "--design-text",
        `drawer menu ${mode}`,
      );
    }
    await page.emulateMedia({ colorScheme: null });
    await gotoOnion(page, `${base}/project/${project}/keys`);
    await shown(TABLE_CELL)(page);
    await assertLightAndDark(page, TABLE_CELL, "semaphore shell");
    await assertReadable(
      page,
      [
        TOOLBAR_TITLE,
        TABLE_HEAD,
        TABLE_CELL,
        PRIMARY_ACTION,
        `${NAV_DASHBOARD} .v-list-item__title`,
        `${NAV_SELECTED} .v-list-item__title`,
      ],
      "semaphore shell",
    );
  });

  test("design: literal colors of hints, placeholders, neutral buttons and inset tables come from the palette", async ({
    page,
  }) => {
    shared.skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(240_000));
    await signIn(page);
    const seeded = await seedShowcase(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertLiteralColors(page, seeded, mode);
    }
  });

  test("design: the native dark mode switch drives the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(180_000));
    await page.emulateMedia({ colorScheme: "light" });
    await signIn(page);
    const { project } = await seedShowcase(page);
    await gotoOnion(page, `${base}/project/${project}/keys`);
    await shown(TABLE_CELL)(page);
    const root = page.locator("html");
    await expect(root, "without a choice the palette follows the browser").not.toHaveAttribute(
      "data-design-theme",
      /.+/,
    );
    const light = await tokenValue(page, "--design-surface-1", "color");
    await page.locator(THEME_SWITCH).click();
    await expect(root).toHaveAttribute("data-design-theme", "dark");
    await expect(page.locator(APP)).toHaveClass(/theme--dark/);
    await assertToken(page, APP, "background-color", "--design-surface-1", "switched to dark");
    expect(await tokenValue(page, "--design-surface-1", "color"), "the dark palette must differ").not.toBe(light);
    await page.locator(THEME_SWITCH).click();
    await expect(root).toHaveAttribute("data-design-theme", "light");
    await expect(page.locator(APP)).toHaveClass(/theme--light/);
    await assertToken(page, APP, "background-color", "--design-surface-1", "switched back to light");
    expect(await tokenValue(page, "--design-surface-1", "color")).toBe(light);
  });

  test("design: the sign-in page shows the generated logo and the configured title", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await openSignIn(page);
    if (title) await expect(page).toHaveTitle(title);
    if (logoUrl) {
      await expect(page.locator(BRAND)).toHaveCSS("background-image", `url("${logoUrl}")`);
      expect(faviconUrl, "DESIGN_FAVICON_URL must accompany a configured logo").toBeTruthy();
      await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
      const box = await page.locator(BRAND).boundingBox();
      expect(Math.round(box.width), "the sign-in logo box is square").toBe(Math.round(box.height));
      for (const url of [logoUrl, faviconUrl]) {
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
    }
  });

  test("design: gallery of sign-in, project, automation, administration and menus", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    const failures = [];
    await nativeThemeFollowsScheme(page);
    try {
      await captureDesignGallery(page, signInViews());
    } catch (error) {
      failures.push(error.message);
    }
    await signIn(page);
    try {
      await captureDesignGallery(page, signedInViews(await seedShowcase(page)));
    } catch (error) {
      failures.push(error.message);
    }
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
