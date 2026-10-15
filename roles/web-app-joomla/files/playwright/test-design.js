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

const base = normalizeBaseUrl(process.env.JOOMLA_BASE_URL || "").replace(/\/$/, "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const logoEnabled = process.env.DESIGN_LOGO_ENABLED === "true";

const MODES = ["light", "dark"];
const ACTION = { timeout: resolveTimeout(10_000) };
const DESKTOP = { width: 1440, height: 900 };
const SHOWCASE_TITLE = "Design showcase";
const SHOWCASE_CATEGORY = "Design showcase category";
const site = (query) => `${base}/index.php?${query ? `${query}&` : ""}fallback=local`;
const admin = (query) => `${base}/administrator/index.php${query ? `?${query}` : ""}`;

const SITE_HEADER = "header.container-header";
const SITE_BRAND = `${SITE_HEADER} .navbar-brand`;
const SITE_LOGO = `${SITE_HEADER} a.brand-logo img`;
const SITE_MAIN = "main";
const SITE_USERNAME = "main input[name='username']";
const SITE_PASSWORD = "main input[name='password']";
const SITE_SUBMIT = "main form button[type='submit'].btn-primary";
const SITE_LINK = ".mod-login__options a";
const ADMIN_FORM = "#form-login";
const ADMIN_USERNAME = "#mod-login-username";
const ADMIN_PASSWORD = "#mod-login-password";
const ADMIN_SUBMIT = "#btn-login-submit";
const ADMIN_HEADER = "#header";
const ADMIN_SIDEBAR = "#sidebar-wrapper";
const ADMIN_CONTENT = "#content";
const ADMIN_LOGO = `${ADMIN_HEADER} .logo img:not(.logo-collapsed)`;
const ADMIN_LIST = "form#adminForm";
const ADMIN_LIST_ROW = "form#adminForm table tbody tr";
const ADMIN_LIST_CELL = "form#adminForm table tbody tr:first-child td";
const ADMIN_LIST_LINK = "form#adminForm table tbody tr th a";
const ADMIN_NAV_LINK = `${ADMIN_SIDEBAR} .main-nav a`;
const ADMIN_PRIMARY = `${ADMIN_LIST} .filter-search-bar__button`;
const ADMIN_CLEAR = `${ADMIN_LIST} .js-stools-btn-clear`;
const ADMIN_SELECT = `${ADMIN_LIST} select.form-select`;
const ADMIN_STATUS_SELECT = "select.form-select-success";
const ADMIN_TAB_CURRENT = "joomla-tab button[role='tab'][aria-selected='true']";
const ADMIN_NOTICE_CLOSE = "#system-message-container .joomla-alert--close";
const ADMIN_USER_TOGGLE = ".header-profile .dropdown-toggle";
const ADMIN_USER_MENU = ".header-profile .dropdown-menu.show";
const ADMIN_SCHEME_SWITCH = "button[data-color-scheme-switch]";
const TOUR = ".shepherd-element";
const TOUR_CLOSE = ".shepherd-cancel-icon";
const EDITOR = ".tox-tinymce";
const EDITOR_TOOLBAR = ".tox .tox-toolbar__primary";
const EDITOR_BUTTON = ".tox .tox-tbtn";
const EDITOR_MENU_BUTTON = ".tox .tox-mbtn";
const EDITOR_STATUSBAR = ".tox .tox-statusbar";
const EDITOR_MENU = ".tox .tox-menu";
const EDITOR_FRAME = "iframe.tox-edit-area__iframe";
const ARTICLE_FORM = "option=com_content&view=article&layout=edit";

/**
 * Args:
 *   page: Playwright page that shows the element.
 *   selector: element that must be visible before the page counts as ready.
 */
async function shown(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible(ACTION);
}

/**
 * Args:
 *   page: Playwright page of the administrator; returns once the template has applied the scheme the browser asks for.
 */
async function schemeApplied(page) {
  await page.waitForFunction(
    () =>
      document.documentElement.getAttribute("data-bs-theme") ===
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
    null,
    ACTION,
  );
}

/**
 * Args:
 *   page: Playwright page on the control panel right after the sign-in; returns once no guided tour covers it.
 */
async function dismissTour(page) {
  let autostart = null;
  await expect
    .poll(
      async () => {
        autostart = await page
          .evaluate(() =>
            document.readyState === "complete" && window.Joomla && window.Joomla.getOptions
              ? String(window.Joomla.getOptions("com_guidedtours.autotour") || "")
              : null,
          )
          .catch(() => null);
        return autostart;
      },
      { message: "the control panel must tell whether a guided tour starts", ...ACTION },
    )
    .not.toBeNull();
  if (autostart === "") return;
  await shown(page, TOUR_CLOSE);
  await page.locator(TOUR_CLOSE).first().click(ACTION);
  await expect(page.locator(TOUR).first()).toBeHidden(ACTION);
}

/**
 * Args:
 *   page: Playwright page; ends on the control panel with an administrator session.
 */
async function signInToAdministrator(page) {
  await gotoOnion(page, admin("fallback=local"));
  await shown(page, `${ADMIN_FORM}, ${ADMIN_CONTENT}`);
  if (await page.locator(ADMIN_FORM).isVisible()) {
    await expect(page.locator(ADMIN_USERNAME)).toBeEditable(ACTION);
    await page.locator(ADMIN_USERNAME).fill(adminUsername);
    await expect(page.locator(ADMIN_PASSWORD)).toBeEditable(ACTION);
    await page.locator(ADMIN_PASSWORD).fill(adminPassword);
    await page.locator(ADMIN_SUBMIT).click(ACTION);
  }
  await shown(page, `body.com_cpanel ${ADMIN_CONTENT}`);
  await dismissTour(page);
}

/**
 * Args:
 *   page: Playwright page; ends with a site session of the administrator.
 */
async function signInToSite(page) {
  await gotoOnion(page, site("option=com_users&view=login"));
  await shown(page, SITE_MAIN);
  if (await page.locator(SITE_USERNAME).isVisible()) {
    await expect(page.locator(SITE_USERNAME)).toBeEditable(ACTION);
    await page.locator(SITE_USERNAME).fill(adminUsername);
    await expect(page.locator(SITE_PASSWORD)).toBeEditable(ACTION);
    await page.locator(SITE_PASSWORD).fill(adminPassword);
    await page.locator(SITE_SUBMIT).first().click(ACTION);
  }
  await shown(page, "main .com-users-profile, main .com-users-logout");
}

/**
 * Args:
 *   page: Playwright page on a form with a TinyMCE field; returns once the toolbar shows and the content document holds its body.
 */
async function editorReady(page) {
  await shown(page, EDITOR);
  await page.locator(EDITOR).first().scrollIntoViewIfNeeded(ACTION);
  await shown(page, EDITOR_TOOLBAR);
  await expect
    .poll(
      () =>
        page
          .locator(EDITOR_FRAME)
          .first()
          .evaluate((frame) => frame.contentDocument?.readyState === "complete" && Boolean(frame.contentDocument.body?.classList.contains("mce-content-body"))),
      ACTION,
    )
    .toBe(true);
}

/**
 * Args:
 *   page: Playwright page with a ready editor.
 *   property: CSS property of the editor's content body.
 * Returns: the computed value.
 */
async function editorBody(page, property) {
  return page
    .locator(EDITOR_FRAME)
    .first()
    .evaluate((frame, name) => frame.contentWindow.getComputedStyle(frame.contentDocument.body).getPropertyValue(name), property);
}

/**
 * Args:
 *   page: Playwright page with a ready editor; returns once the menu of the menu bar entry labelled `label` is open and done animating.
 *   label: pattern of the menu bar entry.
 */
async function openEditorMenu(page, label) {
  await page.locator(EDITOR_MENU_BUTTON).filter({ hasText: label }).first().click(ACTION);
  const menu = page.locator(`${EDITOR_MENU}:visible`).first();
  await expect(menu).toBeVisible(ACTION);
  await expect(menu).toHaveCSS("opacity", "1", ACTION);
}

test.use({ ignoreHTTPSErrors: true });

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, site(""));
  await shown(page, SITE_BRAND);
  await assertDesignTokens(page, "joomla site");
  await gotoOnion(page, admin("fallback=local"));
  await shown(page, ADMIN_SUBMIT);
  const surface = {};
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await expect(page.locator("html"), `the administrator must hand its ${mode} scheme to the tokens`).toHaveAttribute("data-design-theme", mode);
    surface[mode] = await tokenValue(page, "--design-surface-1", "color");
  }
  expect(surface.dark, "--design-surface-1 must change with the scheme of the administrator").not.toBe(surface.light);
});

