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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const designTitle = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const schemeName = decodeDotenvQuotedValue(process.env.DESIGN_SCHEME_NAME || "");

const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const SCHEME = "infinito";
const SCHEME_SHEET = "/wp-content/infinito-design/admin.css";
const LATE_SHEETS = ["/wp-content/infinito-design/extras.css", "/wp-content/infinito-design/editor.css"];
const SITE_BAR_SHEET = "/wp-content/infinito-design/admin-bar.css";
const SIGN_IN_SHEET = "/wp-content/infinito-design/login.css";
const SITE_TITLE = "header .wp-block-site-title a";
const SITE_LOGO = "footer .wp-block-site-logo img";
const POST_TITLE = ".wp-block-post-title";
const COMMENT_SUBMIT = "#commentform #submit";
const GLOBAL_STYLES = "#global-styles-inline-css";
const SIGN_IN_FORM = "#loginform";
const SIGN_IN_SUBMIT = "#wp-submit";
const SIGN_IN_LOGO = ".login h1 a";
const ADMIN_BAR = "#wpadminbar";
const ADMIN_BAR_ENTRY = "#wp-admin-bar-site-name > .ab-item";
const ADMIN_MENU = "#adminmenu";
const ADMIN_MENU_ENTRY = "#adminmenu li.menu-top:not(.wp-has-current-submenu):not(.current) > a.menu-top";
const ADMIN_MENU_CURRENT = "#adminmenu li.wp-has-current-submenu > a.wp-has-current-submenu";
const ADMIN_HEADING = ".wrap h1";
const ADMIN_PRIMARY = "#submit.button-primary";
const LIST_TABLE = ".wp-list-table";
const LIST_ROW = ".wp-list-table tbody tr";
const EDITOR_CANVAS = "iframe[name='editor-canvas']";

function style(page, selector, property, pseudo) {
  return page
    .locator(selector)
    .first()
    .evaluate((element, [name, part]) => getComputedStyle(element, part).getPropertyValue(name), [property, pseudo]);
}

async function inEachMode(page, check) {
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await check(mode);
  }
  await page.emulateMedia({ colorScheme: null });
}

async function shown(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
}

