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

test.use({ ignoreHTTPSErrors: true });

const base = normalizeBaseUrl(
  requireDotenvValue(
    process.env.OPENPROJECT_BASE_URL || process.env.APP_BASE_URL,
    "OPENPROJECT_BASE_URL or APP_BASE_URL"
  )
).replace(/\/$/, "");
const oidcIssuerUrl = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const ssoEnabled = (process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true";
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const iconUrl = requireDotenvValue(process.env.DESIGN_ICON_URL, "DESIGN_ICON_URL");

const MODES = ["light", "dark"];
const HEADER = "header.op-app-header";
const LOGO = `${HEADER} .op-logo > .op-logo--link`;
const CONTENT = "#content";
const LOGIN_FORM = "#login-form";
const LOGIN_USER = "#login-form input#username";
const LOGIN_PASSWORD = "#login-form input#password";
const LOGIN_SUBMIT = "#login-form [type='submit']";
const PRIMARY = "#content .Button--primary:visible";
const THEME_SELECT = "#content form select#pref_theme";

let session = null;

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(page.locator(".op-loading-indicator:visible, .loading-indicator--background:visible")).toHaveCount(0, { timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the platform administrator, through oauth2-proxy and Keycloak when sso is on and through OpenProject's own form otherwise. Later calls reuse the first session.
 */
async function signIn(page) {
  if (session) {
    await page.context().addCookies(session);
  } else if (ssoEnabled) {
    await gotoOnion(page, `${base}/`);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(90_000) }).toContain(base);
  } else {
    await gotoOnion(page, `${base}/login`);
    await expect(page.locator(LOGIN_USER)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(LOGIN_USER).fill(adminUsername);
    await expect(page.locator(LOGIN_PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(LOGIN_PASSWORD).fill(adminPassword);
    await page.locator(LOGIN_SUBMIT).first().click();
    await expect(page.locator(LOGIN_FORM)).toHaveCount(0, { timeout: resolveTimeout(30_000) });
  }
  await gotoOnion(page, `${base}/my/page`);
  await shown(HEADER)(page);
  if (!session) session = await page.context().cookies();
}

/**
 * Args:
 *   page: signed-in Playwright page.
 *   theme: one of the values of OpenProject's interface theme select (light, dark, sync_with_os).
 */
async function pickTheme(page, theme) {
  await gotoOnion(page, `${base}/my/interface`);
  await expect(page.locator(THEME_SELECT)).toBeEditable({ timeout: resolveTimeout(10_000) });
  await page.locator(THEME_SELECT).selectOption(theme);
  await page.locator("#content form").filter({ has: page.locator("select#pref_theme") }).locator("[type='submit']").click();
  await expect(page.locator(THEME_SELECT)).toHaveValue(theme, { timeout: resolveTimeout(10_000) });
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "openproject");
});

test("design: accounts without a stored theme follow the browser instead of the light default", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  if (!ssoEnabled) {
    await gotoOnion(page, `${base}/login`);
    await expect(page.locator("body"), "the instance default theme is sync with OS").toHaveAttribute("data-auto-theme-switcher-theme-value", "sync_with_os");
  }
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/my/page`);
    await expect(page.locator("body")).toHaveAttribute("data-color-mode", mode);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: header is the frame, page and text take the palette, primary action reads on-primary", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/projects`);
    await shown(`${CONTENT} table`)(page);
    await assertToken(page, HEADER, "background-color", "--design-frame", `header ${mode}`);
    await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `text ${mode}`);
    await assertToken(page, PRIMARY, "background-color", "--design-primary", `primary ${mode}`);
    await assertToken(page, PRIMARY, "color", "--design-on-primary", `primary text ${mode}`);
    await assertToken(page, "#content table tbody tr", "border-bottom-color", "--design-border", `table row ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, CONTENT, "openproject projects");
  await assertReadable(page, [`${CONTENT} h1, ${CONTENT} h2`, { selector: "#main-menu a", optional: true }], "openproject projects");
});

test("design: focus indicators take the frame text color in the header and the link color outside it", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await gotoOnion(page, `${base}/my/page`);
  await shown(HEADER)(page);
  const onFrame = await tokenValue(page, "--design-on-frame", "outline-color");
  const link = await tokenValue(page, "--design-link", "outline-color");
  const inHeader = () => page.evaluate((selector) => Boolean(document.activeElement.closest(selector)), HEADER);
  for (let presses = 0; presses < 20 && !(await inHeader()); presses += 1) await page.keyboard.press("Tab");
  let stops = 0;
  for (; stops < 12 && (await inHeader()); stops += 1) {
    const drawn = await page.evaluate(() => {
      const style = getComputedStyle(document.activeElement);
      return { color: style.outlineColor, style: style.outlineStyle, field: document.activeElement.matches("input, textarea, select") };
    });
    if (!drawn.field) {
      expect(drawn.style, `header focus stop ${stops}: an outline must be drawn`).not.toBe("none");
      expect(drawn.color, `header focus stop ${stops}: the outline takes --design-on-frame`).toBe(onFrame);
    }
    await page.keyboard.press("Tab");
  }
  expect(stops, "the header holds focus stops").toBeGreaterThan(0);
  const toggler = page.locator("button.main-menu--navigation-toggler").first();
  await toggler.focus();
  await expect(toggler, "the sidebar toggler draws its outline in --design-link").toHaveCSS("outline-color", link);
});

test("design: the login page takes the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(ssoEnabled, "with sso oauth2-proxy sends every request to the identity provider");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/login`);
    await shown(LOGIN_FORM)(page);
    await assertToken(page, "body", "background-color", "--design-surface-1", `login ${mode}`);
    await assertToken(page, LOGIN_FORM, "background-color", "--design-surface-2", `login card ${mode}`);
    await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary", `login submit ${mode}`);
    await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `login submit ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [LOGIN_SUBMIT, `${LOGIN_FORM} label`], "openproject login");
});

test("design: administration tiles and disabled fields take the palette instead of upstream literals", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/admin`);
    await shown(".menu-blocks--container .menu-block")(page);
    await assertToken(page, ".menu-blocks--container .menu-block", "background-color", "--design-surface-2", `admin tile ${mode}`);
    await gotoOnion(page, `${base}/my/account`);
    await shown(`${CONTENT} form`)(page);
    await assertToken(page, `${CONTENT} form input.FormControl-input:is([readonly], [disabled])`, "background-color", "--design-surface-3", `read-only field ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: a theme picked in the interface settings is respected and mirrored", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.emulateMedia({ colorScheme: "light" });
  await signIn(page);
  const html = page.locator("html");
  const surface = () => tokenValue(page, "--design-surface-1", "background-color");
  try {
    await pickTheme(page, "sync_with_os");
    await gotoOnion(page, `${base}/my/page`);
    await expect(html, "sync with OS hands the mode to the browser").not.toHaveAttribute("data-design-theme");
    const lightSurface = await surface();
    await pickTheme(page, "dark");
    await gotoOnion(page, `${base}/my/page`);
    await expect(page.locator("body")).toHaveAttribute("data-color-mode", "dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(await surface(), "a dark pick switches the tokens while the browser prefers light").not.toBe(lightSurface);
    await assertToken(page, HEADER, "background-color", "--design-frame", "header with a dark pick");
  } finally {
    await pickTheme(page, "sync_with_os");
  }
});

test("design: header shows the generated logo and the tab the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl, "logo replacement is disabled for this role");
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await shown(LOGO)(page);
  await expect(page.locator(LOGO)).toHaveCSS("background-image", `url("${logoUrl}")`);
  const box = await page.locator(LOGO).boundingBox();
  expect(box.width, "the header shows the wide lockup").toBeGreaterThan(box.height * 2);
  if (title) await expect(page).toHaveTitle(new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  await page.setViewportSize({ width: 390, height: 844 });
  await gotoOnion(page, `${base}/my/page`);
  await expect(page.locator(`${HEADER} a.op-logo--icon`)).toHaveCSS("background-image", `url("${iconUrl}")`);
});

test("design: every image the role stylesheet references is served", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const sheet = await page.locator("link[href*='/roles/web-app-openproject/'][href*='style.css']").first().getAttribute("href");
  const css = await (await apiGetOnion(page.request, sheet)).text();
  const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
    .filter((target) => !target.startsWith("data:"))
    .map((target) => new URL(target, sheet).href);
  expect(targets.length, "the role stylesheet references images").toBeGreaterThan(0);
  for (const target of targets) {
    const served = await apiGetOnion(page.request, target);
    expect(`${served.status()} ${served.headers()["content-type"]}`, `${target} must be served as an image`).toMatch(/^200 image\//);
  }
});

test("design: gallery of login, projects, work packages, my account and administration", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(1_500_000));
  const failures = [];
  if (!ssoEnabled) {
    const guest = await page.context().browser().newContext({ ignoreHTTPSErrors: true });
    try {
      await captureDesignGallery(await guest.newPage(), guestViews());
    } catch (error) {
      failures.push(error.message);
    } finally {
      await guest.close();
    }
  }
  await signIn(page);
  await captureDesignGallery(page, signedInViews()).catch((error) => failures.push(error.message));
  expect(failures, failures.join("\n")).toEqual([]);
});

function guestViews() {
  return [
    { name: "login", url: `${base}/login`, prepare: shown(LOGIN_FORM) },
    {
      name: "login-focus",
      url: `${base}/login`,
      prepare: async (page) => {
        await shown(LOGIN_USER)(page);
        await page.locator(LOGIN_USER).focus();
      },
    },
    { name: "lost-password", url: `${base}/account/lost_password`, prepare: shown(`${CONTENT} form`) },
    { name: "register", url: `${base}/account/register`, prepare: shown(`${CONTENT} form`) },
  ];
}

function signedInViews() {
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  return [
    view("home", "/", CONTENT),
    view("my-page", "/my/page", CONTENT),
    view("projects", "/projects", `${CONTENT} table`),
    view("project-overview", "/projects/demo-project", CONTENT),
    view("work-packages", "/projects/demo-project/work_packages", CONTENT),
    view("work-package-new", "/projects/demo-project/work_packages/new", CONTENT),
    view("gantt", "/projects/demo-project/gantt", CONTENT),
    view("boards", "/projects/demo-project/boards", CONTENT),
    view("backlogs", "/projects/your-scrum-project/backlogs", CONTENT),
    view("wiki", "/projects/demo-project/wiki", CONTENT),
    view("notifications", "/notifications", CONTENT),
    view("my-account", "/my/account", `${CONTENT} form`),
    view("my-interface", "/my/interface", THEME_SELECT),
    view("admin", "/admin", CONTENT),
    view("admin-users", "/users", `${CONTENT} table`),
    view("admin-general", "/admin/settings/general", `${CONTENT} form`),
    view("admin-design", "/admin/design", CONTENT),
    view("admin-types", "/types", `${CONTENT} table`),
    view("project-settings", "/projects/demo-project/settings/general", `${CONTENT} form`),
    {
      name: "help-menu",
      url: `${base}/my/page`,
      prepare: async (page) => {
        await shown(HEADER)(page);
        await page.locator("#op-app-header--help-menu-button").click();
        const menu = page.locator("anchored-position:popover-open [role='menu']").first();
        await expect(menu).toBeVisible({ timeout: resolveTimeout(10_000) });
        await expect.poll(() => menu.evaluate((element) => element.getAnimations({ subtree: true }).length), { timeout: resolveTimeout(5_000) }).toBe(0);
      },
    },
  ];
}
