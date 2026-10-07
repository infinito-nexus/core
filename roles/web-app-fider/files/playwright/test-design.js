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
const { decodeDotenvQuotedValue, gotoOnion, performKeycloakLoginForm } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { clickFiderSsoButton } = require("./_shared");

const base = decodeDotenvQuotedValue(process.env.FIDER_BASE_URL || "").replace(/\/$/, "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const logoEnabled = process.env.DESIGN_LOGO_ENABLED === "true";

const MODES = ["light", "dark"];
const READY_MS = 60_000;
const VIEW_READY_MS = 15_000;
const LOGO_IMAGE = /\/static\/images\/logos\/infinito-design-logo\.png/;
const LOGO_FAVICON = /\/static\/favicon\/logos\/infinito-design-logo\.png/;
const HOME = "#p-home";
const HEADER = "#c-header";
const BRAND = `${HEADER} .c-header__brand`;
const NAV_LINK = `${HEADER} .c-header__nav-link`;
const PRIMARY = `${HEADER} .c-button--primary`;
const SWITCH = '.c-themeswitcher[aria-label="Toggle theme"]';
const ADD_IDEA = `${HOME} .p-home__add-idea-btn`;
const USER_MENU = ".c-menu-user";
const SIDE_MENU_ITEM = ".c-side-menu__item";
const SIDE_MENU_TOGGLER = '#p-admin-tags [class~="lg:hidden"][class~="xl:hidden"]';
const MODAL = ".c-modal-window";
const POST_ROW = `${HOME} .c-posts-container__post`;
const TOOLKIT = "#p-ui-toolkit";
const SHOWCASE = [
  { title: "Design showcase: dark mode for the board", description: "A seeded idea that shows a post row, its votes and its tags.", status: "planned" },
  { title: "Design showcase: export ideas as CSV", description: "A seeded idea in the started column of the roadmap.", status: "started" },
  { title: "Design showcase: weekly digest mail", description: "A seeded idea without a response.", status: "" },
];

/**
 * Args:
 *   selector: selector whose first match has to become visible.
 *   timeout: base timeout in milliseconds, scaled through `resolveTimeout`.
 */
function shown(selector, timeout) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(timeout) });
  };
}

async function signIn(page) {
  await gotoOnion(page, `${base}/`);
  await clickFiderSsoButton(page);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await shown(USER_MENU, READY_MS)(page);
}

async function openHome(page) {
  await gotoOnion(page, `${base}/`);
  await shown(HOME, READY_MS)(page);
  await expect(page.locator("body")).toHaveAttribute("data-theme", /^(light|dark)$/);
}

/**
 * Args:
 *   page: Playwright page on a Fider route.
 *   mode: `light` or `dark`; the browser preference is switched and the call returns once the app follows it.
 */
async function useMode(page, mode) {
  await page.emulateMedia({ colorScheme: mode });
  await expect(page.locator("body")).toHaveAttribute("data-theme", mode);
}

/**
 * Args:
 *   page: signed-in Playwright page on a Fider route; a tag and the showcase posts exist afterwards.
 *   posts: showcase posts as `{ title, description, status }`.
 *
 * Returns:
 *   `{ number, slug }` of the first showcase post.
 */
async function seedShowcase(page, posts) {
  return page.evaluate(async (entries) => {
    const headers = { Accept: "application/json", "Content-Type": "application/json" };
    const call = async (method, url, body) => {
      const response = await fetch(url, { method, headers, credentials: "same-origin", body: body ? JSON.stringify(body) : undefined });
      if (!response.ok) throw new Error(`${method} ${url.split("?")[0]} answered ${response.status}`);
      return response.json().catch(() => ({}));
    };
    const tags = await call("GET", "/api/v1/tags");
    if (!tags.some((tag) => tag.slug === "design")) {
      await call("POST", "/api/v1/tags", { name: "Design", color: "8A2BE2", isPublic: true });
    }
    let first = null;
    for (const post of entries) {
      const matches = await call("GET", `/api/v1/posts?query=${encodeURIComponent(post.title)}&limit=50`);
      const found = matches.find((item) => item.title === post.title);
      const entry = found || (await call("POST", "/api/v1/posts", { title: post.title, description: post.description }));
      if (!found) {
        await call("POST", `/api/v1/posts/${entry.number}/tags/design`);
        await call("POST", `/api/v1/posts/${entry.number}/comments`, { content: "A seeded comment for the detail view." });
        if (post.status) await call("PUT", `/api/v1/posts/${entry.number}/status`, { status: post.status, text: "A seeded response." });
      }
      first = first || { number: entry.number, slug: entry.slug };
    }
    return first;
  }, posts);
}

