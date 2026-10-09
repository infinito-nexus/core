const crypto = require("crypto");
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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.SOCIALHOME_ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.SOCIALHOME_ADMIN_PASSWORD || "");
const sidebarLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_SIDEBAR_LOGO_URL || "");
const loginLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGIN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const READY_MS = 10_000;
const SHOWCASE = "Design showcase";
const LOGIN_FORM = ".sh-login-form";
const SUBMIT = `${LOGIN_FORM} button[type='submit']`;
const TOPBAR = ".sh-topbar";
const TOPBAR_TITLE = ".sh-topbar-title";
const DESKTOP_NAV = ".sh-layout > .sh-sidenav";
const BRAND = `${DESKTOP_NAV} .sh-sidenav-brand`;
const COMPOSER = ".sh-composer";
const FEED_ITEM = ".sh-feed-item";
const THEME_OPTION = ".sh-theme-option";
const ADMIN_TAB = ".sh-admin-tabs [role='tab']";
const MOBILE_MORE = ".sh-mobile-tab--more";
const DRAWER_OPEN = ".sh-mobile-drawer--open";
const PACE_MS = 4_000;
const SPACE_PACE_MS = 10_000;

let token = null;
let lastLoad = 0;

/**
 * Args:
 *   page: Playwright page whose request context carries the call.
 *   method: HTTP verb.
 *   path: path below the Social Home origin.
 *   data: JSON body, omitted for a request without one.
 *
 * Returns:
 *   The Playwright API response.
 */
async function call(page, method, path, data) {
  return apiFetchOnion(page.request, `${base}${path}`, {
    method,
    headers: { authorization: `Bearer ${token}` },
    ...(data === undefined ? {} : { data }),
  });
}

/**
 * Args:
 *   page: Playwright page whose request context carries the call.
 *   path: collection path below the Social Home origin.
 *   key: member that holds the list when the answer is an object.
 *
 * Returns:
 *   The entries of the collection.
 */
async function list(page, path, key) {
  const response = await call(page, "GET", path);
  expect(response.status(), `listing ${path}`).toBe(200);
  const body = await response.json();
  return Array.isArray(body) ? body : body[key] || [];
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the administrator. Social Home allows five sign-ins per 15 minutes for every client behind the proxy, so the first call fetches one token per worker and later calls reuse it.
 */
async function signIn(page) {
  if (!token) {
    const response = await apiFetchOnion(page.request, `${base}/api/auth/token`, {
      method: "POST",
      data: { username: adminUsername, password: adminPassword },
    });
    expect(response.status(), "the administrator must get a token").toBe(200);
    token = (await response.json()).token;
    const onboarded = await call(page, "POST", "/api/me/onboarding-complete");
    expect(onboarded.status(), "the first-run onboarding must be cleared").toBeLessThan(300);
  }
  await page.addInitScript((value) => window.localStorage.setItem("sh_token", value), token);
}

/**
 * Args:
 *   page: signed-in Playwright page.
 *
 * Returns:
 *   The id of the showcase space, created when it is missing.
 */
async function showcaseSpace(page) {
  const existing = (await list(page, "/api/spaces", "spaces")).find((entry) => entry.name === SHOWCASE);
  if (existing) return existing.id;
  const response = await call(page, "POST", "/api/spaces", { name: SHOWCASE, description: "Seeded for the corporate design review." });
  expect(response.status(), "seeding the showcase space").toBeLessThan(300);
  return (await response.json()).id;
}

/**
 * Args:
 *   page: signed-in Playwright page; posts, a calendar with an event, a task list, shopping items, a page and a member named after the showcase get created when they are missing.
 *
 * Returns:
 *   The id of the showcase space.
 */
async function seedShowcase(page) {
  const created = async (path, data) => {
    const response = await call(page, "POST", path, data);
    expect(response.status(), `seeding ${path}`).toBeLessThan(300);
    return response.json();
  };
  const spaceId = await showcaseSpace(page);

  const posts = await list(page, "/api/feed", "posts");
  if (!posts.some((post) => String(post.content || "").includes(SHOWCASE))) {
    await created("/api/feed/posts", { type: "text", content: `${SHOWCASE}: dinner at seven, bring the salad.` });
    await created("/api/feed/posts", { type: "text", content: `${SHOWCASE}: the bike is fixed.` });
  }
  const spacePosts = await list(page, `/api/spaces/${spaceId}/feed`, "posts");
  if (!spacePosts.some((post) => String(post.content || "").includes(SHOWCASE))) {
    await created(`/api/spaces/${spaceId}/posts`, { type: "text", content: `${SHOWCASE}: welcome to the space.` });
  }

  let calendar = (await list(page, "/api/calendars", "calendars")).find((entry) => entry.name === SHOWCASE);
  if (!calendar) calendar = await created("/api/calendars", { name: SHOWCASE });
  const day = new Date();
  day.setUTCHours(17, 0, 0, 0);
  const range = `start=${encodeURIComponent(new Date(day.getTime() - 40 * 86_400_000).toISOString())}&end=${encodeURIComponent(new Date(day.getTime() + 40 * 86_400_000).toISOString())}`;
  const events = await list(page, `/api/calendars/${calendar.id}/events?${range}`, "events");
  if (events.length === 0) {
    const end = new Date(day.getTime() + 2 * 3_600_000);
    await created(`/api/calendars/${calendar.id}/events`, { summary: `${SHOWCASE} dinner`, start: day.toISOString(), end: end.toISOString() });
  }

  let taskList = (await list(page, "/api/tasks/lists", "lists")).find((entry) => entry.name === SHOWCASE);
  if (!taskList) {
    taskList = await created("/api/tasks/lists", { name: SHOWCASE });
    for (const task of ["Water the plants", "Book the dentist", "Fix the gate"]) {
      await created(`/api/tasks/lists/${taskList.id}/tasks`, { title: task });
    }
  }

  const shopping = await list(page, "/api/shopping", "items");
  if (shopping.length === 0) {
    for (const text of ["Bread", "Olive oil", "Tomatoes"]) await created("/api/shopping", { text });
  }

  const pages = await list(page, "/api/pages", "pages");
  if (!pages.some((entry) => entry.title === SHOWCASE)) {
    await created("/api/pages", { title: SHOWCASE, content: "# House rules\n\n- Shoes off\n- Lights out at eleven" });
  }

  const member = await call(page, "POST", "/api/admin/users", {
    username: "design-member",
    password: crypto.randomBytes(18).toString("base64url"),
    display_name: "Design Member",
    is_admin: false,
  });
  expect([200, 201, 409], "seeding the household member").toContain(member.status());
  return spaceId;
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  };
}

