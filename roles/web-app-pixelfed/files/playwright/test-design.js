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
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const brandUrl = decodeDotenvQuotedValue(process.env.DESIGN_BRAND_URL);
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);

const MODES = ["light", "dark"];
const NAV = "nav.metro-nav";
const BRAND_IMG = `${NAV} .navbar-brand img`;
const USER_MENU = "#navbarDropdown";
const MENU_PANEL = `${NAV} .dropdown-menu.show`;
const SIDEBAR_CARD = ".sidebar-component .card";
const COMPOSE_BUTTON = ".sidebar-component .btn-primary";
const LOGIN_EMAIL = "input#email[name='email']";
const LOGIN_PASSWORD = "input#password[name='password']";
const LOGIN_CARD = "main#content .card";
const LOGIN_SUBMIT = "main#content form button[type='submit'].btn-primary";
const SETTINGS_NAV = ".settings-nav";
const ADMIN_HEADER = ".main-content .header.bg-primary";
const ADMIN_TOPBAR = "nav.navbar-top";
const ADMIN_LOGO = ".sidenav .navbar-brand-img";
const MODAL = ".modal-content .ui-menu";
const THEME_KEY = "pf_m2s.color-scheme";
const CUSTOM_CSS_BEGIN = "/* infinito-design:begin */";
const SHOWCASE = "Design showcase #designshowcase";
const SHOWCASE_POSTS = 3;

let session = null;

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   page: Playwright page on which an overlay opened.
 *   selector: the overlay panel; it must be visible, no longer animating and fully opaque.
 */
async function opaque(page, selector) {
  await shown(selector)(page);
  await expect
    .poll(
      () =>
        page
          .locator(selector)
          .first()
          .evaluate((element) => {
            const panel = element.closest(".modal-content, .dropdown-menu") || element;
            const layer = element.closest(".modal") || panel;
            return (
              layer.getAnimations({ subtree: true }).every((animation) => animation.playState !== "running") &&
              getComputedStyle(layer).opacity === "1"
            );
          }),
      { timeout: resolveTimeout(10_000), message: `${selector} must have finished opening` },
    )
    .toBe(true);
}

async function openUserMenu(page) {
  await shown(USER_MENU)(page);
  await page.locator(USER_MENU).click();
  await opaque(page, MENU_PANEL);
}