/**
 * Args:
 *   page: Playwright page that shows an open modal once its opening animation ended.
 */
async function modalOpened(page) {
  await shown(MODAL, VIEW_READY_MS)(page);
  await expect
    .poll(() =>
      page
        .locator(MODAL)
        .first()
        .evaluate((el) => el.getAnimations({ subtree: true }).every((a) => a.playState !== "running") && getComputedStyle(el).opacity === "1"),
    )
    .toBe(true);
}

const VISITOR_VIEWS = [
  { name: "visitor-home", url: `${base}/`, prepare: shown(PRIMARY, VIEW_READY_MS) },
  {
    name: "sign-in-modal",
    url: `${base}/`,
    prepare: async (view) => {
      await shown(PRIMARY, VIEW_READY_MS)(view);
      await view.locator(PRIMARY).first().click();
      await modalOpened(view);
    },
  },
  { name: "component-page", url: `${base}/_design`, prepare: shown("#p-ui-toolkit", VIEW_READY_MS) },
  { name: "not-found", url: `${base}/design-showcase-missing`, prepare: shown("#p-error404", VIEW_READY_MS) },
];

/**
 * Args:
 *   post: `{ number, slug }` of the showcase post the detail view opens.
 *
 * Returns:
 *   The gallery views of the signed-in administrator.
 */
function memberViews(post) {
  const admin = (path, id) => ({ url: `${base}/admin${path}`, prepare: shown(id, VIEW_READY_MS) });
  return [
    { name: "home", url: `${base}/`, prepare: shown(POST_ROW, VIEW_READY_MS) },
    { name: "home-search", url: `${base}/?query=digest`, prepare: shown(POST_ROW, VIEW_READY_MS) },
    {
      name: "home-filter",
      url: `${base}/`,
      prepare: async (view) => {
        await shown(".c-post-filter-btn", VIEW_READY_MS)(view);
        await view.locator(".c-post-filter-btn").first().click();
        await shown(".c-dropdown__list", VIEW_READY_MS)(view);
      },
    },
    { name: "post-details", url: `${base}/posts/${post.number}/${post.slug}`, prepare: shown("#p-show-post", VIEW_READY_MS) },
    { name: "roadmap", url: `${base}/roadmap`, prepare: shown("#p-roadmap", VIEW_READY_MS) },
    {
      name: "user-menu",
      url: `${base}/`,
      prepare: async (view) => {
        await shown(`${USER_MENU} .c-dropdown__handle`, VIEW_READY_MS)(view);
        await view.locator(`${USER_MENU} .c-dropdown__handle`).first().click();
        await shown(`${USER_MENU} .c-dropdown__list`, VIEW_READY_MS)(view);
      },
    },
    {
      name: "new-idea",
      url: `${base}/`,
      prepare: async (view) => {
        await shown(".p-home__add-idea-btn", VIEW_READY_MS)(view);
        await view.locator(".p-home__add-idea-btn").first().click();
        await modalOpened(view);
      },
    },
    { name: "my-settings", url: `${base}/settings`, prepare: shown("#p-my-settings", VIEW_READY_MS) },
    { name: "my-notifications", url: `${base}/notifications`, prepare: shown("#p-my-notifications", VIEW_READY_MS) },
    { name: "admin-general", ...admin("", "#p-admin-general") },
    { name: "admin-advanced", ...admin("/advanced", "#p-admin-advanced") },
    { name: "admin-privacy", ...admin("/privacy", "#p-admin-privacy") },
    { name: "admin-users", ...admin("/users", "#p-admin-members") },
    { name: "admin-tags", ...admin("/tags", "#p-admin-tags") },
    { name: "admin-invitations", ...admin("/invitations", "#p-admin-invitations") },
    { name: "admin-authentication", ...admin("/authentication", "#p-admin-authentication") },
    { name: "admin-webhooks", ...admin("/webhooks", "#p-admin-webhooks") },
    { name: "admin-export", ...admin("/export", "#p-admin-export") },
    { name: "admin-moderation", ...admin("/moderation", "#p-admin-moderation") },
    {
      name: "admin-menu-hover",
      url: `${base}/admin/tags`,
      prepare: async (view) => {
        await shown("#p-admin-tags", VIEW_READY_MS)(view);
        const entry = view.locator(`${SIDE_MENU_ITEM}:not(${SIDE_MENU_ITEM}--active)`).first();
        if (!(await entry.isVisible())) await view.locator(SIDE_MENU_TOGGLER).first().click();
        await shown(SIDE_MENU_ITEM, VIEW_READY_MS)(view);
        await entry.hover();
        await view.evaluate(() => window.scrollTo(0, 0));
      },
    },
  ];
}