function tab(selector, panel) {
  return async (page) => {
    await shown(selector)(page);
    await page.locator(selector).first().click();
    await shown(panel)(page);
  };
}

function adminTab(index, panel) {
  return async (page) => {
    await shown(ADMIN_TAB)(page);
    await page.locator(ADMIN_TAB).nth(index).click();
    await shown(panel)(page);
  };
}

async function navigation(page) {
  if (page.viewportSize().width > 768) {
    const entry = `${DESKTOP_NAV} a[href$='/calendar']`;
    await shown(entry)(page);
    await page.locator(entry).hover();
    return;
  }
  await shown(MOBILE_MORE)(page);
  await page.locator(MOBILE_MORE).click();
  await shown(DRAWER_OPEN)(page);
  await expect
    .poll(() => page.locator(DRAWER_OPEN).evaluate((element) => element.getAnimations().length), {
      timeout: resolveTimeout(READY_MS),
    })
    .toBe(0);
}

async function primaryInBody(page) {
  return page.evaluate(() => {
    const probe = document.createElement("span");
    probe.style.color = "var(--sh-primary)";
    document.body.appendChild(probe);
    const value = getComputedStyle(probe).color;
    probe.remove();
    return value;
  });
}

function signedOutViews() {
  return [
    { name: "sign-in", url: `${base}/`, prepare: shown(LOGIN_FORM) },
    {
      name: "sign-in-focus",
      url: `${base}/`,
      prepare: async (page) => {
        await shown(LOGIN_FORM)(page);
        await page.locator(`${LOGIN_FORM} input[name='username']`).focus();
      },
    },
    { name: "forgot-password", url: `${base}/forgot-password`, prepare: shown(".sh-login") },
  ];
}

/**
 * Args:
 *   prepare: the view's own preparation.
 *   pace: milliseconds to keep after the previous view. Social Home allows every user 60 API requests per minute and path prefix; a signed-in page load spends three of them on /api/me, a space page several more on /api/spaces.
 *
 * Returns:
 *   The preparation, started no earlier than `pace` after the previous one.
 */
function paced(prepare, pace) {
  return async (page) => {
    const wait = lastLoad + pace - Date.now();
    if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
    lastLoad = Date.now();
    await prepare(page);
  };
}