test("design: the site takes frame, page, text, link and primary action from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, site("option=com_users&view=login"));
    await shown(page, SITE_USERNAME);
    await assertToken(page, SITE_HEADER, "background-color", "--design-frame", `header ${mode}`);
    await expect(page.locator(SITE_HEADER), `the header gradient must be gone in ${mode} mode`).toHaveCSS("background-image", "none");
    await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `body text ${mode}`);
    await assertToken(page, SITE_PASSWORD, "background-color", "--design-surface-2", `field ${mode}`);
    await assertToken(page, SITE_PASSWORD, "border-top-color", "--design-border-strong", `field boundary ${mode}`);
    await assertToken(page, SITE_SUBMIT, "background-color", "--design-primary", `primary action ${mode}`);
    await assertToken(page, SITE_SUBMIT, "color", "--design-on-primary", `primary action ${mode}`);
    await assertToken(page, SITE_LINK, "color", "--design-link", `link ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, `${SITE_MAIN} label`, "joomla site");
  await assertReadable(page, [`${SITE_MAIN} label`, SITE_SUBMIT, SITE_LINK, `${SITE_MAIN} a`, ".sidebar-right .card-header", ".mod-breadcrumbs__item.active"], "joomla site");
});

test("design: the administrator takes frame, navigation, list and actions from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signInToAdministrator(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, admin("option=com_plugins&view=plugins"));
    await shown(page, ADMIN_LIST_ROW);
    await schemeApplied(page);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", mode);
    await assertToken(page, ADMIN_HEADER, "background-color", "--design-frame", `header ${mode}`);
    await assertToken(page, `${ADMIN_HEADER} .page-title`, "color", "--design-on-frame", `page title ${mode}`);
    await assertToken(page, ADMIN_SIDEBAR, "background-color", "--design-frame", `sidebar ${mode}`);
    await assertToken(page, ADMIN_NAV_LINK, "color", "--design-on-frame", `navigation entry ${mode}`);
    await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
    await assertToken(page, ADMIN_LIST_CELL, "color", "--design-text", `list text ${mode}`);
    await assertToken(page, ADMIN_LIST_CELL, "border-bottom-color", "--design-border", `list divider ${mode}`);
    await assertToken(page, ADMIN_LIST_LINK, "color", "--design-link", `list link ${mode}`);
    await assertToken(page, ADMIN_PRIMARY, "background-color", "--design-primary", `primary action ${mode}`);
    await assertToken(page, ADMIN_PRIMARY, "color", "--design-on-primary", `primary action ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ADMIN_LIST_CELL, "joomla administrator");
  await assertReadable(page, [ADMIN_LIST_CELL, ADMIN_LIST_LINK, ADMIN_NAV_LINK, `${ADMIN_HEADER} .page-title`, ADMIN_PRIMARY], "joomla administrator");
});