exports.register = function () {
  test.describe("design", () => {
    test.beforeEach(() => {
      skipUnlessServiceEnabled("design");
      test.skip(!isServiceEnabled("sso"), "the role bootstraps the Fider tenant only together with the identity provider");
    });

    test("design: tokens are present and switch with the color scheme", async ({ page }) => {
      await openHome(page);
      await assertDesignTokens(page, "fider home");
    });

    test("design: the custom CSS of the tenant carries the palette in both modes", async ({ page }) => {
      await openHome(page);
      await expect(page.locator("body > link[rel='stylesheet'][href*='/static/custom/']")).toHaveAttribute("href", /\/static\/custom\/[0-9a-f]{32}\.css$/);
      for (const mode of MODES) {
        await useMode(page, mode);
        await assertToken(page, "body", "background-color", "--design-surface-1", `page in ${mode}`);
        await assertToken(page, "body", "color", "--design-text", `body text in ${mode}`);
        await assertToken(page, HEADER, "background-color", "--design-surface-2", `header in ${mode}`);
        await assertToken(page, HEADER, "border-bottom-color", "--design-border", `header divider in ${mode}`);
        await assertToken(page, ADD_IDEA, "background-color", "--design-surface-2", `suggestion card in ${mode}`);
        await assertToken(page, ADD_IDEA, "border-top-color", "--design-border", `suggestion card border in ${mode}`);
        await assertToken(page, `${NAV_LINK}--active`, "color", "--design-text", `active navigation link in ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
    });

    test("design: the primary action is filled with --design-primary and labelled in --design-on-primary", async ({ page }) => {
      await openHome(page);
      for (const mode of MODES) {
        await useMode(page, mode);
        await assertToken(page, PRIMARY, "background-color", "--design-primary", `sign-in button in ${mode}`);
        await assertToken(page, PRIMARY, "color", "--design-on-primary", `sign-in button text in ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
    });

    test("design: surfaces and text hold in light and dark mode", async ({ page }) => {
      await openHome(page);
      await assertLightAndDark(page, HOME, "fider home");
      await assertLightAndDark(page, ADD_IDEA, "fider suggestion card");
      await assertReadable(page, [`${BRAND} h1`, `${NAV_LINK}--active`, `${NAV_LINK}:not(${NAV_LINK}--active)`, PRIMARY, ADD_IDEA, { selector: ".p-home__welcome-col p", optional: true }], "fider home");
    });

    test("design: the built-in component page stays readable", async ({ page }) => {
      await gotoOnion(page, `${base}/_design`);
      await shown(TOOLKIT, READY_MS)(page);
      await expect(page.locator("body")).toHaveAttribute("data-theme", /^(light|dark)$/);
      await assertReadable(
        page,
        [`${TOOLKIT} .c-button--primary`, `${TOOLKIT} .c-button--secondary`, `${TOOLKIT} .c-button--danger`, `${TOOLKIT} .c-message--success`, `${TOOLKIT} .c-message--warning`, `${TOOLKIT} .c-message--error`, { selector: `${TOOLKIT} .c-hint`, optional: true }],
        "fider component page",
      );
    });

    test("design: the board carries the configured title", async ({ page }) => {
      await openHome(page);
      expect(title, "DESIGN_TITLE must be set in the Playwright env file").toBeTruthy();
      await expect(page).toHaveTitle(title);
      await expect(page.locator(`${BRAND} h1`)).toHaveText(title);
    });

    test("design: logo and favicon are the configured ones", async ({ page }) => {
      test.skip(!logoEnabled, "the role places the logo in the database blob store only; with the object store enabled the tenant keeps its own logo");
      await openHome(page);
      const logo = page.locator(`${BRAND} img`);
      await expect(logo).toBeVisible();
      await expect(logo).toHaveAttribute("src", LOGO_IMAGE);
      await expect.poll(() => logo.evaluate((img) => img.complete && img.naturalWidth > 0), { message: "header logo must load" }).toBe(true);
      const logoBox = await logo.boundingBox();
      expect(Math.abs(logoBox.width - logoBox.height), "header logo box is square").toBeLessThanOrEqual(1);
      const brandBox = await page.locator(BRAND).boundingBox();
      expect(brandBox.width, "logo and title form a wide brand").toBeGreaterThan(brandBox.height);
      await expect(page.locator("link[rel='icon']").first()).toHaveAttribute("href", LOGO_FAVICON);
    });

    test("design: the board follows the browser until the switch is used, then the switch wins", async ({ page }) => {
      await page.emulateMedia({ colorScheme: "dark" });
      await openHome(page);
      await expect(page.locator("body")).toHaveAttribute("data-theme", "dark");
      await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
      const dark = await tokenValue(page, "--design-surface-1", "color");
      await page.locator(SWITCH).click();
      await expect(page.locator("body")).toHaveAttribute("data-theme", "light");
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
      expect(await tokenValue(page, "--design-surface-1", "color"), "the tokens follow the switch against the browser").not.toBe(dark);
      await assertToken(page, "body", "background-color", "--design-surface-1", "page after the switch");
      await gotoOnion(page, `${base}/_design`);
      await shown(TOOLKIT, READY_MS)(page);
      await expect(page.locator("body")).toHaveAttribute("data-theme", "light");
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
      await page.emulateMedia({ colorScheme: null });
    });

    test("design: the signed-in board and the administration keep cards, dividers, selection and primary text on the tokens", async ({ page }) => {
      await signIn(page);
      await seedShowcase(page, SHOWCASE);
      await openHome(page);
      await shown(POST_ROW, READY_MS)(page);
      for (const mode of MODES) {
        await useMode(page, mode);
        await assertToken(page, POST_ROW, "background-color", "--design-surface-2", `post card in ${mode}`);
        await assertToken(page, `${POST_ROW} .c-posts-container__post-title`, "color", "--design-text", `post title in ${mode}`);
        await assertToken(page, ".c-post-filter-btn", "background-color", "--design-surface-2", `filter button in ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
      await assertReadable(page, [`${POST_ROW} .c-posts-container__post-title`, `${POST_ROW} .c-posts-container__postdescription`, ".c-post-filter-btn", { selector: ".c-powered a", optional: true }], "fider board");
      await gotoOnion(page, `${base}/admin`);
      await shown("#p-admin-general", READY_MS)(page);
      for (const mode of MODES) {
        await useMode(page, mode);
        await assertToken(page, `${SIDE_MENU_ITEM}:not(${SIDE_MENU_ITEM}--active)`, "border-bottom-color", "--design-border", `menu divider in ${mode}`);
        await assertToken(page, `${SIDE_MENU_ITEM}--active`, "color", "--design-link", `selected menu entry in ${mode}`);
        await assertToken(page, "#p-admin-general .c-button--primary", "background-color", "--design-primary", `save button in ${mode}`);
        await assertToken(page, "#p-admin-general .c-button--primary", "color", "--design-on-primary", `save button text in ${mode}`);
        await assertToken(page, "#p-admin-general .c-input", "background-color", "--design-surface-2", `input in ${mode}`);
        await assertToken(page, "#p-admin-general .c-input", "border-top-color", "--design-border-strong", `input boundary in ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
      await assertReadable(page, [`${SIDE_MENU_ITEM}--active`, `${SIDE_MENU_ITEM}:not(${SIDE_MENU_ITEM}--active)`, "#p-admin-general .c-button--primary", "#p-admin-general .c-input"], "fider administration");
    });

    test("design: gallery", async ({ page, browser }) => {
      test.skip(!galleryEnabled(), "gallery runs only with INFINITO_PLAYWRIGHT_KEEP=true");
      test.setTimeout(resolveTimeout(1_500_000));
      await signIn(page);
      const post = await seedShowcase(page, SHOWCASE);
      const failures = [];
      const visitorContext = await browser.newContext({ ignoreHTTPSErrors: true });
      const visitor = await visitorContext.newPage();
      await captureDesignGallery(visitor, VISITOR_VIEWS).catch((error) => failures.push(error.message));
      await visitorContext.close();
      await captureDesignGallery(page, memberViews(post)).catch((error) => failures.push(error.message));
      expect(failures, failures.join("\n")).toEqual([]);
    });
  });
};