function signedInViews(spaceId) {
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  return [
    view("welcome", "/", ".sh-welcome-hero"),
    view("feed", "/feed", FEED_ITEM),
    {
      name: "feed-composer-focus",
      url: `${base}/feed`,
      prepare: async (page) => {
        await shown(`${COMPOSER} textarea`)(page);
        await page.locator(`${COMPOSER} textarea`).first().focus();
      },
    },
    view("spaces", "/spaces", ".sh-spaces-section"),
    view("space-feed", `/spaces/${spaceId}`, ".sh-space-feed"),
    view("space-settings", `/spaces/${spaceId}/settings`, ".sh-space-settings-page"),
    view("space-browse", "/spaces/browse", "main"),
    view("calendar", "/calendar", ".sh-calendar-views"),
    view("organize", "/organize", ".sh-organize-host"),
    view("pages", "/pages", "main"),
    view("dms", "/dms", ".sh-dms"),
    view("notifications", "/notifications", ".sh-notifications-page"),
    view("friends", "/friends", ".sh-friends"),
    view("gallery", "/gallery", ".sh-gallery"),
    view("bazaar", "/bazaar", ".sh-bazaar"),
    view("corner", "/corner", ".sh-welcome"),
    view("search", `/search?q=${encodeURIComponent(SHOWCASE)}`, ".sh-search-page"),
    view("settings-profile", "/settings", "#sh-settings-panel-profile"),
    { name: "settings-appearance", url: `${base}/settings`, prepare: tab("#sh-settings-tab-appearance", ".sh-theme-options") },
    { name: "settings-security", url: `${base}/settings`, prepare: tab("#sh-settings-tab-security", "#sh-settings-panel-security") },
    view("admin-members", "/admin", ".sh-admin-table"),
    {
      name: "admin-create-user",
      url: `${base}/admin`,
      prepare: tab("details.sh-admin-section > summary", ".sh-admin-create-user"),
    },
    { name: "admin-spaces", url: `${base}/admin`, prepare: adminTab(1, ".sh-admin-section") },
    { name: "admin-storage", url: `${base}/admin`, prepare: adminTab(5, ".sh-admin-stats") },
    { name: "admin-settings", url: `${base}/admin`, prepare: adminTab(7, ".sh-admin-section") },
    view("connections", "/connections", ".sh-connections"),
    { name: "navigation", url: `${base}/feed`, prepare: navigation },
  ].map((entry) => ({ ...entry, prepare: paced(entry.prepare, entry.url.includes("/spaces") ? SPACE_PACE_MS : PACE_MS) }));
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${base}/feed`);
    await shown(TOPBAR)(page);
    await assertDesignTokens(page, "Social Home");
  });

  test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/`);
      await shown(LOGIN_FORM)(page);
      await assertToken(page, ".sh-login", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, LOGIN_FORM, "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, LOGIN_FORM, "border-top-color", "--design-border", `sign-in ${mode}`);
      await assertToken(page, `${LOGIN_FORM} input[name='username']`, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await page.locator(SUBMIT).hover();
      await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, LOGIN_FORM, "Social Home sign-in");
    await assertReadable(page, [`${LOGIN_FORM} label`, SUBMIT, ".sh-login a.sh-link"], "Social Home sign-in");
  });

  test("design: the signed-in shell takes surfaces, dividers, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/feed`);
      await shown(COMPOSER)(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, TOPBAR, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, TOPBAR, "border-bottom-color", "--design-border", `shell divider ${mode}`);
      await assertToken(page, COMPOSER, "background-color", "--design-surface-2", `composer ${mode}`);
      await assertToken(page, TOPBAR_TITLE, "color", "--design-text", `shell ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, COMPOSER, "Social Home feed");
    await assertReadable(page, [TOPBAR_TITLE, { selector: `${DESKTOP_NAV} a`, optional: true }], "Social Home feed");
  });

  test("design: the member table separates its rows with the border token", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/admin`);
      await shown(".sh-admin-table td")(page);
      await assertToken(page, ".sh-admin-table td", "border-bottom-color", "--design-border", `member rows ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the sidebar marks the current page and the hovered entry with the state surfaces", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/feed`);
      const current = `${DESKTOP_NAV} a[aria-current='page']`;
      await shown(current)(page);
      await assertToken(page, current, "background-color", "--design-surface-active", `current entry ${mode}`);
      await assertToken(page, current, "color", "--design-link", `current entry ${mode}`);
      await assertToken(page, `${DESKTOP_NAV} .sh-sidenav-divider`, "border-top-color", "--design-border", `sidebar divider ${mode}`);
      const other = `${DESKTOP_NAV} a[href$='/calendar']`;
      await page.locator(other).hover();
      await assertToken(page, other, "background-color", "--design-surface-hover", `hovered entry ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: a theme picked in the appearance settings is respected and mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await signIn(page);
    await gotoOnion(page, `${base}/settings`);
    await tab("#sh-settings-tab-appearance", THEME_OPTION)(page);
    const html = page.locator("html");
    const surface = () => tokenValue(page, "--design-surface-1", "background-color");
    const lightSurface = await surface();
    await expect(html, "auto follows the browser preference").not.toHaveAttribute("data-design-theme");

    await page.locator(THEME_OPTION).nth(1).click();
    await expect(html).toHaveClass(/sh-theme-dark/);
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(await surface(), "a dark theme picked in Social Home must switch the tokens").not.toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "dark theme picked in Social Home");

    await gotoOnion(page, page.url());
    await shown(TOPBAR)(page);
    await expect(html, "the picked theme must survive a reload").toHaveAttribute("data-design-theme", "dark");

    await page.emulateMedia({ colorScheme: "dark" });
    await tab("#sh-settings-tab-appearance", THEME_OPTION)(page);
    await page.locator(THEME_OPTION).nth(0).click();
    await expect(html).toHaveAttribute("data-design-theme", "light");
    expect(await surface(), "a light theme picked in Social Home must keep the light tokens").toBe(lightSurface);

    await page.locator(THEME_OPTION).nth(2).click();
    await expect(html, "auto hands the mode back to the browser").not.toHaveAttribute("data-design-theme");
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: a space takes the household primary from the palette in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    const spaceId = await showcaseSpace(page);
    const html = page.locator("html");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/spaces/${spaceId}`);
      await expect(html, "the space theme must be applied").toHaveAttribute("data-space-theme", spaceId);
      await expect(html, "the household primary must be the one the role wrote").toHaveAttribute("data-design-household-primary", "");
      expect(await primaryInBody(page), `space primary ${mode}`).toBe(await tokenValue(page, "--design-primary", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the interface shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!sidebarLogoUrl && !title, "logo and title replacement are disabled for this role");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    await gotoOnion(page, `${base}/settings`);
    await shown(TOPBAR_TITLE)(page);
    if (title) {
      await expect
        .poll(async () => (await page.title()).split(title).length - 1, { message: "the title must carry the configured title once" })
        .toBe(1);
      expect(await page.title(), "the upstream brand must be gone from the title").not.toContain("Social Home");
    }
    if (sidebarLogoUrl) {
      await expect(page.locator(BRAND)).toHaveCSS("background-image", `url("${sidebarLogoUrl}")`);
      await expect(page.locator(`${BRAND} .sh-logo`)).toBeHidden();
      const box = await page.locator(BRAND).boundingBox();
      expect(box.width, "the sidebar lockup must be wider than high").toBeGreaterThan(box.height);
      const content = await page.locator(BRAND).evaluate((element) => {
        const style = getComputedStyle(element);
        return element.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      });
      expect(content, "the sidebar lockup must not shrink below the 28px of the upstream logo").toBeGreaterThanOrEqual(28);
      for (const url of [sidebarLogoUrl, loginLogoUrl, faviconUrl]) {
        expect((await apiGetOnion(page.request, url)).ok(), `${url} must be served`).toBe(true);
      }
      await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    }
  });

  test("design: the sign-in page shows the generated logo", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!loginLogoUrl, "logo replacement is disabled for this role");
    await gotoOnion(page, `${base}/`);
    await shown(LOGIN_FORM)(page);
    await expect(page.locator(".sh-login-hero .sh-wordmark")).toHaveCSS("background-image", `url("${loginLogoUrl}")`);
    await expect(page.locator(".sh-login-hero .sh-wordmark__name")).toBeHidden();
  });

  test("design: gallery of sign-in, feed, spaces, organizer, settings and administration", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    const failures = [];
    await captureDesignGallery(page, signedOutViews()).catch((error) => failures.push(error.message));
    await signIn(page);
    const spaceId = await seedShowcase(page);
    await captureDesignGallery(page, signedInViews(spaceId)).catch((error) => failures.push(error.message));
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
