const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
} = require("./design");
const {
  apiFetchOnion,
  apiGetOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.POSTMARKS_BASE_URL, "POSTMARKS_BASE_URL"));
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const adminKey = requireDotenvValue(process.env.POSTMARKS_ADMIN_KEY, "POSTMARKS_ADMIN_KEY");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");

const MODES = ["light", "dark"];
const READY = 10_000;
const BOOKMARK = ".bookmarks .bookmark";
const HEADLINE = `${BOOKMARK} .headline a`;
const SUBHEAD = `${BOOKMARK} .subhead`;
const MENU_LINK = ".header .menu a";
const LOGO = ".header .logo img";
const PASSWORD = ".login #password";
const LOGIN_SUBMIT = ".login button[type='submit']";
const EDIT_FORM = ".edit-bookmark form";
const SAVE = ".edit-bookmark button[type='submit']";
const TAG_ENTRY = "#tagEntry";
const CHIP = "#taggedList .tagged";
const SIGNED_IN = ".header .menu a[href='/admin']";
const FOOTER_ICONS = [".btn--feed img", ".btn--github img"];
const SHOWCASE_TAG = "designshowcase";
const SEED = Array.from({ length: 12 }, (_, index) => `design-showcase-${String(index + 1).padStart(2, "0")}`);

/**
 * Args:
 *   page: Playwright page that ends signed in as the Postmarks owner, through Keycloak when the proxy gates the site, otherwise through the native password form with the role's ADMIN_KEY.
 */
async function signIn(page) {
  await gotoOnion(page, `${base}/admin`);
  if (oidcIssuerUrl && page.url().startsWith(oidcIssuerUrl)) {
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
    await gotoOnion(page, `${base}/admin`);
  } else if ((await page.locator(PASSWORD).count()) > 0) {
    const password = page.locator(PASSWORD);
    await expect(password).toBeEditable({ timeout: resolveTimeout(READY) });
    await password.fill(adminKey);
    await page.locator(LOGIN_SUBMIT).click();
  }
  await expect(page.locator(SIGNED_IN)).toBeVisible({ timeout: resolveTimeout(READY) });
}

/**
 * Args:
 *   page: signed-in Playwright page; the twelve showcase bookmarks carrying the showcase tag are created when they are missing.
 *
 * Returns:
 *   The id of the first showcase bookmark.
 */