test("design: search tools, selects and tabs of the administrator follow the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signInToAdministrator(page);
  await gotoOnion(page, admin("option=com_plugins&view=plugins&filter[search]=content"));
  await shown(page, ADMIN_LIST_ROW);
  await expect(page.locator(ADMIN_CLEAR)).toBeEnabled(ACTION);
  await assertToken(page, ADMIN_CLEAR, "background-color", "--design-primary", "clear button");
  await assertToken(page, ADMIN_CLEAR, "color", "--design-on-primary", "clear button");
  await expect(page.locator(ADMIN_SELECT).first(), "the select must not paint the upstream arrow image").toHaveCSS("background-image", "none");
  await assertToken(page, ADMIN_SELECT, "background-color", "--design-surface-2", "select");
  await assertToken(page, ADMIN_SELECT, "color", "--design-text", "select");
  await gotoOnion(page, admin("option=com_plugins&view=plugins&filter[search]="));
  await shown(page, ADMIN_LIST_ROW);

  await gotoOnion(page, admin("option=com_content&view=article&layout=edit"));
  await shown(page, "#jform_title");
  await assertToken(page, ADMIN_STATUS_SELECT, "background-color", "--design-surface-2", "status select");
  await assertToken(page, ADMIN_STATUS_SELECT, "color", "--design-success", "status select");
  await assertReadable(page, [ADMIN_TAB_CURRENT, ADMIN_STATUS_SELECT, `${ADMIN_CONTENT} label`], "joomla administrator form");
});

