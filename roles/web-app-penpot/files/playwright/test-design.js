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

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const lockupUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOCKUP_URL || "") || logoUrl;
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const THEME_CLASS = { light: "light", dark: "default" };
const THEME_LABEL = { light: "Penpot Light", dark: "Penpot Dark (default)", system: "System theme" };
const SHOWCASE = "Design showcase";
const READY_TIMEOUT = 60_000;
const VIEW_TIMEOUT = 10_000;

const AUTH_SECTION = "main[class*='auth__auth-section']";
const AUTH_LOGO = "a[class*='auth__logo-btn']";
const LOGIN_TITLE = "[data-testid='login-title']";
const LOGIN_SUBMIT = "[data-testid='login-submit']";
const EMAIL = `${AUTH_SECTION} input[type='email']`;
const PASSWORD = `${AUTH_SECTION} input[type='password']`;
const RECOVERY_SUBMIT = "[data-testid='recovery-resquest-submit']";
const SIDEBAR = "[data-testid='dashboard-sidebar']";
const SIDEBAR_LOGO = `${SIDEBAR} [class*='sidebar__penpot-icon']`;
const HEADER = "[data-testid='dashboard-header']";
const NAV_TITLE = `${SIDEBAR} [class*='element-title']`;
const NAV_CURRENT = `${SIDEBAR} li[class*='sidebar__current']`;
const NAV_ENTRY = `${SIDEBAR} li:not([class*='sidebar__current']) [class*='element-title']`;
const PROFILE_BUTTON = "[data-testid='profile-btn']";
const PROFILE_MENU_ENTRY = "[data-testid='profile-profile-opt']";
const TEAM_SWITCH = `${SIDEBAR} button[aria-haspopup='menu']`;
const TEAM_MENU_ENTRY = `${SIDEBAR} [role='menu'] [role='menuitem']`;
const NEW_PROJECT = "[data-testid='new-project-button']";
const PROJECT_OPTIONS = "[data-testid='project-options']";
const GRID_ITEM = "li[class*='grid-item']";
const TABLE_ROW = "[class*='table-row']";
const INVITE = "[data-testid='invite-member']";
const INVITE_DIALOG = "[class*='team__modal-team-container']";
const DELETED = "[data-testid='deleted-page-section']";
const SETTINGS_NAV = "[data-testid='settings-profile']";
const SETTINGS_FORM = "[data-testid='settings-form']";
const SETTINGS_CONTAINER = "[class*='settings__dashboard-container']";
const SAVE_PROFILE = `${SETTINGS_CONTAINER} button[class*='btn-primary']`;
const SAVE_NOTIFICATIONS = "[data-testid='submit-settings']";
const SAVE_PASSWORD = "[data-testid='submit-password']";
const SAVE_OPTIONS = "[data-testid='submit-lang-change']";
const THEME_SELECT = `${SETTINGS_FORM} [role='combobox']`;
const SELECT_OPTION = "[class*='custom-select-dropdown'] li";
const REMOVE_ACCOUNT = "[data-testid='remove-acount-btn']";
const CONFIRM_REMOVE_ACCOUNT = "[data-testid='delete-account-btn']";
const LAYERS = "[role='tabpanel']";

let session = null;

/**
 * Args:
 *   page: signed-in Playwright page; the request runs inside it, so the session cookie travels along.
 *   method: name of the Penpot RPC method.
 *   params: JSON parameters of the call.
 *
 * Returns:
 *   The HTTP status and the decoded answer, whose keys the backend writes in camelCase.
 */
async function rpc(page, method, params) {
  return page.evaluate(
    async ([name, body]) => {
      const response = await fetch(`/api/main/methods/${name}`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify(body),
      });
      return { status: response.status, data: await response.json().catch(() => null) };
    },
    [method, params || {}],
  );
}