async function seed(page) {
  const listed = async () => {
    const response = await apiGetOnion(page.request, `${base}/tagged/${SHOWCASE_TAG}?raw=true&limit=100`);
    expect(response.ok(), "the tagged list answers").toBe(true);
    return (await response.json()).bookmarks || [];
  };
  const present = new Set((await listed()).map((bookmark) => bookmark.title));
  for (const [index, name] of SEED.entries()) {
    if (present.has(name)) continue;
    const created = await apiFetchOnion(page.request, `${base}/bookmark?raw=true`, {
      method: "POST",
      form: {
        url: `https://example.org/${name}`,
        title: name,
        description: `Seeded for the corporate design review, entry ${index + 1}.`,
        tags: JSON.stringify(index % 2 === 0 ? [SHOWCASE_TAG, "palette"] : [SHOWCASE_TAG, "layout"]),
      },
    });
    expect(created.status(), `seeding ${name}`).toBeLessThan(300);
  }
  const bookmarks = await listed();
  expect(bookmarks.length, "the showcase bookmarks exist").toBeGreaterThan(0);
  return bookmarks[0].id;
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY) });
  };
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${base}/about`);
    await assertDesignTokens(page, "postmarks");
  });

  test("design: page, header, bookmarks and links take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await seed(page);
    await gotoOnion(page, `${base}/`);
    await shown(BOOKMARK)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `text ${mode}`);
      await assertToken(page, HEADLINE, "color", "--design-link", `bookmark link ${mode}`);
      await assertToken(page, SUBHEAD, "color", "--design-text-muted", `bookmark meta ${mode}`);
      await assertToken(page, ".header", "border-bottom-color", "--design-border", `header divider ${mode}`);
      await assertToken(page, ".footer", "border-top-color", "--design-border", `footer divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".content", "postmarks page");
    await assertReadable(
      page,
      [
        HEADLINE,
        SUBHEAD,
        { selector: `${BOOKMARK} .description`, optional: true },
        { selector: ".tag-list a", optional: true },
        MENU_LINK,
        ".footer a",
        { selector: ".pagination .status", optional: true },
      ],
      "postmarks home",
    );
  });

  test("design: the feed and GitHub footer icons follow the text tone in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${base}/about`);
    for (const icon of FOOTER_ICONS) {
      await shown(icon)(page);
      for (const [mode, inverted] of [
        ["light", "0"],
        ["dark", "1"],
      ]) {
        await page.emulateMedia({ colorScheme: mode });
        await expect(page.locator(icon), `${icon} in ${mode} mode`).toHaveCSS(
          "filter",
          `brightness(0) invert(${inverted})`,
        );
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: forms take fields, primary action, chips and focus from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${base}/bookmark/new`);
    await shown(EDIT_FORM)(page);
    await page.locator(TAG_ENTRY).fill("palette");
    await page.locator(TAG_ENTRY).press("Enter");
    await shown(CHIP)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await page.mouse.move(0, 0);
      await assertToken(page, "#bookmark_url", "background-color", "--design-surface-2", `field ${mode}`);
      await assertToken(page, "#bookmark_url", "border-top-color", "--design-border-strong", `field border ${mode}`);
      await assertToken(page, CHIP, "border-top-color", "--design-border-strong", `tag chip border ${mode}`);
      await assertToken(page, SAVE, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, SAVE, "color", "--design-on-primary", `primary action text ${mode}`);
      await page.locator("#bookmark_url").focus();
      await assertToken(page, "#bookmark_url", "outline-color", "--design-link", `focused field ${mode}`);
      await page.locator(SAVE).hover();
      await assertToken(page, SAVE, "background-color", "--design-primary-hover", `hovered primary action ${mode}`);
    }
    await page.mouse.move(0, 0);
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${EDIT_FORM} label`, SAVE, "#bookmark_url"], "postmarks form");
  });

  test("design: tag operations and the empty search take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await seed(page);
    for (const [path, selector, token] of [
      [`/tagged/${SHOWCASE_TAG}`, ".tag-add", "--design-text-muted"],
      [`/tagged/${SHOWCASE_TAG}/palette`, ".bookmark .tags .tag-remove", "--design-danger"],
    ]) {
      await gotoOnion(page, `${base}${path}`);
      await shown(selector)(page);
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        await assertToken(page, selector, "color", token, `tag operation ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
      await assertReadable(page, [selector], "postmarks tag operation");
    }
    await gotoOnion(page, `${base}/search?query=zzznomatch`);
    await shown("p.error")(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "p.error", "color", "--design-danger", `search error ${mode}`);
      await assertToken(page, ".search button", "color", "--design-on-primary", `search action text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["p.error", ".search button"], "postmarks search");
  });

  test("design: logo, favicon and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!faviconUrl && !title && !logoUrl, "logo and title replacement are disabled for this role");
    await signIn(page);
    await gotoOnion(page, `${base}/about`);
    if (title) {
      await expect.poll(() => page.title(), { message: "the page carries the configured title" }).toMatch(new RegExp(`\\| ${title}$`));
      await expect(page.locator(".header .logo a")).toContainText(title);
    }
    if (faviconUrl) {
      await expect(page.locator("link[rel='icon']")).toHaveAttribute("href", faviconUrl);
    }
    if (logoUrl) {
      const logo = page.locator(LOGO);
      await expect(logo).toHaveCSS("content", `url("${logoUrl}")`);
      const box = await logo.boundingBox();
      expect(Math.round(box.height), "the header logo keeps the 96 px slot").toBe(96);
      expect(Math.round(box.width), "the header logo box is square").toBe(Math.round(box.height));
    }
  });

  test("design: every image the role stylesheet references is served", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${base}/about`);
    const sheet = await page.locator("link[href*='/roles/web-app-postmarks/'][href*='style.css']").first().getAttribute("href");
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

  function visitorViews(bookmarkId) {
    const views = [
      { name: "home", url: `${base}/`, prepare: shown(BOOKMARK) },
      { name: "about", url: `${base}/about`, prepare: shown(".content p") },
      { name: "search", url: `${base}/search`, prepare: shown("#query") },
      { name: "search-results", url: `${base}/search?query=showcase`, prepare: shown(BOOKMARK) },
      { name: "search-no-match", url: `${base}/search?query=zzznomatch`, prepare: shown("p.error") },
      { name: "tagged", url: `${base}/tagged/${SHOWCASE_TAG}`, prepare: shown(BOOKMARK) },
      { name: "tagged-combined", url: `${base}/tagged/${SHOWCASE_TAG}/palette`, prepare: shown(".tag-op") },
      { name: "bookmark", url: `${base}/bookmark/${bookmarkId}`, prepare: shown(".bookmark-permalink-title") },
    ];
    if (isServiceEnabled("sso")) return views;
    return [
      ...views,
      { name: "login", url: `${base}/login`, prepare: shown(PASSWORD) },
      {
        name: "login-focus",
        url: `${base}/login`,
        prepare: async (page) => {
          await shown(PASSWORD)(page);
          await page.locator(PASSWORD).focus();
        },
      },
    ];
  }

  function ownerViews(bookmarkId) {
    return [
      { name: "home-signed-in", url: `${base}/`, prepare: shown(SIGNED_IN) },
      { name: "home-page-two", url: `${base}/?offset=10`, prepare: shown(".pagination") },
      {
        name: "home-link-hover",
        url: `${base}/`,
        prepare: async (page) => {
          await shown(HEADLINE)(page);
          await page.locator(HEADLINE).first().hover();
        },
      },
      { name: "bookmark-new", url: `${base}/bookmark/new`, prepare: shown(EDIT_FORM) },
      {
        name: "bookmark-new-tags",
        url: `${base}/bookmark/new`,
        prepare: async (page) => {
          await shown(TAG_ENTRY)(page);
          await page.locator(TAG_ENTRY).fill("palette");
          await page.locator(TAG_ENTRY).press("Enter");
          await shown(CHIP)(page);
        },
      },
      {
        name: "bookmark-new-hover",
        url: `${base}/bookmark/new`,
        prepare: async (page) => {
          await shown(SAVE)(page);
          await page.locator(SAVE).hover();
        },
      },
      { name: "bookmark-edit", url: `${base}/bookmark/${bookmarkId}/edit`, prepare: shown(EDIT_FORM) },
      {
        name: "bookmark-edit-details",
        url: `${base}/bookmark/${bookmarkId}/edit`,
        prepare: async (page) => {
          await shown("details.form-group summary")(page);
          await page.locator("details.form-group").first().evaluate((details) => {
            details.open = true;
          });
          await shown("#bookmark_allowed")(page);
        },
      },
      { name: "bookmark-popup", url: `${base}/bookmark/popup`, prepare: shown(EDIT_FORM) },
      { name: "admin-bookmarklet", url: `${base}/admin`, prepare: shown(".admin-links") },
      { name: "admin-import", url: `${base}/admin/bookmarks`, prepare: shown("#multiadd_urls") },
      { name: "admin-followers", url: `${base}/admin/followers`, prepare: shown(".admin-links") },
      { name: "admin-following", url: `${base}/admin/following`, prepare: shown(".admin-links") },
      { name: "admin-data", url: `${base}/admin/data`, prepare: shown(".admin-links") },
      { name: "network", url: `${base}/network`, prepare: shown(".content h1") },
    ];
  }

  test("design: gallery of public pages, forms and the owner area", async ({ browser, page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_800_000));
    await signIn(page);
    const bookmarkId = await seed(page);
    const failures = [];
    const visitor = await browser.newPage({ ignoreHTTPSErrors: true });
    try {
      if (isServiceEnabled("sso")) await signIn(visitor);
      await captureDesignGallery(visitor, visitorViews(bookmarkId));
    } catch (error) {
      failures.push(error.message);
    }
    await visitor.close();
    try {
      await captureDesignGallery(page, ownerViews(bookmarkId));
    } catch (error) {
      failures.push(error.message);
    }
    expect(failures, "design gallery views failed").toEqual([]);
  });
};
