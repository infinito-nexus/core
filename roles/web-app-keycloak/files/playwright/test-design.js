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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const realm = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME);
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD);
const darkClass = decodeDotenvQuotedValue(process.env.DESIGN_DARK_CLASS || "");
const logoSize = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_SIZE || "");
const theme = decodeDotenvQuotedValue(process.env.DESIGN_THEME || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const accountUrl = `${base}/realms/${realm}/account/`;
const consoleUrl = `${base}/admin/master/console/`;
const authUrl = `${base}/realms/${realm}/protocol/openid-connect/auth?client_id=account&response_type=code&scope=openid`;
const signInUrl = `${authUrl}&redirect_uri=${encodeURIComponent(accountUrl)}`;
const errorUrl = `${authUrl}&redirect_uri=${encodeURIComponent("https://unregistered.invalid/")}`;
const logoutUrl = `${base}/realms/${realm}/protocol/openid-connect/logout`;

const MODES = ["light", "dark"];
const INJECTED = /<!--infinito-inj-->[\s\S]*?<!--\/infinito-inj-->/g;
const DARK_MODE_SCRIPT = /<script type="module" async blocking="render">[\s\S]*?<\/script>/;
const UNKNOWN_USERNAME = "design-gallery-visitor";
const SIGN_IN_SUBMIT = "#kc-login";
const SIGN_IN_USERNAME = "#username";
const SIGN_IN_PASSWORD = "#password";
const SIGN_IN_TITLE = "#kc-page-title";
const SIGN_IN_LABEL = "label[for='username']";
const SIGN_IN_FIELD = ".pf-v5-c-form-control";
const SIGN_IN_FORGOT = "a[href*='reset-credentials']";
const SIGN_IN_ERROR = "#input-error-username, #input-error, .pf-v5-c-helper-text__item.pf-m-error";
const SIGN_IN_ERROR_TEXT = ".pf-v5-c-helper-text__item.pf-m-error .pf-v5-c-helper-text__item-text";
const SIGN_IN_LOGO = ".kc-logo-text";
const CARD = ".pf-v5-c-login__main";
const CARD_HEADER = ".pf-v5-c-login__main-header";
const PAGE = ".pf-v5-c-page";
const MASTHEAD = ".pf-v5-c-masthead";
const SIDEBAR = ".pf-v5-c-page__sidebar";
const FRAME = `${MASTHEAD}, ${SIDEBAR}`;
const BRAND = `${MASTHEAD} .pf-v5-c-masthead__brand img`;
const NAV_TOGGLE = "[data-testid='nav-toggle']";
const NAV_LINK = `${SIDEBAR} a.pf-v5-c-nav__link`;
const NAV_CURRENT = `${SIDEBAR} a.pf-v5-c-nav__link.pf-m-current`;
const NAV_IDLE = `${SIDEBAR} a.pf-v5-c-nav__link:not(.pf-m-current):visible`;
const NAV_HOVERED = `${SIDEBAR} a.pf-v5-c-nav__link:hover`;
const SECTION = ".pf-v5-c-page__main-section.pf-m-light";
const PRIMARY = ".pf-v5-c-page__main .pf-v5-c-button.pf-m-primary";
const ACCOUNT_SAVE = "[data-testid='save']";
const ACCOUNT_HEADING = ".pf-v5-c-page__main h1";
const CONSOLE_ADD_USER = "[data-testid='add-user']";
const CONSOLE_HEADING = ".pf-v5-c-page__main h1";
const USER_MENU_TOGGLE = `${MASTHEAD} .pf-v5-c-menu-toggle:visible >> nth=-1`;
const MENU = ".pf-v5-c-menu:visible";
const MENU_ENTRY = `${MENU} .pf-v5-c-menu__list-item`;
const MENU_HOVERED = ".pf-v5-c-menu .pf-v5-c-menu__list-item:hover";
const DIALOG = "[role='dialog']";
const DIALOG_DANGER = `${DIALOG} .pf-v5-c-button.pf-m-danger`;
const KEBAB = "button[aria-label='Kebab toggle']:visible";
const TABLE = ".pf-v5-c-table";
const TABLE_ROW = `${TABLE} tbody tr`;
const TABLE_LINK = `${TABLE_ROW} a`;
const TABLE_HEAD = `${TABLE} thead th`;
const TABLE_HEAD_ROW = `${TABLE} thead`;
const SWITCH_ON = ".pf-v5-c-switch__input:checked ~ .pf-v5-c-switch__toggle";
const NOTICE = ".pf-v5-c-banner.pf-m-gold";
const BUSY = ".pf-v5-c-spinner, .pf-v5-c-skeleton";
const LOGOUT_PANEL = "#infinito-logout-status";
const LOGOUT_PANEL_LINE = `${LOGOUT_PANEL} > p`;

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
 *   panel: dialog or menu that must have finished opening.
 */
async function opened(page, panel) {
  await expect(page.locator(panel).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(page.locator(panel).first()).toHaveCSS("opacity", "1");
  await settled(page);
}

/**
 * Args:
 *   page: Playwright page without a session of the platform realm; ends on the account console.
 */
async function signInToAccount(page) {
  await gotoOnion(page, accountUrl);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await shown(page, ACCOUNT_SAVE);
}

/**
 * Args:
 *   page: Playwright page without a session of the master realm; ends on the user list of the platform realm.
 */
async function signInToConsole(page) {
  await gotoOnion(page, `${consoleUrl}?view=sign-in#/${realm}/users`);
  await performKeycloakLoginForm(page, superAdminUsername, superAdminPassword);
  await shown(page, CONSOLE_ADD_USER);
}

/**
 * Args:
 *   page: Playwright page that shows a console; a collapsed sidebar gets expanded.
 *   entry: name of the navigation entry the pointer rests on afterwards.
 */
async function navigationOpened(page, entry) {
  const sidebar = page.locator(SIDEBAR);
  if (!(await sidebar.evaluate((element) => element.classList.contains("pf-m-expanded")))) await page.locator(NAV_TOGGLE).click();
  await expect(sidebar).toHaveClass(/pf-m-expanded/);
  await expect.poll(async () => (await sidebar.boundingBox()).x, { message: "the sidebar must have slid in" }).toBe(0);
  await sidebar.getByRole("link", { name: entry, exact: true }).hover();
  await settled(page);
}

/**
 * Args:
 *   page: Playwright page that shows a list of the administration console.
 *   name: text of the link whose target replaces the list.
 *   selector: element of the target page that must be visible afterwards.
 */
async function followListLink(page, name, selector) {
  const href = await page.getByRole("link", { name, exact: true }).first().getAttribute("href");
  await gotoOnion(page, `${consoleUrl}?view=${encodeURIComponent(name)}${href}`);
  await shown(page, selector);
}

/**
 * Args:
 *   page: Playwright page that resolves the expression.
 *   expression: CSS color expression, tokens included.
 *
 * Returns:
 *   The computed color of a probe styled with the expression.
 */
async function colorOf(page, expression) {
  return page.evaluate((value) => {
    const probe = document.createElement("span");
    probe.style.color = value;
    document.body.appendChild(probe);
    const color = getComputedStyle(probe).color;
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
 *   page: Playwright page whose requests carry the session.
 *   url: address of the lockup the theme serves.
 *   box: box the page gives the lockup.
 *   label: surface named in the failure message.
 */
async function assertLockup(page, url, box, label) {
  const [width, height] = logoSize.split("x").map(Number);
  expect(url, `${label}: the lockup must come from the corporate theme`).toContain(`/${theme}/`);
  const source = await (await apiGetOnion(page.request, new URL(url, base).toString())).text();
  expect(Number(/width="(\d+)"/.exec(source)[1]), `${label}: the lockup must be rendered for the declared slot`).toBe(width);
  expect(Number(/height="(\d+)"/.exec(source)[1]), `${label}: the lockup must be rendered for the declared slot`).toBe(height);
  expect(width / height, `${label}: the lockup must be wide enough to carry the title next to the symbol`).toBeGreaterThanOrEqual(1.5);
  expect(box.width, `${label}: a ${box.width}x${box.height} box must be at least twice as wide as high`).toBeGreaterThanOrEqual(2 * box.height);
  expect((box.height * width) / height, `${label}: the lockup must fit the width of its box at full height`).toBeLessThanOrEqual(box.width + 1);
  expect(
    (Number(/font-size="(\d+)"/.exec(source)[1]) * box.height) / height,
    `${label}: the title of the lockup must not be painted smaller than 12px`,
  ).toBeGreaterThanOrEqual(12);
  if (title) expect(source, `${label}: the lockup must carry the corporate title`).toContain(`>${title}</text>`);
  expect(
    await colorOf(page, / fill="([^"]+)"/.exec(source)[1]),
    `${label}: the title of the lockup must be painted in the on-color of the frame it sits on`,
  ).toBe(await colorOf(page, "var(--design-on-frame)"));
  await assertLoads(page, url);
}

const view = (name, url, selector, extra) => ({
  name,
  url,
  prepare: async (page) => {
    await shown(page, selector);
    if (extra) await extra(page);
  },
});

const panel = (name, url, opener, target, before) => ({
  name,
  url,
  prepare: async (page) => {
    if (!(await page.locator(target).first().isVisible())) {
      if (before) await before(page);
      await shown(page, opener);
      await page.locator(opener).first().click();
    }
    await opened(page, target);
  },
});

const accountView = (name, path, selector, extra) => view(name, `${accountUrl}${path}?view=${name}`, selector, extra);
const consoleRoute = (name, hash) => `${consoleUrl}?view=${name}#/${realm}${hash}`;
const consoleView = (name, hash, selector, extra) => view(name, consoleRoute(name, hash), selector, extra);

const visitorViews = () => [
  view("sign-in", signInUrl, SIGN_IN_SUBMIT),
  view("sign-in-focus", signInUrl, SIGN_IN_SUBMIT, async (page) => {
    await page.locator(SIGN_IN_USERNAME).fill(UNKNOWN_USERNAME);
    await page.keyboard.press("Tab");
    await settled(page);
  }),
  view("sign-in-rejected", signInUrl, SIGN_IN_SUBMIT, async (page) => {
    await page.locator(SIGN_IN_USERNAME).fill(UNKNOWN_USERNAME);
    await page.locator(SIGN_IN_PASSWORD).fill(UNKNOWN_USERNAME);
    await page.locator(SIGN_IN_SUBMIT).click();
    await shown(page, SIGN_IN_ERROR);
  }),
  view("forgot-password", signInUrl, SIGN_IN_SUBMIT, async (page) => {
    await page.locator(SIGN_IN_FORGOT).click();
    await shown(page, "#kc-reset-password-form");
  }),
  view("sign-out-confirmation", logoutUrl, "#kc-logout"),
  view("error-page", errorUrl, "#kc-error-message"),
  view("sign-in-console", `${consoleUrl}?view=sign-in-console`, SIGN_IN_SUBMIT),
];

const accountViews = () => [
  accountView("account-personal-info", "", ACCOUNT_SAVE),
  accountView("account-signing-in", "account-security/signing-in", "role=heading[name='Signing in']"),
  accountView("account-device-activity", "account-security/device-activity", "role=heading[name='Device activity']"),
  accountView("account-applications", "applications", ".pf-v5-c-data-list__item"),
  accountView("account-groups", "groups", "role=heading[name='Groups']"),
  accountView("account-navigation", "", ACCOUNT_SAVE, (page) => navigationOpened(page, "Applications")),
  panel("account-user-menu", `${accountUrl}?view=account-user-menu`, USER_MENU_TOGGLE, MENU),
];

const consoleViews = () => [
  consoleView("admin-realm", "", "role=heading[name=/welcome to/i]"),
  consoleView("admin-users", "/users", TABLE_ROW),
  consoleView("admin-user-create", "/users/add-user", "role=heading[name='Create user']"),
  consoleView("admin-navigation", "/users", TABLE_ROW, (page) => navigationOpened(page, "Clients")),
  consoleView("admin-user-detail", "/users", TABLE_ROW, (page) => followListLink(page, adminUsername, "role=tab[name='Credentials']")),
  consoleView("admin-groups", "/groups", "role=heading[name='Groups']"),
  consoleView("admin-clients", "/clients", TABLE_ROW),
  consoleView("admin-client-detail", "/clients", TABLE_ROW, (page) => followListLink(page, "account", "role=tab[name='Settings']")),
  consoleView("admin-client-scopes", "/client-scopes", TABLE_ROW),
  consoleView("admin-roles", "/roles", TABLE_ROW),
  consoleView("admin-sessions", "/sessions", "role=heading[name='Sessions']"),
  consoleView("admin-events", "/events", "role=heading[name='No user events']"),
  consoleView("admin-realm-settings", "/realm-settings", "[data-testid='rs-general-tab'][aria-selected='true']"),
  consoleView("admin-realm-settings-login", "/realm-settings/login", "role=heading[name='Login screen customization']"),
  consoleView("admin-realm-settings-themes", "/realm-settings/themes", "[data-testid='rs-themes-tab'][aria-selected='true']"),
  consoleView("admin-realm-settings-keys", "/realm-settings/keys", TABLE_ROW),
  consoleView("admin-authentication", "/authentication", TABLE_ROW),
  consoleView("admin-identity-providers", "/identity-providers", "role=heading[name='Identity providers']"),
  panel("admin-clear-events-dialog", consoleRoute("admin-clear-events-dialog", "/realm-settings/events"), "role=button[name='Clear user events']", DIALOG, async (page) => {
    await shown(page, "[data-testid='rs-events-tab']");
    await page.locator("[data-testid='rs-events-tab']").click();
  }),
  panel("admin-realm-actions", consoleRoute("admin-realm-actions", "/realm-settings"), "role=button[name='Action']", MENU),
  panel("admin-partial-export-dialog", consoleRoute("admin-partial-export-dialog", "/realm-settings"), "role=menuitem[name='Partial export']", DIALOG, async (page) => {
    await shown(page, "role=button[name='Action']");
    await page.locator("role=button[name='Action']").click();
  }),
  panel("admin-row-menu", consoleRoute("admin-row-menu", "/users"), KEBAB, MENU, (page) => shown(page, TABLE_ROW)),
  panel("admin-user-menu", consoleRoute("admin-user-menu", "/users"), USER_MENU_TOGGLE, MENU, (page) => shown(page, TABLE_ROW)),
];

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    expect(theme, "DESIGN_THEME must be set once design is enabled").toBeTruthy();
    await gotoOnion(page, signInUrl);
    await shown(page, SIGN_IN_SUBMIT);
    await expect(page.locator("html"), "the design script must mark the page as carrying the palette").toHaveAttribute("data-design-palette", "");
    await assertDesignTokens(page, "keycloak");
  });

  test("design: the sign-in page takes frame, card, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, signInUrl);
      await shown(page, SIGN_IN_SUBMIT);
      await expect(page.locator("html"), "PatternFly's own dark stylesheet must stay off").not.toHaveClass(/pf-v5-theme-dark/);
      await assertToken(page, "body", "background-color", "--design-frame", `page ${mode}`);
      await assertToken(page, CARD, "background-color", "--design-surface-2", `card ${mode}`);
      await assertToken(page, CARD_HEADER, "border-top-color", "--design-primary", `card accent ${mode}`);
      await assertToken(page, SIGN_IN_TITLE, "color", "--design-text", `heading ${mode}`);
      await assertToken(page, SIGN_IN_LABEL, "color", "--design-text", `label ${mode}`);
      await assertToken(page, SIGN_IN_FIELD, "background-color", "--design-surface-2", `field ${mode}`);
      await assertToken(page, SIGN_IN_FORGOT, "color", "--design-link", `link ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "color", "--design-on-primary", `primary action ${mode}`);
      await page.locator(SIGN_IN_SUBMIT).hover();
      await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary-hover", `hovered primary action ${mode}`);
      await page.locator(SIGN_IN_USERNAME).fill(UNKNOWN_USERNAME);
      await page.locator(SIGN_IN_PASSWORD).fill(UNKNOWN_USERNAME);
      await page.locator(SIGN_IN_SUBMIT).click();
      await shown(page, SIGN_IN_ERROR);
      await assertToken(page, SIGN_IN_ERROR_TEXT, "color", "--design-danger", `rejection ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [SIGN_IN_ERROR_TEXT], "keycloak rejected sign-in");
    await gotoOnion(page, signInUrl);
    await shown(page, SIGN_IN_SUBMIT);
    await assertLightAndDark(page, SIGN_IN_TITLE, "keycloak sign-in");
    await assertReadable(page, [SIGN_IN_TITLE, SIGN_IN_LABEL, SIGN_IN_SUBMIT, SIGN_IN_FORGOT], "keycloak sign-in");
  });

  test("design: the account console paints frame, navigation states and content from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signInToAccount(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${accountUrl}?view=palette-${mode}`);
      await shown(page, ACCOUNT_SAVE);
      await expect(page.locator("html"), "PatternFly's own dark stylesheet must stay off").not.toHaveClass(/pf-v5-theme-dark/);
      await assertToken(page, MASTHEAD, "background-color", "--design-frame", `masthead ${mode}`);
      await assertToken(page, SIDEBAR, "background-color", "--design-frame", `sidebar ${mode}`);
      await assertToken(page, NAV_LINK, "color", "--design-on-frame", `navigation entry ${mode}`);
      await assertToken(page, NAV_CURRENT, "background-color", "--design-frame-active", `selected navigation entry ${mode}`);
      await page.locator(NAV_IDLE).first().hover();
      await assertToken(page, NAV_HOVERED, "background-color", "--design-frame-hover", `hovered navigation entry ${mode}`);
      await assertToken(page, PAGE, "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, SECTION, "background-color", "--design-surface-2", `section ${mode}`);
      await assertToken(page, ACCOUNT_HEADING, "color", "--design-text", `heading ${mode}`);
      await assertToken(page, PRIMARY, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, PRIMARY, "color", "--design-on-primary", `primary action ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await gotoOnion(page, `${accountUrl}?view=palette`);
    await shown(page, ACCOUNT_SAVE);
    await assertLightAndDark(page, ACCOUNT_HEADING, "keycloak account console");
    await assertReadable(page, [ACCOUNT_HEADING, NAV_LINK, NAV_CURRENT, PRIMARY, `${MASTHEAD} .pf-v5-c-menu-toggle`], "keycloak account console");
  });

  test("design: the administration console maps tables, menus, switches and dialogs onto the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signInToConsole(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, consoleRoute(`palette-${mode}`, "/users"));
      await shown(page, TABLE_ROW);
      await expect(page.locator("html"), "PatternFly's own dark stylesheet must stay off").not.toHaveClass(/pf-v5-theme-dark/);
      await assertToken(page, MASTHEAD, "background-color", "--design-frame", `masthead ${mode}`);
      await assertToken(page, SIDEBAR, "background-color", "--design-frame", `sidebar ${mode}`);
      await assertToken(page, NAV_CURRENT, "background-color", "--design-frame-active", `selected navigation entry ${mode}`);
      await assertToken(page, PAGE, "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, TABLE, "background-color", "--design-surface-2", `table ${mode}`);
      await assertToken(page, TABLE_HEAD, "color", "--design-text", `table head ${mode}`);
      await expect(page.locator(TABLE_HEAD_ROW).first(), `a head tint would end before the action column ${mode}`).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
      await assertToken(page, TABLE_ROW, "border-bottom-color", "--design-border", `table row divider ${mode}`);
      await assertToken(page, TABLE_LINK, "color", "--design-link", `link ${mode}`);
      await assertToken(page, CONSOLE_ADD_USER, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, CONSOLE_ADD_USER, "color", "--design-on-primary", `primary action ${mode}`);
      await page.locator(KEBAB).first().click();
      await opened(page, MENU);
      await assertToken(page, MENU, "background-color", "--design-surface-2", `menu ${mode}`);
      await page.locator(MENU_ENTRY).first().hover();
      await assertToken(page, MENU_HOVERED, "background-color", "--design-surface-hover", `hovered menu entry ${mode}`);
      await page.keyboard.press("Escape");

      await gotoOnion(page, consoleRoute(`switch-${mode}`, "/realm-settings/login"));
      await shown(page, "role=heading[name='Login screen customization']");
      await assertToken(page, SWITCH_ON, "background-color", "--design-primary", `switched-on toggle ${mode}`);

      await gotoOnion(page, consoleRoute(`notice-${mode}`, "/events"));
      await shown(page, NOTICE);
      await assertToken(page, NOTICE, "background-color", "--design-warning", `notice ${mode}`);
      await assertToken(page, NOTICE, "color", "--design-on-warning", `notice ${mode}`);

      await gotoOnion(page, consoleRoute(`dialog-${mode}`, "/realm-settings/events"));
      await shown(page, "[data-testid='rs-events-tab']");
      await page.locator("[data-testid='rs-events-tab']").click();
      await page.locator("role=button[name='Clear user events']").click();
      await opened(page, DIALOG);
      await assertToken(page, DIALOG_DANGER, "background-color", "--design-danger", `destructive action ${mode}`);
      await assertToken(page, DIALOG_DANGER, "color", "--design-on-danger", `destructive action ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [DIALOG_DANGER, { selector: `${DIALOG} h1`, optional: true }], "keycloak confirmation dialog");
    await gotoOnion(page, consoleRoute("notice", "/events"));
    await shown(page, NOTICE);
    await assertReadable(page, [NOTICE], "keycloak notice");
    await gotoOnion(page, consoleRoute("palette", "/users"));
    await shown(page, TABLE_ROW);
    await assertLightAndDark(page, TABLE_HEAD, "keycloak administration console");
    await assertReadable(page, [CONSOLE_HEADING, TABLE_HEAD, TABLE_LINK, CONSOLE_ADD_USER, NAV_LINK, NAV_CURRENT], "keycloak administration console");
  });

  test("design: every focus stop of the frame draws its indicator in the on-color of the frame", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signInToConsole(page);
    const onFrame = await colorOf(page, "var(--design-on-frame)");
    const inFrame = () => page.evaluate((frame) => Boolean(document.activeElement.closest(frame)), FRAME);
    for (let attempt = 0; attempt < 5 && !(await inFrame()); attempt += 1) await page.keyboard.press("Tab");
    let stops = 0;
    for (let index = 0; index < 60; index += 1) {
      const stop = await page.evaluate((frame) => {
        const element = document.activeElement;
        const style = getComputedStyle(element);
        const after = getComputedStyle(element, "::after");
        return {
          inside: Boolean(element.closest(frame)),
          name: `${element.tagName.toLowerCase()} "${(element.textContent || element.getAttribute("aria-label") || "").trim().slice(0, 30)}"`,
          outline: style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0 ? style.outlineColor : "none",
          underline: after.borderBottomStyle !== "none" && parseFloat(after.borderBottomWidth) > 0 ? after.borderBottomColor : "none",
        };
      }, FRAME);
      if (!stop.inside) break;
      expect(stop.outline, `the focus indicator of ${stop.name} inside the frame`).toBe(onFrame);
      expect(["none", "rgba(0, 0, 0, 0)", onFrame], `the focus underline PatternFly draws below ${stop.name} inside the frame`).toContain(stop.underline);
      stops += 1;
      await page.keyboard.press("Tab");
    }
    expect(stops, "the walk must have visited masthead and sidebar").toBeGreaterThan(8);

    await page.locator(USER_MENU_TOGGLE).first().click();
    await opened(page, MENU);
    await page.keyboard.press("ArrowDown");
    const entry = await page.evaluate(() => ({
      hosted: Boolean(document.activeElement.closest(".pf-v5-c-masthead .pf-v5-c-menu")),
      outline: getComputedStyle(document.activeElement).outlineColor,
    }));
    expect(entry.hosted, "the arrow key must move the focus into the menu the masthead hosts").toBe(true);
    expect(entry.outline, "a menu the frame hosts must draw its focus indicator in the link color").toBe(await colorOf(page, "var(--design-link)"));
  });

  test("design: the realm's dark mode switch decides, the browser preference only follows it", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    expect(darkClass, "DESIGN_DARK_CLASS must be set once design is enabled; an empty one builds a regex that matches every class").toBeTruthy();
    const html = page.locator("html");
    await page.emulateMedia({ colorScheme: "dark" });
    await gotoOnion(page, signInUrl);
    await shown(page, SIGN_IN_SUBMIT);
    await expect(html, "Keycloak must mark its own dark mode with the class of the corporate theme").toHaveClass(new RegExp(darkClass));
    await expect(html, "a realm that follows the browser must leave the tokens to the browser preference").not.toHaveAttribute("data-design-theme");
    const dark = await tokenValue(page, "--design-surface-2", "background-color");

    await page.route(/\/protocol\/openid-connect\/auth/, async (route) => {
      const response = await route.fetch();
      const body = (await response.text()).replace('content="light dark"', 'content="light"').replace(DARK_MODE_SCRIPT, "");
      await route.fulfill({ response, body });
    });
    await gotoOnion(page, signInUrl);
    await shown(page, SIGN_IN_SUBMIT);
    await expect(html, "a realm with dark mode switched off must pin the tokens to light").toHaveAttribute("data-design-theme", "light");
    expect(await tokenValue(page, "--design-surface-2", "background-color"), "the tokens must stay light although the browser prefers dark").not.toBe(dark);
    await assertToken(page, CARD, "background-color", "--design-surface-2", "card with dark mode switched off");
  });

  test("design: a page without the injected palette keeps Keycloak's own colors", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.route(/\/protocol\/openid-connect\/auth/, async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, body: (await response.text()).replace(INJECTED, "") });
    });
    await gotoOnion(page, signInUrl);
    await shown(page, SIGN_IN_SUBMIT);
    await expect(page.locator("html")).not.toHaveAttribute("data-design-palette");
    for (const selector of [CARD, SIGN_IN_SUBMIT]) {
      const background = await page.locator(selector).first().evaluate((element) => getComputedStyle(element).backgroundColor);
      expect(background, `${selector} must not lose its background to an unresolved token`).not.toBe("rgba(0, 0, 0, 0)");
    }
    await assertReadable(page, [SIGN_IN_TITLE, SIGN_IN_SUBMIT], "keycloak sign-in without the palette");
  });

  test("design: both realms select the corporate theme and its mapping names only variables PatternFly declares", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const stylesheet = (surface) => `link[rel='stylesheet'][href*='/${surface}/${theme}/']`;
    const mapping = () =>
      page.evaluate((marker) => {
        const declared = new Set();
        const assigned = new Set();
        const collect = (rules, target) => {
          for (const rule of rules) {
            if (rule.cssRules) collect(rule.cssRules, target);
            if (!rule.style) continue;
            for (const name of rule.style) if (name.startsWith("--pf-v5-") || name.startsWith("--keycloak-")) target.add(name);
          }
        };
        for (const sheet of document.styleSheets) {
          let rules;
          try {
            rules = sheet.cssRules;
          } catch {
            continue;
          }
          collect(rules, /design\.css/.test(sheet.href || "") && (sheet.href || "").includes(marker) ? assigned : declared);
        }
        return { assigned: assigned.size, unknown: [...assigned].filter((name) => !declared.has(name)) };
      }, `/${theme}/`);

    await gotoOnion(page, `${consoleUrl}?view=theme`);
    await shown(page, SIGN_IN_SUBMIT);
    await expect(page.locator(stylesheet("login")), "the master realm must sign in through the corporate theme").not.toHaveCount(0);

    await gotoOnion(page, signInUrl);
    await shown(page, SIGN_IN_SUBMIT);
    await expect(page.locator(stylesheet("login")), "the platform realm must sign in through the corporate theme").not.toHaveCount(0);
    const signIn = await mapping();
    expect(signIn.assigned, "the corporate stylesheet must map PatternFly's variables").toBeGreaterThan(100);
    expect(signIn.unknown, "variables the corporate stylesheet assigns although the sign-in page declares none of them").toEqual([]);

    await signInToAccount(page);
    await expect(page.locator(stylesheet("account")), "the account console must load the corporate theme").not.toHaveCount(0);

    await signInToConsole(page);
    await expect(page.locator(stylesheet("admin")), "the administration console must load the corporate theme").not.toHaveCount(0);
  });

  test("design: title, lockup and favicon are the corporate ones on every surface", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoSize && !title, "logo and title replacement are disabled for this role");
    await page.setViewportSize({ width: 1440, height: 900 });
    const favicon = page.locator("link[rel~='icon']");

    await gotoOnion(page, signInUrl);
    await shown(page, SIGN_IN_SUBMIT);
    if (title) await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    if (logoSize) {
      const logo = page.locator(SIGN_IN_LOGO);
      if (title) await expect(logo.locator("span")).toHaveText(title);
      const url = await logo.evaluate((element) => /url\("?([^")]+)"?\)/.exec(getComputedStyle(element).backgroundImage)[1]);
      await assertLockup(page, url, await logo.boundingBox(), "sign-in page");
      await expect(favicon).toHaveAttribute("href", new RegExp(`/login/${theme}/img/favicon\\.ico`));
      await assertLoads(page, await favicon.getAttribute("href"));
    }

    await signInToAccount(page);
    if (title) await expect(page).toHaveTitle(`${title} Account Console`);
    if (logoSize) {
      await assertLockup(page, await page.locator(BRAND).getAttribute("src"), await page.locator(BRAND).boundingBox(), "account console");
      await expect(favicon).toHaveAttribute("href", new RegExp(`/account/${theme}/favicon\\.ico`));
      await assertLoads(page, await favicon.getAttribute("href"));
    }

    await signInToConsole(page);
    if (title) await expect(page).toHaveTitle(`${title} Administration Console`);
    if (logoSize) {
      await assertLockup(page, await page.locator(BRAND).getAttribute("src"), await page.locator(BRAND).boundingBox(), "administration console");
      await expect(favicon).toHaveAttribute("href", new RegExp(`/admin/${theme}/favicon\\.ico`));
      await assertLoads(page, await favicon.getAttribute("href"));
    }
  });

  test("design: the logout status panel takes surface, text and tone from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    skipUnlessServiceEnabled("javascript");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, logoutUrl);
      await shown(page, LOGOUT_PANEL);
      await assertToken(page, LOGOUT_PANEL, "background-color", "--design-surface-2", `logout panel ${mode}`);
      await assertToken(page, LOGOUT_PANEL, "color", "--design-text", `logout panel ${mode}`);
      expect(
        [await tokenValue(page, "--design-warning", "color"), await tokenValue(page, "--design-danger", "color")],
        `logout panel headline ${mode}: the tone must be a status color of the palette`,
      ).toContain(await page.locator(LOGOUT_PANEL_LINE).first().evaluate((line) => getComputedStyle(line).color));
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [LOGOUT_PANEL_LINE, `${LOGOUT_PANEL_LINE} + p`], "keycloak logout panel");
  });

  test("design: gallery of sign-in pages, account console and administration console", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(3_600_000));

    const failures = [];
    const capture = async (views) => {
      try {
        await captureDesignGallery(page, views);
      } catch (error) {
        failures.push(error.message);
      }
    };
    await capture(visitorViews());
    await signInToAccount(page);
    await capture(accountViews());
    await signInToConsole(page);
    await capture(consoleViews());
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