test("design: the article editor takes frame, toolbar, menus and content from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signInToAdministrator(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, admin(ARTICLE_FORM));
    await shown(page, "#jform_title");
    await schemeApplied(page);
    await editorReady(page);
    await assertToken(page, EDITOR, "border-top-color", "--design-border-strong", `editor ${mode}`);
    await assertToken(page, EDITOR_TOOLBAR, "background-color", "--design-surface-2", `editor toolbar ${mode}`);
    await expect(page.locator(EDITOR_TOOLBAR).first(), `the toolbar separator gradient must be gone in ${mode} mode`).toHaveCSS("background-image", "none");
    await assertToken(page, EDITOR_BUTTON, "color", "--design-text", `editor button ${mode}`);
    await assertToken(page, `${EDITOR_BUTTON} svg`, "fill", "--design-text", `editor icon ${mode}`);
    await assertToken(page, EDITOR_MENU_BUTTON, "color", "--design-text", `editor menu bar ${mode}`);
    await assertToken(page, ".tox .tox-promotion", "background-color", "--design-surface-2", `editor menu bar end ${mode}`);
    await assertToken(page, EDITOR_STATUSBAR, "background-color", "--design-surface-2", `editor status bar ${mode}`);
    await assertToken(page, EDITOR_STATUSBAR, "color", "--design-text-muted", `editor status bar ${mode}`);
    expect(await editorBody(page, "background-color"), `editor content ${mode}`).toBe(await tokenValue(page, "--design-surface-2", "background-color"));
    expect(await editorBody(page, "color"), `editor text ${mode}`).toBe(await tokenValue(page, "--design-text", "color"));
    await openEditorMenu(page, /insert/i);
    await assertToken(page, `${EDITOR_MENU}:visible`, "background-color", "--design-surface-2", `editor menu ${mode}`);
    await assertToken(page, `${EDITOR_MENU}:visible .tox-collection__item-label`, "color", "--design-text", `editor menu entry ${mode}`);
    await page.keyboard.press("Escape");
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [EDITOR_BUTTON, EDITOR_MENU_BUTTON, { selector: `${EDITOR_STATUSBAR} .tox-statusbar__path-item`, optional: true }], "joomla editor");
});

test("design: the site submission form takes tabs, labels and the editor from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signInToSite(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, site("option=com_content&view=form&layout=edit"));
    await shown(page, "main form#adminForm");
    await editorReady(page);
    await assertToken(page, "main joomla-tab > joomla-tab-element[active]", "background-color", "--design-surface-2", `tab panel ${mode}`);
    await assertToken(page, "main joomla-tab > joomla-tab-element[active]", "border-top-color", "--design-border", `tab panel boundary ${mode}`);
    await assertToken(page, "main joomla-tab div[role='tablist']", "background-color", "--design-surface-3", `tab list ${mode}`);
    await assertToken(page, "main joomla-tab button[role='tab'][aria-selected='true']", "color", "--design-text", `current tab ${mode}`);
    await assertToken(page, "main joomla-tab-element[active] label", "color", "--design-text", `form label ${mode}`);
    await assertToken(page, EDITOR_TOOLBAR, "background-color", "--design-surface-2", `site editor toolbar ${mode}`);
    expect(await editorBody(page, "background-color"), `site editor content ${mode}`).toBe(await tokenValue(page, "--design-surface-2", "background-color"));
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, "main joomla-tab-element[active] label", "joomla site form");
  await assertReadable(page, ["main joomla-tab-element[active] label", "main joomla-tab button[role='tab']", EDITOR_MENU_BUTTON], "joomla site form");
});

test("design: the editor follows the scheme picked in the administrator over the browser preference", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await page.emulateMedia({ colorScheme: "light" });
  await signInToAdministrator(page);
  await gotoOnion(page, admin(ARTICLE_FORM));
  await editorReady(page);
  const light = await editorBody(page, "background-color");
  const flip = async (scheme) => {
    await gotoOnion(page, admin(""));
    await shown(page, `body.com_cpanel ${ADMIN_CONTENT}`);
    await page.locator(`${ADMIN_USER_TOGGLE}:visible`).first().click(ACTION);
    await shown(page, ADMIN_USER_MENU);
    await page.locator(`${ADMIN_SCHEME_SWITCH}:visible`).first().click(ACTION);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", scheme);
  };
  await flip("dark");
  try {
    await gotoOnion(page, admin(ARTICLE_FORM));
    await editorReady(page);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    await expect
      .poll(() => page.locator(EDITOR_FRAME).first().evaluate((frame) => frame.contentDocument.documentElement.getAttribute("data-design-theme")), ACTION)
      .toBe("dark");
    await expect.poll(() => editorBody(page, "background-color"), ACTION).not.toBe(light);
    expect(await editorBody(page, "background-color"), "editor content in the picked scheme").toBe(await tokenValue(page, "--design-surface-2", "background-color"));
    expect(await editorBody(page, "color"), "editor text in the picked scheme").toBe(await tokenValue(page, "--design-text", "color"));
    await assertToken(page, EDITOR_TOOLBAR, "background-color", "--design-surface-2", "editor toolbar in the picked scheme");
    await assertToken(page, EDITOR_BUTTON, "color", "--design-text", "editor button in the picked scheme");
  } finally {
    await flip("light");
  }
});