exports.register = function (shared) {
  const { test, expect, skipUnlessServiceEnabled, isServiceEnabled, env } = shared;
  const base = env.baseUrl.replace(/\/$/, "");

  /**
   * Args:
   *   name: marker that makes the document URL unique. Every Penpot route is a hash route, so without it two routes share one document and a navigation between them requests none.
   *   route: hash route of the app, starting with a slash.
   *
   * Returns:
   *   The URL of that route.
   */
  function url(name, route) {
    return `${base}/?design-view=${name}#${route}`;
  }

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

  function shown(selector, timeout = READY_TIMEOUT) {
    return async (page) => {
      await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(timeout) });
      await animationsSettled(page);
    };
  }

  function loaded(visibleSelector, attachedSelector) {
    return async (page) => {
      await shown(visibleSelector, VIEW_TIMEOUT)(page);
      await expect(page.locator(attachedSelector).first()).toBeAttached({ timeout: resolveTimeout(VIEW_TIMEOUT) });
      await animationsSettled(page);
    };
  }

  /**
   * Args:
   *   readySelector: element that is visible once the page has rendered, at every viewport.
   *   trigger: control that opens the panel. Penpot keeps its desktop grid on a narrow viewport, where a control of the content column lies outside of it, so the click is dispatched on the element.
   *   panel: element of the opened menu or dialog.
   */
  function opened(readySelector, trigger, panel) {
    return async (page) => {
      await shown(readySelector, VIEW_TIMEOUT)(page);
      await expect(page.locator(trigger).first()).toBeAttached({ timeout: resolveTimeout(VIEW_TIMEOUT) });
      if (!(await page.locator(panel).first().isVisible())) await page.locator(trigger).first().dispatchEvent("click");
      await expect(page.locator(panel).first()).toBeAttached({ timeout: resolveTimeout(VIEW_TIMEOUT) });
      await animationsSettled(page);
      await expect(page.locator(panel).first()).toHaveCSS("opacity", "1");
    };
  }

  /**
   * Args:
   *   page: Playwright page that ends signed in as the administrator on the dashboard. The first call signs in through the login surface the deployment offers; later calls reuse that session.
   */
  async function signIn(page) {
    if (session) {
      await page.context().addCookies(session);
      await gotoOnion(page, url("session", "/"));
    } else if (isServiceEnabled("sso")) {
      await shared.penpotOidcLogin(page, env.adminUsername, env.adminPassword);
    } else if (isServiceEnabled("ldap")) {
      await shared.penpotLdapLogin(page, env.adminEmail, env.adminPassword);
    } else {
      await shared.penpotNativeLogin(page, env.adminEmail, env.adminPassword);
    }
    await expect(page.locator(SIDEBAR)).toBeVisible({ timeout: resolveTimeout(READY_TIMEOUT) });
    if (!session) session = await page.context().cookies();
  }

  /**
   * Args:
   *   page: signed-in Playwright page.
   *   theme: value of the profile setting: "light", "dark" or "system".
   *
   * Returns:
   *   The value the profile held before; a profile that never picked a theme holds none.
   */
  async function storeTheme(page, theme) {
    const profile = await rpc(page, "get-profile");
    expect(profile.status, "the session must resolve its profile").toBe(200);
    const saved = await rpc(page, "update-profile", { fullname: profile.data.fullname, theme });
    expect(saved.status, `storing the theme ${theme}`).toBe(200);
    return profile.data.theme || "dark";
  }

  /**
   * Args:
   *   page: signed-in Playwright page.
   *   body: steps that need the app to follow the color scheme of the browser. Penpot shows its dark theme to a profile that picked none; the theme the profile had before is stored again afterwards.
   */
  async function withSystemTheme(page, body) {
    const previous = await storeTheme(page, "system");
    try {
      return await body();
    } finally {
      await storeTheme(page, previous);
    }
  }

  /**
   * Args:
   *   page: signed-in Playwright page; a project and a file named after the showcase get created when they are missing.
   *
   * Returns:
   *   The ids of the default team, the showcase project and the showcase file.
   */
  async function seedShowcase(page) {
    const profile = await rpc(page, "get-profile");
    expect(profile.status, "the session must resolve its profile").toBe(200);
    const teamId = profile.data.defaultTeamId;
    const projects = await rpc(page, "get-projects", { teamId });
    expect(projects.status, "the administrator must list projects").toBe(200);
    let project = projects.data.find((entry) => entry.name === SHOWCASE && !entry.deletedAt);
    if (!project) {
      const created = await rpc(page, "create-project", { teamId, name: SHOWCASE });
      expect(created.status, "seeding the showcase project").toBe(200);
      project = created.data;
    }
    const files = await rpc(page, "get-project-files", { projectId: project.id });
    expect(files.status, "the administrator must list files").toBe(200);
    let file = files.data.find((entry) => entry.name === SHOWCASE);
    if (!file) {
      const created = await rpc(page, "create-file", { projectId: project.id, name: SHOWCASE });
      expect(created.status, "seeding the showcase file").toBe(200);
      file = created.data;
    }
    return { teamId, projectId: project.id, fileId: file.id };
  }

  async function pickTheme(page, theme) {
    await page.locator(THEME_SELECT).nth(1).click();
    await page.locator(SELECT_OPTION, { hasText: THEME_LABEL[theme] }).click();
    await page.locator(SAVE_OPTIONS).click();
  }

  function visitorViews() {
    return [
      { name: "sign-in", url: url("sign-in", "/auth/login"), prepare: shown(LOGIN_TITLE, VIEW_TIMEOUT) },
      {
        name: "sign-in-focus",
        url: url("sign-in-focus", "/auth/login"),
        prepare: async (page) => {
          await shown(EMAIL, VIEW_TIMEOUT)(page);
          await page.locator(EMAIL).focus();
          await animationsSettled(page);
        },
      },
      {
        name: "sign-in-invalid",
        url: url("sign-in-invalid", "/auth/login"),
        prepare: async (page) => {
          await shown(EMAIL, VIEW_TIMEOUT)(page);
          await page.locator(EMAIL).fill("not-an-address");
          await page.locator(EMAIL).blur();
          await animationsSettled(page);
        },
      },
      {
        name: "recovery-request",
        url: url("recovery-request", "/auth/recovery/request"),
        prepare: shown(RECOVERY_SUBMIT, VIEW_TIMEOUT),
      },
    ];
  }

  function signedInViews({ teamId, projectId, fileId }) {
    const team = `team-id=${teamId}`;
    const dashboard = (name, route, content) => ({ name, url: url(name, route), prepare: loaded(SIDEBAR, content) });
    const settings = (name, route, content) => ({ name, url: url(name, route), prepare: loaded(SETTINGS_NAV, content) });
    return [
      dashboard("projects", `/dashboard/recent?${team}`, NEW_PROJECT),
      {
        name: "project-menu",
        url: url("project-menu", `/dashboard/recent?${team}`),
        prepare: opened(SIDEBAR, PROJECT_OPTIONS, "[role='menu'] [role='menuitem']"),
      },
      dashboard("project-files", `/dashboard/files?${team}&project-id=${projectId}`, GRID_ITEM),
      dashboard("libraries", `/dashboard/libraries?${team}`, HEADER),
      dashboard("fonts", `/dashboard/fonts?${team}`, HEADER),
      dashboard("deleted", `/dashboard/deleted?${team}`, DELETED),
      dashboard("team-members", `/dashboard/members?${team}`, TABLE_ROW),
      dashboard("team-invitations", `/dashboard/invitations?${team}`, INVITE),
      dashboard("team-settings", `/dashboard/settings?${team}`, HEADER),
      {
        name: "invite-dialog",
        url: url("invite-dialog", `/dashboard/invitations?${team}`),
        prepare: opened(SIDEBAR, INVITE, INVITE_DIALOG),
      },
      {
        name: "profile-menu",
        url: url("profile-menu", `/dashboard/recent?${team}`),
        prepare: opened(SIDEBAR, PROFILE_BUTTON, PROFILE_MENU_ENTRY),
      },
      {
        name: "team-switcher",
        url: url("team-switcher", `/dashboard/recent?${team}`),
        prepare: opened(SIDEBAR, TEAM_SWITCH, TEAM_MENU_ENTRY),
      },
      {
        name: "navigation-hover",
        url: url("navigation-hover", `/dashboard/recent?${team}`),
        prepare: async (page) => {
          await shown(SIDEBAR, VIEW_TIMEOUT)(page);
          await page.locator(NAV_TITLE).nth(1).hover();
          await animationsSettled(page);
        },
      },
      settings("settings-profile", "/settings/profile", REMOVE_ACCOUNT),
      settings("settings-password", "/settings/password", SAVE_PASSWORD),
      settings("settings-notifications", "/settings/notifications", SAVE_NOTIFICATIONS),
      settings("settings-options", "/settings/options", SETTINGS_FORM),
      settings("settings-feedback", "/settings/feedback", HEADER),
      {
        name: "delete-account-dialog",
        url: url("delete-account-dialog", "/settings/profile"),
        prepare: opened(SETTINGS_NAV, REMOVE_ACCOUNT, CONFIRM_REMOVE_ACCOUNT),
      },
      { name: "not-found", url: url("not-found", "/design-showcase-missing"), prepare: shown("#app svg", VIEW_TIMEOUT) },
      {
        name: "workspace",
        url: url("workspace", `/workspace?${team}&file-id=${fileId}`),
        prepare: shown(LAYERS, VIEW_TIMEOUT),
      },
    ];
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, url("tokens", "/auth/login"));
    await shown(LOGIN_TITLE)(page);
    await assertDesignTokens(page, "Penpot");
  });

  test("design: the sign-in page follows the browser and takes surface, action and text from the palette", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, url(`sign-in-${mode}`, "/auth/login"));
      await shown(LOGIN_TITLE)(page);
      await expect(
        page.locator("html"),
        "a visitor has no profile, so the palette follows the browser instead of Penpot's dark default",
      ).not.toHaveAttribute("data-design-theme");
      await assertToken(page, AUTH_SECTION, "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, LOGIN_TITLE, "color", "--design-text", `sign-in ${mode}`);
      if (await page.locator(LOGIN_SUBMIT).isVisible()) {
        await page.locator(EMAIL).fill("design@example.org");
        await page.locator(PASSWORD).fill("design-showcase");
        await expect(page.locator(LOGIN_SUBMIT)).toBeEnabled();
        await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
        await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
        await page.locator(LOGIN_SUBMIT).hover();
        await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
      }
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, AUTH_SECTION, "Penpot sign-in");
    await assertReadable(
      page,
      [LOGIN_TITLE, { selector: LOGIN_SUBMIT, optional: true }, `${AUTH_SECTION} label`],
      "Penpot sign-in",
    );
  });

  test("design: the signed-in interface takes surfaces, dividers, actions and text from the palette", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    const { teamId } = await seedShowcase(page);
    await withSystemTheme(page, async () => {
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        await gotoOnion(page, url(`shell-${mode}`, `/dashboard/recent?team-id=${teamId}`));
        await shown(NEW_PROJECT)(page);
        await expect(page.locator("body"), "the system theme follows the browser").toHaveClass(THEME_CLASS[mode]);
        await expect(page.locator("html")).toHaveAttribute("data-design-theme", mode);
        await assertToken(page, SIDEBAR, "background-color", "--design-surface-1", `shell ${mode}`);
        await assertToken(page, SIDEBAR, "border-right-color", "--design-border", `sidebar divider ${mode}`);
        await assertToken(page, NAV_ENTRY, "color", "--design-text", `shell ${mode}`);
        await assertToken(page, NAV_CURRENT, "background-color", "--design-surface-active", `selected entry ${mode}`);
        await assertToken(page, `${NAV_CURRENT} [class*='element-title']`, "color", "--design-link", `selected entry ${mode}`);

        await gotoOnion(page, url(`form-${mode}`, "/settings/profile"));
        await shown(REMOVE_ACCOUNT)(page);
        await assertToken(page, SETTINGS_CONTAINER, "border-top-color", "--design-border", `content divider ${mode}`);
        const fullname = page.locator(`${SETTINGS_CONTAINER} input[type='text']`).first();
        await fullname.focus();
        await fullname.pressSequentially("x");
        await expect(page.locator(SAVE_PROFILE)).toBeEnabled();
        await assertToken(page, SAVE_PROFILE, "background-color", "--design-primary", `form action ${mode}`);
        await assertToken(page, SAVE_PROFILE, "color", "--design-on-primary", `form action ${mode}`);
        await page.locator(SAVE_PROFILE).hover();
        await assertToken(page, SAVE_PROFILE, "background-color", "--design-primary-hover", `hovered action ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
      await gotoOnion(page, url("shell", `/dashboard/recent?team-id=${teamId}`));
      await shown(NEW_PROJECT)(page);
      await assertLightAndDark(page, SIDEBAR, "Penpot dashboard");
      await assertReadable(
        page,
        [NAV_TITLE, NEW_PROJECT, `${PROFILE_BUTTON} span`, `${SIDEBAR} [class*='sidebar-section-title']`],
        "Penpot dashboard",
      );
    });
  });

  test("design: a theme picked in the settings is respected and mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    const previous = await storeTheme(page, "system");
    const html = page.locator("html");
    const surface = () => tokenValue(page, "--design-surface-1", "background-color");
    try {
      await page.emulateMedia({ colorScheme: "dark" });
      await gotoOnion(page, url("theme", "/settings/options"));
      await shown(SETTINGS_FORM)(page);
      await expect(html, "the system theme follows the browser").toHaveAttribute("data-design-theme", "dark");
      const darkSurface = await surface();

      await pickTheme(page, "light");
      await expect(page.locator("body")).toHaveClass("light");
      await expect(html).toHaveAttribute("data-design-theme", "light");
      expect(await surface(), "a light theme picked in Penpot must switch the tokens while the browser prefers dark").not.toBe(
        darkSurface,
      );
      await assertToken(page, "body", "--color-background-primary", "--design-surface-1", "light theme picked in Penpot");
      const lightSurface = await surface();

      await page.emulateMedia({ colorScheme: "light" });
      await pickTheme(page, "dark");
      await expect(page.locator("body")).toHaveClass("default");
      await expect(html).toHaveAttribute("data-design-theme", "dark");
      expect(await surface(), "a dark theme picked in Penpot must keep the dark tokens while the browser prefers light").toBe(
        darkSurface,
      );

      await gotoOnion(page, url("theme-kept", "/settings/options"));
      await shown(SETTINGS_FORM)(page);
      await expect(html, "the picked theme must survive a reload").toHaveAttribute("data-design-theme", "dark");

      await pickTheme(page, "system");
      await expect(html, "the system theme hands the mode back to the browser").toHaveAttribute("data-design-theme", "light");
      expect(await surface()).toBe(lightSurface);
    } finally {
      await page.emulateMedia({ colorScheme: null });
      await storeTheme(page, previous);
    }
  });

  test("design: the interface shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await gotoOnion(page, url("brand", "/auth/login"));
    await shown(LOGIN_TITLE)(page);
    const titled = (label) =>
      expect
        .poll(async () => (await page.title()).split(title).length - 1, {
          message: `the title of ${label} must carry the configured title exactly once`,
        })
        .toBe(1);
    const loads = (address) =>
      page.evaluate(
        (src) =>
          new Promise((resolve) => {
            const image = new Image();
            image.onload = () => resolve(image.naturalWidth > 0);
            image.onerror = () => resolve(false);
            image.src = src;
          }),
        address,
      );
    if (title) await titled("the sign-in page");
    if (logoUrl) {
      await expect(page.locator(AUTH_LOGO)).toHaveCSS("background-image", `url("${lockupUrl}")`);
      await expect(page.locator(`${AUTH_LOGO} > svg`)).toHaveCSS("visibility", "hidden");
      const box = await page.locator(AUTH_LOGO).boundingBox();
      expect(
        box.width,
        `the logo box on the sign-in page is ${box.width}x${box.height} and must be wider than high`,
      ).toBeGreaterThan(box.height);
      expect(faviconUrl, "DESIGN_FAVICON_URL must accompany a configured logo").toBeTruthy();
      await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
      for (const address of [lockupUrl, faviconUrl]) {
        expect(await loads(address), `the page must be allowed to load ${address}`).toBe(true);
      }
    }

    await signIn(page);
    if (title) await titled("the dashboard");
    if (logoUrl) {
      await expect(page.locator(SIDEBAR_LOGO).first()).toHaveCSS("background-image", `url("${logoUrl}")`);
      await expect(page.locator(`${SIDEBAR_LOGO} > svg`).first()).toHaveCSS("visibility", "hidden");
      expect(await loads(logoUrl), `the page must be allowed to load ${logoUrl}`).toBe(true);
    }
  });

  test("design: gallery of sign-in, dashboard, team, settings, dialogs, menus and editor", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(3_600_000));

    await signIn(page);
    const signedIn = signedInViews(await seedShowcase(page));
    await page.context().clearCookies();
    const failures = [];
    await captureDesignGallery(page, visitorViews()).catch((error) => failures.push(error.message));
    await signIn(page);
    await withSystemTheme(page, () =>
      captureDesignGallery(page, signedIn).catch((error) => failures.push(error.message)),
    );
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