async function openAppearance(page) {
  await openUserMenu(page);
  await page.locator(`${MENU_PANEL} a.nav-link`, { has: page.locator(".fa-brush") }).click();
  await opaque(page, MODAL);
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the platform administrator, through the identity provider when sso is on and through Pixelfed's own form otherwise. Later calls reuse the first session.
 *   shared: the spec's shared state from `_shared.js`.
 */
async function signIn(page, shared) {
  const base = shared.env.pixelfedBaseUrl.replace(/\/$/, "");
  if (session) {
    await page.context().addCookies(session);
    await gotoOnion(page, `${base}/i/web`);
  } else if (shared.env.oidcEnabled) {
    await shared.loginToPixelfed(page, shared.loginScenarios.find((scenario) => scenario.label === "administrator"));
    await gotoOnion(page, `${base}/i/web`);
  } else {
    await gotoOnion(page, `${base}/login`);
    await expect(page.locator(LOGIN_EMAIL)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(LOGIN_EMAIL).fill(adminEmail);
    await expect(page.locator(LOGIN_PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(LOGIN_PASSWORD).fill(adminPassword);
    await page.locator(LOGIN_SUBMIT).click();
  }
  await expect(page.locator(NAV)).toBeVisible({ timeout: resolveTimeout(30_000) });
  if (!session) session = await page.context().cookies();
}

/**
 * Args:
 *   page: signed-in Playwright page on the SPA; the request runs inside it with the session cookie and the CSRF token of the page.
 *   method: HTTP verb.
 *   path: path below the Pixelfed origin.
 *   body: list of [name, value] form entries, the value "__png__" standing for a generated image, or null.
 *
 * Returns:
 *   The HTTP status and the parsed JSON answer.
 */
async function api(page, method, path, body = null) {
  return page.evaluate(
    async ([verb, url, entries]) => {
      const headers = {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-TOKEN": document.querySelector("meta[name='csrf-token']").content,
        Accept: "application/json",
      };
      let payload;
      if (entries) {
        payload = new FormData();
        for (const [name, value] of entries) {
          if (value === "__png__") {
            const canvas = document.createElement("canvas");
            canvas.width = 640;
            canvas.height = 640;
            const context = canvas.getContext("2d");
            context.fillStyle = getComputedStyle(document.body).getPropertyValue("--design-primary");
            context.fillRect(0, 0, 640, 640);
            context.fillStyle = getComputedStyle(document.body).getPropertyValue("--design-surface-2");
            context.fillRect(160, 160, 320, 320);
            payload.append(name, await new Promise((resolve) => canvas.toBlob(resolve, "image/png")), "showcase.png");
          } else {
            payload.append(name, value);
          }
        }
      }
      const response = await fetch(url, { method: verb, headers, body: payload });
      return { status: response.status, data: await response.json().catch(() => null) };
    },
    [method, path, body],
  );
}

/**
 * Args:
 *   page: signed-in Playwright page on the SPA; showcase posts of the administrator get created until there are SHOWCASE_POSTS of them.
 *
 * Returns:
 *   The administrator's profile id and the id of the first showcase post.
 */
async function seedShowcase(page) {
  const me = await page.evaluate(() => window._sharedData.user.id);
  const listed = await api(page, "GET", `/api/v1/accounts/${me}/statuses?limit=40`);
  expect(listed.status, "the session must list the administrator's posts").toBe(200);
  const existing = listed.data.filter((status) => (status.content_text || status.content || "").includes("designshowcase"));
  for (let index = existing.length; index < SHOWCASE_POSTS; index += 1) {
    const media = await api(page, "POST", "/api/v1/media", [["file", "__png__"]]);
    expect(media.status, "uploading a showcase image").toBeLessThan(300);
    const created = await api(page, "POST", "/api/v1/statuses", [
      ["status", `${SHOWCASE} ${index + 1}`],
      ["media_ids[]", String(media.data.id)],
      ["visibility", "public"],
    ]);
    expect(created.status, "creating a showcase post").toBeLessThan(300);
    existing.push(created.data);
  }
  return { profileId: me, statusId: existing[existing.length - 1].id };
}

exports.register = function (shared) {
  const base = shared.env.pixelfedBaseUrl.replace(/\/$/, "");

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    await assertDesignTokens(page, "pixelfed");
  });

  test("design: the sign-in page takes surface, card, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(shared.env.oidcEnabled, "with sso the sign-in form belongs to the identity provider");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/login`);
      await shown(LOGIN_EMAIL)(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, LOGIN_CARD, "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await assertToken(page, LOGIN_PASSWORD, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, LOGIN_CARD, "pixelfed sign-in");
    await assertReadable(page, [LOGIN_SUBMIT, `${LOGIN_CARD} label`, `${LOGIN_CARD} a`], "pixelfed sign-in");
  });

  test("design: the guest landing follows the palette instead of its dark-only slate", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const card = ".landing-index-component .card";
    const domain = ".landing-index-component .server-header-domain";
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/`);
      await shown(domain)(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `landing ${mode}`);
      await assertToken(page, card, "background-color", "--design-surface-2", `landing card ${mode}`);
      await assertToken(page, domain, "color", "--design-text", `landing domain ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, card, "pixelfed landing");
    await assertReadable(page, [domain, ".landing-index-component .nav-menu .nav-link", { selector: ".server-admin .admin-card .username", optional: true }], "pixelfed landing");
  });

  test("design: Pixelfed's custom CSS setting carries the SPA variables, the role stylesheet none of them", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    const blocks = await page.locator("head style").evaluateAll((styles, begin) => styles.filter((style) => style.textContent.includes(begin)).length, CUSTOM_CSS_BEGIN);
    expect(blocks, "exactly one role block renders through uikit.custom.css").toBe(1);
    const sheet = await page.locator("link[href*='/roles/web-app-pixelfed/'][href*='style.css']").first().getAttribute("href");
    const css = await (await apiGetOnion(page.request, sheet)).text();
    expect(css, "the SPA variables belong to the in-house custom CSS").not.toMatch(/--(body-bg|card-bg|nav-bg)\s*:/);
  });

  test("design: the signed-in feed takes surfaces, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/i/web`);
      await shown(SIDEBAR_CARD)(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `feed ${mode}`);
      await assertToken(page, NAV, "background-color", "--design-surface-2", `navbar ${mode}`);
      await assertToken(page, SIDEBAR_CARD, "background-color", "--design-surface-2", `sidebar ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `feed ${mode}`);
      await assertToken(page, COMPOSE_BUTTON, "background-color", "--design-primary", `compose ${mode}`);
      await assertToken(page, COMPOSE_BUTTON, "color", "--design-on-primary", `compose ${mode}`);
      await page.locator(COMPOSE_BUTTON).hover();
      await assertToken(page, COMPOSE_BUTTON, "background-color", "--design-primary-hover", `hovered compose ${mode}`);
      await page.mouse.move(0, 0);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, SIDEBAR_CARD, "pixelfed feed");
    await assertReadable(page, [COMPOSE_BUTTON, `${NAV} .navbar-brand`, { selector: ".sidebar-component a.nav-link", optional: true }], "pixelfed feed");
  });

  test("design: the settings card divides with the border token and its submit reads on-primary", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    const card = "main#content .card.border";
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/settings/home`);
      await shown("input#name")(page);
      await assertToken(page, card, "border-top-color", "--design-border", `settings card ${mode}`);
      await assertToken(page, SETTINGS_NAV, "border-right-color", "--design-border", `settings navigation divider ${mode}`);
      await assertToken(page, card, "background-color", "--design-surface-2", `settings card ${mode}`);
      await assertToken(page, `${card} button[type='submit'].btn-primary`, "color", "--design-on-primary", `settings submit ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${SETTINGS_NAV} .nav-link`, `${card} label[for='name']`], "pixelfed settings");
  });

  test("design: the privacy settings panels follow the palette instead of their inline white", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    const section = "main#content .privacy-section";
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/settings/privacy`);
      await shown(section)(page);
      await assertToken(page, section, "background-color", "--design-surface-2", `privacy panel ${mode}`);
      await assertToken(page, `${section} .privacy-section-header`, "background-color", "--design-surface-3", `privacy panel header ${mode}`);
      await assertToken(page, section, "border-top-color", "--design-border", `privacy panel border ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${section} .privacy-section-header h5`, `${section} .privacy-description`, "main#content .privacy-links .btn"], "pixelfed privacy settings");
  });

  test("design: the provisioned administrator reaches the admin dashboard", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    const response = await gotoOnion(page, `${base}/i/admin/dashboard`);
    expect(page.url(), "the provisioned administrator must carry Pixelfed's admin flag").toContain("/i/admin/dashboard");
    expect(response.status()).toBe(200);
    await expect(page.locator(ADMIN_HEADER)).toBeVisible({ timeout: resolveTimeout(10_000) });
  });

  test("design: the admin top bar and header are the frame and keep their focus indicator", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    await page.setViewportSize({ width: 1440, height: 900 });
    await gotoOnion(page, `${base}/i/admin/dashboard`);
    await shown(ADMIN_HEADER)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ADMIN_TOPBAR, "background-color", "--design-frame", `admin top bar ${mode}`);
      await assertToken(page, ADMIN_HEADER, "background-color", "--design-frame", `admin header ${mode}`);
      await assertToken(page, "body", "background-color", "--design-surface-1", `admin page ${mode}`);
      await assertToken(page, ".main-content .card", "background-color", "--design-surface-2", `admin card ${mode}`);
      await assertToken(page, `${ADMIN_TOPBAR} .nav-link`, "color", "--design-on-frame", `admin top bar link ${mode}`);
      const outline = await tokenValue(page, "--design-on-frame", "outline-color");
      const inTopBar = () => page.evaluate((selector) => Boolean(document.activeElement.closest(selector)), ADMIN_TOPBAR);
      await page.locator("body").click({ position: { x: 1, y: 899 } });
      for (let presses = 0; presses < 60 && !(await inTopBar()); presses += 1) await page.keyboard.press("Tab");
      let stops = 0;
      for (; stops < 12; stops += 1) {
        if (!(await inTopBar())) break;
        const drawn = await page.evaluate(() => {
          const style = getComputedStyle(document.activeElement);
          return { color: style.outlineColor, style: style.outlineStyle, field: document.activeElement.matches("input, textarea, select") };
        });
        expect(drawn.style, `admin top bar focus stop ${stops} ${mode}: an outline must be drawn`).not.toBe("none");
        if (!drawn.field) expect(drawn.color, `admin top bar focus stop ${stops} ${mode}: the outline takes --design-on-frame`).toBe(outline);
        await page.keyboard.press("Tab");
      }
      expect(stops, `the admin top bar holds focus stops in ${mode} mode`).toBeGreaterThan(0);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".main-content .card", "pixelfed admin");
    await assertReadable(page, [`${ADMIN_HEADER} h6, ${ADMIN_HEADER} .h2, ${ADMIN_HEADER} .text-white`, ".main-content .card .text-muted"], "pixelfed admin");
  });

  test("design: admin table rows divide with the border token", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    await gotoOnion(page, `${base}/i/admin/users/list`);
    const cell = ".main-content table tbody tr td";
    await shown(cell)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, cell, "border-top-color", "--design-border", `admin user row ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [cell], "pixelfed admin users");
  });

  test("design: a theme picked in the Appearance dialog is respected and mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await signIn(page, shared);
    await gotoOnion(page, `${base}/i/web`);
    const html = page.locator("html");
    const surface = () => tokenValue(page, "--design-surface-1", "background-color");
    const lightSurface = await surface();
    await expect(html, "the palette follows the browser preference").not.toHaveAttribute("data-design-theme");
    try {
      await openAppearance(page);
      await page.locator(`${MODAL} .btn-group .btn`).nth(2).click();
      await expect(page.locator("body")).toHaveClass(/force-dark-mode/);
      await expect(html).toHaveAttribute("data-design-theme", "dark");
      expect(await surface(), "a dark pick must switch the tokens while the browser prefers light").not.toBe(lightSurface);
      await assertToken(page, "body", "background-color", "--design-surface-1", "feed after a dark pick");
    } finally {
      await page.evaluate((key) => window.localStorage.setItem(key, "system"), THEME_KEY);
    }
    await gotoOnion(page, `${base}/i/web`);
    await expect(html, "the system theme hands the mode back to the browser").not.toHaveAttribute("data-design-theme");
  });

  test("design: navbar, admin sidebar and tab show the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoUrl, "logo replacement is disabled for this role");
    await signIn(page, shared);
    await shown(BRAND_IMG)(page);
    await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    await expect(page.locator(BRAND_IMG)).toHaveCSS("content", `url("${logoUrl}")`);
    await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    await page.setViewportSize({ width: 1440, height: 900 });
    await gotoOnion(page, `${base}/i/admin/dashboard`);
    await shown(ADMIN_LOGO)(page);
    await expect(page.locator(ADMIN_LOGO)).toHaveCSS("content", `url("${brandUrl}")`);
    const box = await page.locator(ADMIN_LOGO).boundingBox();
    expect(box.width, "the admin sidebar shows the wide lockup").toBeGreaterThan(box.height * 3);
  });

  test("design: every image the role stylesheet references is served", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base}/`);
    const sheet = await page.locator("link[href*='/roles/web-app-pixelfed/'][href*='style.css']").first().getAttribute("href");
    const css = await (await apiGetOnion(page.request, sheet)).text();
    const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
      .filter((target) => !target.startsWith("data:"))
      .map((target) => new URL(target, sheet).href);
    expect(targets.length, "the role stylesheet references images").toBeGreaterThan(0);
    for (const target of targets) {
      const served = await apiGetOnion(page.request, target);
      expect(
        `${served.status()} ${served.headers()["content-type"]}`,
        `${target} must be served as an image; a relative url() resolves against the stylesheet on the CDN`,
      ).toMatch(/^200 image\//);
    }
  });

  test("design: gallery of landing, sign-in, feed, menus, settings and administration", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_500_000));
    const failures = [];
    const guest = await page.context().browser().newContext({ ignoreHTTPSErrors: true });
    try {
      await captureDesignGallery(await guest.newPage(), guestViews(base, shared.env.oidcEnabled));
    } catch (error) {
      failures.push(error.message);
    } finally {
      await guest.close();
    }
    await signIn(page, shared);
    const seeded = await seedShowcase(page);
    await captureDesignGallery(page, signedInViews(base, seeded)).catch((error) => failures.push(error.message));
    expect(failures, failures.join("\n")).toEqual([]);
  });
};

function guestViews(base, oidcEnabled) {
  const views = [
    { name: "landing", url: `${base}/`, prepare: shown(".landing-index-component .server-header") },
    { name: "about", url: `${base}/site/about`, prepare: shown("main#content h1") },
  ];
  if (oidcEnabled) return views;
  return views.concat([
    { name: "sign-in", url: `${base}/login`, prepare: shown(LOGIN_EMAIL) },
    {
      name: "sign-in-focus",
      url: `${base}/login`,
      prepare: async (page) => {
        await shown(LOGIN_EMAIL)(page);
        await page.locator(LOGIN_EMAIL).focus();
      },
    },
    { name: "password-reset", url: `${base}/password/reset`, prepare: shown("main#content input[type='email']") },
    { name: "forgot-email", url: `${base}/auth/forgot/email`, prepare: shown("main#content form") },
  ]);
}

function signedInViews(base, { profileId, statusId }) {
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  return [
    view("home-feed", "/i/web", `${NAV} .navbar-brand`),
    { name: "user-menu", url: `${base}/i/web`, prepare: openUserMenu },
    { name: "appearance", url: `${base}/i/web`, prepare: openAppearance },
    view("compose", "/i/web/compose", ".web-wrapper"),
    view("discover", "/i/web/discover", ".web-wrapper"),
    view("notifications", "/i/web/notifications", ".notification-metro-component"),
    view("profile", `/i/web/profile/${profileId}`, ".profile-timeline-component"),
    view("post", `/i/web/post/${statusId}`, ".post-timeline-component"),
    view("hashtag", "/i/web/hashtag/designshowcase", ".hashtag-component"),
    view("direct", "/i/web/direct", ".dms-page-component"),
    view("settings-account", "/settings/home", "input#name"),
    view("settings-privacy", "/settings/privacy", SETTINGS_NAV),
    view("settings-accessibility", "/settings/accessibility", SETTINGS_NAV),
    view("settings-media", "/settings/media", SETTINGS_NAV),
    view("settings-timeline", "/settings/timeline", SETTINGS_NAV),
    view("sudo-confirm", "/i/auth/sudo", "#sudoForm"),
    view("admin-dashboard", "/i/admin/dashboard", ADMIN_HEADER),
    view("admin-users", "/i/admin/users/list", ".main-content table"),
    view("admin-settings", "/i/admin/settings", ADMIN_HEADER),
    view("admin-custom-css", "/i/admin/settings/custom-css", "textarea#css"),
    view("admin-reports", "/i/admin/reports", ADMIN_HEADER),
    view("admin-hashtags", "/i/admin/hashtags/home", ADMIN_HEADER),
  ];
}