test("design: the administrator sign-in page takes card, labels and the primary action from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, admin("fallback=local"));
    await shown(page, ADMIN_SUBMIT);
    await schemeApplied(page);
    await assertToken(page, `${ADMIN_FORM} label`, "color", "--design-text", `label ${mode}`);
    await assertToken(page, ADMIN_SUBMIT, "background-color", "--design-primary", `primary action ${mode}`);
    await assertToken(page, ADMIN_SUBMIT, "color", "--design-on-primary", `primary action ${mode}`);
    await assertToken(page, ADMIN_SIDEBAR, "background-color", "--design-frame", `brand panel ${mode}`);
    await assertToken(page, `${ADMIN_SIDEBAR} .h1`, "color", "--design-on-frame", `site name ${mode}`);
    await assertToken(page, `${ADMIN_SIDEBAR} .h2`, "color", "--design-on-frame", `sign-in subtitle ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [`${ADMIN_FORM} label`, ADMIN_SUBMIT, `${ADMIN_SIDEBAR} .h1`, `${ADMIN_SIDEBAR} .h2`], "joomla administrator sign-in");
});

test("design: the template style parameters carry the light palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.emulateMedia({ colorScheme: "light" });
  await gotoOnion(page, admin("fallback=local"));
  await shown(page, ADMIN_SUBMIT);
  const inline = await page.evaluate(() =>
    [...document.querySelectorAll("head style")].map((node) => node.textContent).find((text) => text.includes("--template-bg-light")),
  );
  const literal = async (name) => {
    const value = new RegExp(`${name}:\\s*([^;]+);`).exec(inline)[1].trim();
    return page.evaluate((color) => {
      const probe = document.createElement("span");
      probe.style.color = color;
      document.body.appendChild(probe);
      const computed = getComputedStyle(probe).color;
      probe.remove();
      return computed;
    }, value);
  };
  expect(await literal("--template-bg-light"), "bg-light parameter").toBe(await tokenValue(page, "--design-surface-1", "color"));
  expect(await literal("--template-text-dark"), "text-dark parameter").toBe(await tokenValue(page, "--design-text", "color"));
  expect(await literal("--template-text-light"), "text-light parameter").toBe(await tokenValue(page, "--design-on-frame", "color"));
  expect(await literal("--link-color"), "link-color parameter").toBe(await tokenValue(page, "--design-link", "color"));
  await gotoOnion(page, site(""));
  await shown(page, SITE_BRAND);
  await expect(page.locator("head link[href*='css/global/custom_infinito']"), "the color file of the site template").toHaveCount(1);
});

test("design: the template stylesheet reaches sign-in, error and component pages of both templates", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  const siteSheet = "head link[href*='/media/templates/site/cassiopeia/css/user']";
  const adminSheet = "head link[href*='/media/templates/administrator/atum/css/user']";
  for (const query of ["", "option=com_users&view=login", "option=com_content&view=article&id=999999", "option=com_users&view=login&tmpl=component"]) {
    await gotoOnion(page, site(query));
    await expect(page.locator(siteSheet), `site stylesheet on '${query}'`).toHaveCount(1);
    await assertToken(page, "body", "color", "--design-text", `body text on '${query}'`);
  }
  await gotoOnion(page, admin("fallback=local"));
  await shown(page, ADMIN_SUBMIT);
  await expect(page.locator(adminSheet), "administrator stylesheet on the sign-in page").toHaveCount(1);
  await signInToAdministrator(page);
  for (const query of ["option=com_users&view=users", "option=com_users&view=users&tmpl=component"]) {
    await gotoOnion(page, admin(query));
    await shown(page, ADMIN_LIST);
    await expect(page.locator(adminSheet), `administrator stylesheet on '${query}'`).toHaveCount(1);
    await assertToken(page, ADMIN_LIST_CELL, "color", "--design-text", `list text on '${query}'`);
  }
});

test("design: the native scheme switch of the administrator decides over the browser preference", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await page.emulateMedia({ colorScheme: "light" });
  await signInToAdministrator(page);
  await schemeApplied(page);
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
  const light = await tokenValue(page, "--design-surface-1", "background-color");
  await page.locator(`${ADMIN_USER_TOGGLE}:visible`).first().click(ACTION);
  await shown(page, ADMIN_USER_MENU);
  await page.locator(`${ADMIN_SCHEME_SWITCH}:visible`).first().click(ACTION);
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
  expect(await tokenValue(page, "--design-surface-1", "background-color"), "the tokens must follow the switch").not.toBe(light);
  await assertToken(page, "body", "background-color", "--design-surface-1", "page after the switch");
  await assertToken(page, ADMIN_HEADER, "background-color", "--design-frame", "header after the switch");
  await page.locator(`${ADMIN_SCHEME_SWITCH}:visible`).first().click(ACTION);
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
});

test("design: every focus stop inside the frame draws its indicator in the frame text color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signInToAdministrator(page);
  await gotoOnion(page, admin("option=com_users&view=users"));
  await shown(page, ADMIN_LIST_ROW);
  const onFrame = await tokenValue(page, "--design-on-frame", "color");
  let stops = 0;
  for (let step = 0; step < 30; step += 1) {
    await page.keyboard.press("Tab");
    const focus = await page.evaluate(() => {
      const element = document.activeElement;
      if (!element || !element.closest("#header, #sidebar-wrapper") || element.closest(".skip-to")) return null;
      const style = getComputedStyle(element);
      return { name: `${element.tagName}.${element.className}`, style: style.outlineStyle, color: style.outlineColor };
    });
    if (focus === null) continue;
    stops += 1;
    expect(focus.style, `${focus.name} must draw a focus outline`).not.toBe("none");
    expect(focus.color, `${focus.name} must draw its focus outline in --design-on-frame`).toBe(onFrame);
  }
  expect(stops, "no focus stop inside the frame was reached").toBeGreaterThan(3);
});

test("design: logos, favicon and title are the corporate ones on both surfaces", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoEnabled, "the logo replacement is switched off");
  await page.setViewportSize(DESKTOP);
  await gotoOnion(page, site(""));
  await shown(page, SITE_BRAND);
  await expect(page.locator(SITE_LOGO)).toHaveAttribute("src", /images\/infinito-design\/site-brand\.svg/);
  await expect(page.locator(SITE_LOGO)).toHaveAttribute("alt", title);
  await expect(page.locator(SITE_LOGO)).toHaveJSProperty("complete", true);
  const siteBox = await page.locator(SITE_LOGO).boundingBox();
  expect(siteBox.width, "the site lockup must be wider than high").toBeGreaterThan(siteBox.height * 1.5);
  await expect(page.locator("head link[rel='icon']")).toHaveAttribute("href", /templates\/site\/cassiopeia\/images\/joomla-favicon\.svg/);

  await gotoOnion(page, admin("fallback=local"));
  await shown(page, ADMIN_SUBMIT);
  await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  await expect(page.locator(".login .main-brand img, .login img").first()).toHaveAttribute("src", /images\/infinito-design\/admin-login\.svg/);
  const loginLogo = page.locator(".login .main-brand img").first();
  await expect(loginLogo).toBeVisible(ACTION);
  await expect(loginLogo, "the sign-in lockup must load").toHaveJSProperty("complete", true);
  expect(await loginLogo.evaluate((image) => image.naturalWidth), "the sign-in lockup must decode").toBeGreaterThan(0);
  const loginBox = await loginLogo.boundingBox();
  expect(loginBox.width, "the sign-in lockup must be wider than high").toBeGreaterThan(loginBox.height * 1.5);
  const raw = (token) => page.evaluate((name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim().toLowerCase(), token);
  const scheme = {};
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await schemeApplied(page);
    scheme[mode] = { link: await raw("--design-link"), surface: await raw("--design-surface-1") };
  }
  await page.emulateMedia({ colorScheme: null });
  const loginResponse = await apiGetOnion(request, `${base}/images/infinito-design/admin-login.svg`, { ignoreHTTPSErrors: true });
  expect(loginResponse.status(), "admin-login.svg must be served").toBe(200);
  const loginSvg = (await loginResponse.text()).toLowerCase();
  const loginTexts = [...loginSvg.matchAll(/<text[^>]*>/g)].map((match) => match[0]);
  expect(loginTexts.length, "admin-login.svg must carry the title").toBeGreaterThan(0);
  for (const text of loginTexts) {
    expect(/\sfill="([^"]+)"/.exec(text)[1], "admin-login.svg must render its text in --design-link").toBe(scheme.light.link);
    expect(/\sstroke="([^"]+)"/.exec(text)[1], "admin-login.svg must outline its text in --design-surface-1").toBe(scheme.light.surface);
  }
  expect(loginSvg, "admin-login.svg must switch its text to the dark palette").toContain(`text{fill:${scheme.dark.link};stroke:${scheme.dark.surface}}`);
  await expect(page.locator(`${ADMIN_SIDEBAR} .h1`)).toHaveText(title);
  await expect(page.locator("head link[rel='icon']")).toHaveAttribute("href", /templates\/administrator\/atum\/images\/joomla-favicon\.svg/);

  await signInToAdministrator(page);
  await gotoOnion(page, admin("option=com_users&view=users"));
  await shown(page, ADMIN_LIST);
  await expect(page.locator(ADMIN_LOGO)).toHaveAttribute("src", /images\/infinito-design\/admin-brand\.svg/);
  await expect(page.locator(ADMIN_LOGO)).toHaveJSProperty("complete", true);
  const adminBox = await page.locator(ADMIN_LOGO).boundingBox();
  expect(adminBox.width, "the administrator lockup must be wider than high").toBeGreaterThan(adminBox.height * 1.5);

  const onFrame = (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--design-on-frame"))).trim();
  for (const lockup of ["site-brand", "admin-brand"]) {
    const response = await apiGetOnion(request, `${base}/images/infinito-design/${lockup}.svg`, { ignoreHTTPSErrors: true });
    expect(response.status(), `${lockup}.svg must be served`).toBe(200);
    const texts = [...(await response.text()).matchAll(/<text[^>]*>/g)].map((match) => match[0]);
    expect(texts.length, `${lockup}.svg must carry the title`).toBeGreaterThan(0);
    for (const text of texts) {
      expect(/\sfill="([^"]+)"/.exec(text)[1].toLowerCase(), `${lockup}.svg must render its text in --design-on-frame`).toBe(onFrame.toLowerCase());
      expect(Number(/font-size="([^"]+)"/.exec(text)[1]), `${lockup}.svg must render its text at a readable size`).toBeGreaterThanOrEqual(12);
    }
  }
});

/**
 * Args:
 *   page: Playwright page with an administrator session.
 *   list: query of the administrator list that holds the entry.
 *   form: query of the form that creates the entry.
 *   name: title of the entry; an entry of that title is created once.
 *   task: Joomla task that saves the form.
 *   fill: optional step on the opened form before it is saved.
 * Returns: the id of the entry.
 */
async function seedEntry(page, { list, form, name, task, fill }) {
  const entry = page.locator(`${ADMIN_LIST} table tbody a`).filter({ hasText: name }).first();
  await gotoOnion(page, admin(`${list}&filter[search]=${encodeURIComponent(name)}`));
  await shown(page, ADMIN_LIST);
  if ((await entry.count()) === 0) {
    await gotoOnion(page, admin(form));
    await shown(page, "#jform_title");
    await page.locator("#jform_title").fill(name);
    if (fill) await fill(page);
    await page.evaluate((save) => window.Joomla.submitbutton(save), task);
    await shown(page, ADMIN_LIST);
    await gotoOnion(page, admin(`${list}&filter[search]=${encodeURIComponent(name)}`));
    await shown(page, ADMIN_LIST);
  }
  await expect(entry).toBeVisible(ACTION);
  return new URL(await entry.getAttribute("href"), base).searchParams.get("id");
}

const view = (name, url, selector, extra) => ({
  name,
  url,
  prepare: async (page) => {
    await shown(page, selector);
    if (extra) await extra(page);
  },
});

/**
 * Args:
 *   page: Playwright page of the administrator; closes the statistics notice a fresh installation shows on every page.
 */
async function closeNotice(page) {
  const close = page.locator(ADMIN_NOTICE_CLOSE).first();
  if (await close.isVisible()) {
    await close.click(ACTION);
    await expect(close).toBeHidden(ACTION);
  }
}

const administratorView = (name, query, selector, extra) =>
  view(name, admin(query), selector, async (page) => {
    await schemeApplied(page);
    await closeNotice(page);
    if (extra) await extra(page);
  });

const visitorViews = (articleId) => [
  view("site-home", site(""), SITE_BRAND),
  view("site-article", site(`option=com_content&view=article&id=${articleId}`), "main .com-content-article"),
  view("site-category-blog", site("option=com_content&view=category&layout=blog&id=2"), "main .com-content-category-blog"),
  view("site-categories", site("option=com_content&view=categories&id=0"), "main .com-content-categories"),
  view("site-archive", site("option=com_content&view=archive"), "main .com-content-archive"),
  view("site-search", site("option=com_finder&view=search&q=design"), "main .com-finder"),
  view("site-sign-in", site("option=com_users&view=login"), SITE_USERNAME),
  view("site-sign-in-rejected", site("option=com_users&view=login"), SITE_USERNAME, async (page) => {
    await page.locator(SITE_USERNAME).fill("design-gallery-visitor");
    await page.locator(SITE_PASSWORD).fill("design-gallery-visitor");
    await page.locator(SITE_SUBMIT).first().click(ACTION);
    await shown(page, "#system-message-container joomla-alert");
  }),
  view("site-password-reset", site("option=com_users&view=reset"), "main form button[type='submit']"),
  view("site-username-reminder", site("option=com_users&view=remind"), "main form button[type='submit']"),
  view("site-not-found", site("option=com_content&view=article&id=999999"), SITE_BRAND),
  view("admin-sign-in", admin("fallback=local"), ADMIN_SUBMIT, schemeApplied),
];

const memberViews = () => [
  view("site-profile", site("option=com_users&view=profile"), "main .com-users-profile"),
  view("site-profile-edit", site("option=com_users&view=profile&layout=edit"), "main form#member-profile"),
  view("site-article-submit", site("option=com_content&view=form&layout=edit"), "main form#adminForm", editorReady),
];

const administratorViews = () => [
  view("admin-dashboard", admin(""), `body.com_cpanel ${ADMIN_CONTENT}`, schemeApplied),
  administratorView("admin-user-menu", "option=com_cpanel&view=cpanel&dashboard=system", `body.com_cpanel ${ADMIN_CONTENT}`, async (page) => {
    await page.locator(`${ADMIN_USER_TOGGLE}:visible`).first().click(ACTION);
    await shown(page, ADMIN_USER_MENU);
    await expect(page.locator(ADMIN_USER_MENU).first()).toHaveCSS("opacity", "1");
  }),
  administratorView("admin-articles", "option=com_content&view=articles&filter[search]=", ADMIN_LIST_ROW),
  administratorView("admin-article-new", ARTICLE_FORM, "#jform_title", editorReady),
  administratorView("admin-article-editor-menu", ARTICLE_FORM, "#jform_title", async (page) => {
    await editorReady(page);
    await openEditorMenu(page, /insert/i);
  }),
  administratorView("admin-categories", "option=com_categories&view=categories&extension=com_content&filter[search]=", ADMIN_LIST_ROW),
  administratorView("admin-users", "option=com_users&view=users", ADMIN_LIST_ROW),
  administratorView("admin-user-new", "option=com_users&view=user&layout=edit", "#jform_name"),
  administratorView("admin-user-groups", "option=com_users&view=groups", ADMIN_LIST_ROW),
  administratorView("admin-menu-items", "option=com_menus&view=items&menutype=mainmenu", ADMIN_LIST_ROW),
  administratorView("admin-modules", "option=com_modules&view=modules&client_id=0", ADMIN_LIST_ROW),
  administratorView("admin-plugins", "option=com_plugins&view=plugins", ADMIN_LIST_ROW),
  administratorView("admin-extensions", "option=com_installer&view=manage", ADMIN_LIST_ROW),
  administratorView("admin-template-styles", "option=com_templates&view=styles&client_id=0", ADMIN_LIST_ROW),
  administratorView("admin-global-configuration", "option=com_config", "#jform_sitename"),
  administratorView("admin-system-information", "option=com_admin&view=sysinfo", `${ADMIN_CONTENT} joomla-tab`),
  administratorView("admin-mail-templates", "option=com_mails&view=templates", ADMIN_LIST_ROW),
  administratorView("admin-guided-tours", "option=com_guidedtours&view=tours", ADMIN_LIST_ROW),
  administratorView("admin-action-logs", "option=com_actionlogs&view=actionlogs", ADMIN_LIST_ROW),
  administratorView("admin-media", "option=com_media", "#com-media"),
];

/**
 * Args:
 *   page: Playwright page with an administrator session; ends with one showcase category and one published, featured showcase article.
 * Returns: the id of the showcase article.
 */
async function seedShowcase(page) {
  await seedEntry(page, {
    list: "option=com_categories&view=categories&extension=com_content",
    form: "option=com_categories&view=category&layout=edit&extension=com_content",
    name: SHOWCASE_CATEGORY,
    task: "category.save",
  });
  return seedEntry(page, {
    list: "option=com_content&view=articles",
    form: "option=com_content&view=article&layout=edit",
    name: SHOWCASE_TITLE,
    task: "article.save",
    fill: (form) => form.locator("input[name='jform[featured]'][value='1']").check({ force: true, ...ACTION }),
  });
}

test("design: gallery of site and administrator", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(3_600_000));
  await page.addInitScript(() => {
    if (window.location.protocol === "https:") window.localStorage.setItem("phpdebugbar-open", "0");
  });

  const failures = [];
  const capture = async (views) => {
    try {
      await captureDesignGallery(page, views);
    } catch (error) {
      failures.push(error.message);
    }
  };
  await signInToAdministrator(page);
  const articleId = await seedShowcase(page);
  await page.context().clearCookies();
  await capture(visitorViews(articleId));
  await signInToSite(page);
  await capture(memberViews());
  await signInToAdministrator(page);
  await capture(administratorViews());
  expect(failures, failures.join("\n")).toEqual([]);
});