exports.register = function (shared) {
  const base = shared.env.wpBaseUrl;

  async function openAdmin(page, path, selector) {
    await gotoOnion(page, `${base}/wp-admin/${path}`);
    await shown(page, selector);
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base}/`);
    await shown(page, SITE_TITLE);
    await assertDesignTokens(page, "wordpress");
  });

  test("design: the site takes surface, text and the primary action from the global styles", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base}/hello-world/`);
    await shown(page, POST_TITLE);
    expect(
      await page.locator(GLOBAL_STYLES).evaluate((sheet) => sheet.textContent),
      "the global styles of the theme carry the tokens as preset values",
    ).toContain("--wp--preset--color--base: var(--design-surface-1)");
    await inEachMode(page, async (mode) => {
      await assertToken(page, "body", "background-color", "--design-surface-1", `site page ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `site text ${mode}`);
      await assertToken(page, POST_TITLE, "color", "--design-text", `site heading ${mode}`);
      await assertToken(page, COMMENT_SUBMIT, "background-color", "--design-primary", `site primary action ${mode}`);
      await assertToken(page, COMMENT_SUBMIT, "color", "--design-on-primary", `site primary action text ${mode}`);
      await assertToken(page, "#commentform #comment", "border-top-color", "--design-border-strong", `site field ${mode}`);
    });
    await assertLightAndDark(page, POST_TITLE, "wordpress site");
    await assertReadable(page, [SITE_TITLE, POST_TITLE, COMMENT_SUBMIT, ".wp-block-post-content p"], "wordpress site");
  });

  test("design: title, site icon and site logo are the corporate ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!designTitle, "the title replacement is disabled for this role");
    await gotoOnion(page, `${base}/`);
    await shown(page, SITE_TITLE);
    await expect(page.locator(SITE_TITLE)).toHaveText(designTitle);
    await expect(page).toHaveTitle(new RegExp(designTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    await expect(page.locator("link[rel='icon']").first(), "the site icon is the corporate one").toHaveAttribute(
      "href",
      /\/wp-content\/uploads\/.*infinito-site-icon-/,
    );
    await expect(page.locator(SITE_LOGO), "the footer shows the corporate site logo").toHaveAttribute(
      "src",
      /\/wp-content\/uploads\/.*infinito-site-logo-/,
    );
    const box = await page.locator(SITE_LOGO).evaluate((image) => ({ natural: image.naturalWidth, width: image.width, height: image.height }));
    expect(box.natural, "the site logo loads").toBeGreaterThan(0);
    expect(box.width, "the site logo fills its square box").toBe(box.height);
  });

  test("design: the administrator signs in through the WordPress form when no identity provider is deployed", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(isServiceEnabled("sso"), "with sso the sign-in page redirects to the identity provider");
    await shared.wpAdminLogin(page);
    await openAdmin(page, "index.php", ADMIN_BAR);
    await expect(page.locator("#wp-admin-bar-my-account")).toBeVisible();
  });

  test("design: the administration takes frame, surfaces, dividers and the primary action from the corporate color scheme", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await shared.wpAdminLogin(page);
    await openAdmin(page, "edit.php", LIST_ROW);
    await expect(page.locator("body"), "the account is on the corporate admin color scheme").toHaveClass(new RegExp(`admin-color-${SCHEME}`));
    await expect(page.locator("#colors-css"), "the color scheme loads its stylesheet from WordPress").toHaveAttribute(
      "href",
      new RegExp(SCHEME_SHEET.replace(/[.]/g, "\\.")),
    );
    for (const sheet of LATE_SHEETS) {
      await expect(page.locator(`head link[href*='${sheet}']`), `the scheme links ${sheet} at the end of the head`).toHaveCount(1);
    }
    await inEachMode(page, async (mode) => {
      await assertToken(page, "body", "background-color", "--design-surface-1", `admin page ${mode}`);
      await assertToken(page, ADMIN_BAR, "background-color", "--design-frame", `admin bar ${mode}`);
      await assertToken(page, ADMIN_BAR_ENTRY, "color", "--design-on-frame", `admin bar entry ${mode}`);
      await assertToken(page, ADMIN_MENU, "background-color", "--design-frame", `admin menu ${mode}`);
      await assertToken(page, ADMIN_MENU_ENTRY, "color", "--design-on-frame", `admin menu entry ${mode}`);
      await assertToken(page, ADMIN_MENU_CURRENT, "background-color", "--design-frame-active", `current admin menu entry ${mode}`);
      await assertToken(page, ADMIN_MENU_CURRENT, "color", "--design-on-frame", `current admin menu entry text ${mode}`);
      await assertToken(page, LIST_TABLE, "background-color", "--design-surface-2", `list table ${mode}`);
      await assertToken(page, LIST_TABLE, "border-top-color", "--design-border", `list table border ${mode}`);
      await assertToken(page, `${LIST_TABLE} thead th`, "border-bottom-color", "--design-border", `list table head divider ${mode}`);
      await assertToken(page, ADMIN_HEADING, "color", "--design-text", `admin heading ${mode}`);
      await assertToken(page, `${LIST_ROW} a.row-title`, "color", "--design-link", `admin link ${mode}`);
    });
    await page.locator(ADMIN_MENU_ENTRY).first().hover();
    await inEachMode(page, async (mode) => {
      await assertToken(page, `${ADMIN_MENU} li.menu-top:hover`, "background-color", "--design-frame-hover", `hovered admin menu entry ${mode}`);
    });
    await assertLightAndDark(page, ADMIN_HEADING, "wordpress administration");
    await assertReadable(
      page,
      [ADMIN_HEADING, `${LIST_ROW} a.row-title`, `${LIST_TABLE} thead th a`, ADMIN_MENU_ENTRY, ADMIN_MENU_CURRENT, ADMIN_BAR_ENTRY, ".subsubsub a"],
      "wordpress administration",
    );

    await openAdmin(page, "options-discussion.php", "#default_comment_status");
    await inEachMode(page, async (mode) => {
      await assertToken(page, ADMIN_PRIMARY, "background-color", "--design-primary", `admin primary action ${mode}`);
      await assertToken(page, ADMIN_PRIMARY, "color", "--design-on-primary", `admin primary action text ${mode}`);
      await assertToken(page, "input[type='checkbox']:checked", "background-color", "--design-primary", `checked box ${mode}`);
      expect(
        await style(page, "input[type='checkbox']:checked", "background-color", "::before"),
        `the check mark of a checked box takes --design-on-primary (${mode})`,
      ).toBe(await tokenValue(page, "--design-on-primary", "background-color"));
      await assertToken(page, "#comment_max_links", "border-top-color", "--design-border-strong", `admin field ${mode}`);
      await assertToken(page, "#comment_max_links", "background-color", "--design-surface-2", `admin field ${mode}`);
    });
    await assertReadable(page, [ADMIN_PRIMARY, ".form-table th", ".form-table label"], "wordpress settings");

    await openAdmin(page, "profile.php", "#color-picker");
    const choice = page.locator(`#color-picker .color-option:has(input[value='${SCHEME}'])`);
    await expect(choice.locator("input[name='admin_color']"), "the profile shows the corporate scheme as the account's choice").toBeChecked();
    await expect(choice.locator("label"), "the corporate scheme carries the platform name").toHaveText(schemeName);

    await gotoOnion(page, `${base}/`);
    await shown(page, ADMIN_BAR);
    await inEachMode(page, async (mode) => {
      await assertToken(page, ADMIN_BAR, "background-color", "--design-frame", `admin bar on the site ${mode}`);
      await assertToken(page, ADMIN_BAR_ENTRY, "color", "--design-on-frame", `admin bar entry on the site ${mode}`);
    });
  });

  test("design: every focus stop inside the admin menu draws its indicator in the frame text color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await shared.wpAdminLogin(page);
    await openAdmin(page, "index.php", ADMIN_MENU);
    const onFrame = await tokenValue(page, "--design-on-frame", "outline-color");
    await page.locator(`${ADMIN_MENU} a.menu-top`).first().focus();
    const stops = [];
    for (let index = 0; index < 40; index += 1) {
      const stop = await page.evaluate(() => {
        const element = document.activeElement;
        if (!element.closest("#adminmenuwrap")) return null;
        const computed = getComputedStyle(element);
        return { name: element.textContent.trim().slice(0, 24), style: computed.outlineStyle, color: computed.outlineColor };
      });
      if (!stop) break;
      stops.push(stop);
      await page.keyboard.press("Tab");
    }
    expect(stops.length, "the Tab walk visits the admin menu").toBeGreaterThan(5);
    for (const stop of stops) {
      expect(`${stop.style} ${stop.color}`, `focus stop '${stop.name}' draws its outline in --design-on-frame`).toBe(`solid ${onFrame}`);
    }
  });

  test("design: the sign-in page takes card, text, logo and the primary action from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(isServiceEnabled("sso"), "with sso the sign-in page redirects to the identity provider");
    await gotoOnion(page, `${base}/wp-login.php`);
    await shown(page, SIGN_IN_SUBMIT);
    await expect(page.locator("body")).toHaveClass(new RegExp(`admin-color-${SCHEME}`));
    await expect(page.locator(`link[href*='${SIGN_IN_SHEET}']`), "WordPress links the corporate sign-in stylesheet").toHaveCount(1);
    await page.locator("#user_login").focus();
    await inEachMode(page, async (mode) => {
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in page ${mode}`);
      await assertToken(page, SIGN_IN_FORM, "background-color", "--design-surface-2", `sign-in card ${mode}`);
      await assertToken(page, SIGN_IN_FORM, "border-top-color", "--design-border", `sign-in card border ${mode}`);
      await assertToken(page, `${SIGN_IN_FORM} label`, "color", "--design-text", `sign-in label ${mode}`);
      await assertToken(page, "#user_pass", "border-top-color", "--design-border-strong", `sign-in field ${mode}`);
      await assertToken(page, "#user_login:focus", "border-top-color", "--design-link", `focused sign-in field ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary", `sign-in primary action ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "color", "--design-on-primary", `sign-in primary action text ${mode}`);
    });
    await assertLightAndDark(page, `${SIGN_IN_FORM} label`, "wordpress sign-in");
    await assertReadable(page, [`${SIGN_IN_FORM} label`, SIGN_IN_SUBMIT, "#nav a", "#backtoblog a"], "wordpress sign-in");
    await expect(page.locator(SIGN_IN_LOGO), "the logo links to the site").toHaveAttribute("href", new RegExp(`^${base}/?$`));
    if (designTitle) await expect(page.locator(SIGN_IN_LOGO)).toHaveText(designTitle);
    expect(await style(page, SIGN_IN_LOGO, "background-image"), "the sign-in page shows the corporate site logo").toMatch(
      /\/wp-content\/uploads\/.*infinito-site-logo-/,
    );
  });

  test("design: the editor canvas loads the design tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await shared.wpAdminLogin(page);
    await openAdmin(page, "post-new.php", EDITOR_CANVAS);
    const canvas = page.frameLocator(EDITOR_CANVAS);
    await expect(canvas.locator(".editor-styles-wrapper")).toBeVisible({ timeout: resolveTimeout(10_000) });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".editor-header", "background-color", "--design-surface-2", `editor header ${mode}`);
      await assertToken(page, ".editor-document-bar__post-title", "color", "--design-text", `editor document title ${mode}`);
      const outer = await tokenValue(page, "--design-surface-1", "background-color");
      await expect
        .poll(() => canvas.locator(".editor-styles-wrapper").evaluate((element) => getComputedStyle(element).backgroundColor), {
          message: `the editor canvas paints --design-surface-1 in ${mode} mode`,
          timeout: resolveTimeout(10_000),
        })
        .toBe(outer);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: every image the corporate stylesheets reference is served", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    let references = 0;
    for (const path of [SCHEME_SHEET, ...LATE_SHEETS, SITE_BAR_SHEET, SIGN_IN_SHEET]) {
      const sheet = `${base}${path}`;
      const response = await apiGetOnion(page.request, sheet);
      expect(response.status(), `${sheet} is served`).toBe(200);
      const css = await response.text();
      const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
        .filter((target) => !target.startsWith("data:"))
        .map((target) => new URL(target, sheet).href);
      references += targets.length;
      for (const target of targets) {
        const served = await apiGetOnion(page.request, target);
        expect(`${served.status()} ${served.headers()["content-type"]}`, `${target} is served as an image`).toMatch(/^200 image\//);
      }
    }
    expect(references, "the corporate stylesheets reference images").toBeGreaterThan(0);
  });

  const view = (name, url, selector, extra) => ({
    name,
    url,
    prepare: async (page) => {
      await shown(page, selector);
      if (extra) await extra(page);
    },
  });
  const admin = (name, path, selector, extra) => view(name, `${base}/wp-admin/${path}`, selector, extra);

  async function firstPublished(page, type) {
    const response = await apiGetOnion(page.request, `${base}/wp-json/wp/v2/${type}?per_page=1&orderby=id&order=asc&_fields=id,link,title`);
    const [entry] = await response.json();
    return entry;
  }

  async function seedShowcase(page) {
    const nonce = await (await apiGetOnion(page.request, `${base}/wp-admin/admin-ajax.php?action=rest-nonce`)).text();
    const headers = { "X-WP-Nonce": nonce };
    const seeds = {
      posts: { title: "Design showcase", content: "<!-- wp:paragraph --><p>A post for the design gallery.</p><!-- /wp:paragraph -->", status: "publish" },
      pages: { title: "Design showcase page", content: "<!-- wp:paragraph --><p>A page for the design gallery.</p><!-- /wp:paragraph -->", status: "publish" },
    };
    for (const [type, data] of Object.entries(seeds)) {
      if (await firstPublished(page, type)) continue;
      const created = await apiFetchOnion(page.request, `${base}/wp-json/wp/v2/${type}`, { method: "POST", headers, data });
      expect(created.status(), `a showcase entry is created under ${type}`).toBe(201);
    }
    const closed = { welcomeGuide: false, welcomeGuideStyles: false, welcomeGuidePage: false, welcomeGuideTemplate: false };
    const preferences = await apiFetchOnion(page.request, `${base}/wp-json/wp/v2/users/me`, {
      method: "POST",
      headers,
      data: { meta: { persisted_preferences: { "core/edit-post": closed, "core/edit-site": closed, _modified: new Date().toISOString() } } },
    });
    expect(preferences.status(), "the welcome guides of the editors are stored as closed").toBe(200);
  }

  const visitorViews = (post, entry) => [
    view("home", `${base}/`, SITE_TITLE),
    view("post-single", post.link, POST_TITLE),
    view("page-single", entry.link, POST_TITLE),
    view("search-results", `${base}/?s=${encodeURIComponent(post.title.rendered.split(/\s+/)[0])}`, ".wp-block-query-title"),
    view("not-found", `${base}/design-gallery-missing/`, ".wp-block-search__input"),
  ];

  const signInViews = () => [
    view("sign-in", `${base}/wp-login.php`, SIGN_IN_SUBMIT),
    view("sign-in-rejected", `${base}/wp-login.php?view=rejected`, SIGN_IN_SUBMIT, async (page) => {
      for (const field of ["#user_login", "#user_pass"]) {
        await expect(page.locator(field)).toBeEditable({ timeout: resolveTimeout(10_000) });
        await page.locator(field).fill("design-gallery-visitor");
      }
      await page.locator(SIGN_IN_SUBMIT).click();
      await shown(page, "#login_error");
    }),
    view("lost-password", `${base}/wp-login.php?action=lostpassword`, "#lostpasswordform"),
  ];

  async function canvasLoaded(page) {
    if (page.viewportSize().width < 783) return;
    await expect(page.frameLocator(EDITOR_CANVAS).locator(POST_TITLE).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  }

  const adminViews = (post) => [
    admin("admin-dashboard", "index.php", "#dashboard-widgets-wrap"),
    admin("admin-posts", "edit.php", LIST_ROW),
    admin("admin-posts-quick-edit", "edit.php?view=quick-edit", LIST_ROW, async (page) => {
      await page.locator("#the-list button.editinline").first().dispatchEvent("click");
      await shown(page, "#the-list tr.inline-edit-row");
    }),
    admin("admin-post-edit", `post.php?post=${post.id}&action=edit`, EDITOR_CANVAS, async (page) => {
      await page.frameLocator(EDITOR_CANVAS).locator(".editor-styles-wrapper").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
    }),
    admin("admin-media", "upload.php?mode=list", LIST_TABLE),
    admin("admin-pages", "edit.php?post_type=page", LIST_ROW),
    admin("admin-comments", "edit-comments.php", "#the-comment-list"),
    admin("admin-categories", "edit-tags.php?taxonomy=category", "#addtag"),
    admin("admin-themes", "themes.php", ".theme-browser .theme"),
    admin("admin-site-editor", "site-editor.php", ".edit-site-layout", canvasLoaded),
    admin("admin-site-editor-styles", "site-editor.php?p=%2Fstyles", ".edit-site-layout", canvasLoaded),
    admin("admin-plugins", "plugins.php", "#the-list tr"),
    admin("admin-users", "users.php", "#the-list tr"),
    admin("admin-user-new", "user-new.php", "#createuser"),
    admin("admin-profile", "profile.php", "#color-picker"),
    admin("admin-tools", "tools.php", ADMIN_HEADING),
    admin("admin-export", "export.php", "#export-filters"),
    admin("admin-site-health", "site-health.php?tab=debug", ".health-check-accordion"),
    admin("admin-settings-general", "options-general.php", "#blogname"),
    admin("admin-settings-reading", "options-reading.php", "#posts_per_page"),
    admin("admin-settings-discussion", "options-discussion.php", "#default_comment_status"),
    admin("admin-settings-permalinks", "options-permalink.php", "#permalink_structure"),
    admin("admin-settings-privacy", "options-privacy.php", ".privacy-settings-header"),
    admin("admin-menu-open", "index.php?view=menu", ADMIN_BAR, async (page) => {
      if (page.viewportSize().width < 783) {
        await page.locator("#wp-admin-bar-menu-toggle a").click();
        await shown(page, "#wpwrap.wp-responsive-open");
      } else {
        await page.locator("#menu-settings > a").hover();
        await shown(page, "#menu-settings .wp-submenu");
      }
    }),
  ];

  test("design: gallery of site, sign-in and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(840_000));

    await shared.wpAdminLogin(page);
    await seedShowcase(page);
    const post = await firstPublished(page, "posts");
    const entry = await firstPublished(page, "pages");
    await page.context().clearCookies();

    const failures = [];
    const capture = async (views) => {
      try {
        await captureDesignGallery(page, views);
      } catch (error) {
        failures.push(error.message);
      }
    };
    await capture(visitorViews(post, entry));
    if (!isServiceEnabled("sso")) await capture(signInViews());
    await shared.wpAdminLogin(page);
    await capture(adminViews(post));
    expect(failures, failures.join("\n")).toEqual([]);
  });

  test("design: the media grid renders its runtime templates and the theme browser opens without a script error", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    const errors = [];
    page.on("console", (message) => {
      if (message.type() === "error" && !/inline event handler/.test(message.text())) errors.push(message.text().slice(0, 300));
    });
    page.on("pageerror", (error) => errors.push(String(error).slice(0, 300)));
    await shared.wpAdminLogin(page);
    await openAdmin(page, "themes.php", ".theme-browser .theme");
    await openAdmin(page, "upload.php?mode=grid", ".attachments-browser .attachment");
    await inEachMode(page, async (mode) => {
      await assertToken(page, ".attachments-browser .attachment-preview", "background-color", "--design-surface-3", `media tile ${mode}`);
    });
    expect(errors, "the media grid and the theme browser raise no script error and no eval violation").toEqual([]);
  });
};
