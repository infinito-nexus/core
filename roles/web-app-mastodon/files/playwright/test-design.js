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
const {
  apiGetOnion,
  clickOidcLoginLink,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLogin,
  requireDotenvValue,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

test.use({ ignoreHTTPSErrors: true });

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL")).replace(/\/$/, "");
const canonicalDomain = decodeDotenvQuotedValue(requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN"));
const adminEmail = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_EMAIL, "ADMIN_EMAIL"));
const adminPassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));
const adminUsername = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"));
const ssoEnabled = (process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true";
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const wordmarkUrl = decodeDotenvQuotedValue(process.env.DESIGN_WORDMARK_URL || "");
const iconUrl = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_ICON_URL, "DESIGN_ICON_URL"));

const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const COLUMN = ".column";
const HEADING = ".admin-wrapper .content__heading";
const COMPOSE_TEXT = ".compose-form textarea";
const PRIMARY = ".compose-form button.button[type='submit']";
const ADMIN_ROW = ".batch-table__row";
const LOGIN_EMAIL = "#user_email";
const LOGIN_PASSWORD = "#user_password";
const LOGIN_SUBMIT = ".form-container .actions button[type='submit']";
const SETTINGS_SUBMIT = ".admin-wrapper button.button[type='submit']";
const STATUS_MENU = ".detailed-status__action-bar button[aria-label='More']";
const CUSTOM_CSS_BEGIN = "/* infinito-design:begin */";
const SHOWCASE_TAG = "designshowcase";
const SHOWCASE_POSTS = 3;
// rack-attack throttle_per_token_api caps one API token at 300 calls per 5 minutes; each gallery chunk signs in for its own token.
const GALLERY_CHUNK = 4;

let session = null;

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the platform administrator, through the identity provider when sso is on and through Mastodon's own form otherwise. Later calls in the same worker reuse the first session.
 *   options.fresh: sign in again instead of reusing the first session, so the page gets its own API token.
 */
async function signIn(page, { fresh = false } = {}) {
  if (session && !fresh) {
    await page.context().addCookies(session);
  } else if (ssoEnabled) {
    await gotoOnion(page, `${base}/auth/sign_in`);
    if (!page.url().includes("openid-connect/auth")) {
      const strict = page.getByRole("link", { name: /^\s*(log\s*in|sign\s*in|sso)\s*$/i }).first();
      const loose = page.getByRole("link", { name: /log\s*in|sign\s*in|sso/i }).first();
      await clickOidcLoginLink(page, strict, loose);
    }
    if (page.url().includes("openid-connect/auth")) {
      await performKeycloakLogin(page, adminUsername, adminPassword, canonicalDomain);
    }
  } else {
    await gotoOnion(page, `${base}/auth/sign_in`);
    await expect(page.locator(LOGIN_EMAIL)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(LOGIN_EMAIL).fill(adminEmail);
    await expect(page.locator(LOGIN_PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(LOGIN_PASSWORD).fill(adminPassword);
    await page.locator(LOGIN_SUBMIT).click();
    await expect(page, "Mastodon must accept the administrator's inventory password").not.toHaveURL(/\/auth\/sign_in/, {
      timeout: resolveTimeout(15_000),
    });
  }
  await gotoOnion(page, `${base}/home`);
  await shown(COLUMN)(page);
  if (!session) session = await page.context().cookies();
}

/**
 * Args:
 *   page: signed-in page on the web app; the call runs inside it with the web app's bearer token, which never leaves the page.
 *   method: HTTP verb.
 *   path: API path below the Mastodon origin.
 *   body: JSON body or null.
 *
 * Returns:
 *   The HTTP status and the parsed JSON answer.
 */
async function api(page, method, path, body = null) {
  return page.evaluate(
    async ([verb, url, payload]) => {
      const token = JSON.parse(document.getElementById("initial-state").textContent).meta.access_token;
      const response = await fetch(url, {
        method: verb,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", Accept: "application/json" },
        body: payload ? JSON.stringify(payload) : undefined,
      });
      return { status: response.status, data: await response.json().catch(() => null) };
    },
    [method, path, body],
  );
}

/**
 * Args:
 *   page: signed-in page on the web app; showcase posts, one favourite, one bookmark and one list are created until they exist.
 *
 * Returns:
 *   The id of the showcase status that carries the poll.
 */
async function seedShowcase(page) {
  const me = await api(page, "GET", "/api/v1/accounts/verify_credentials");
  expect(me.status, "the session must read its own account").toBe(200);
  const listed = await api(page, "GET", `/api/v1/accounts/${me.data.id}/statuses?limit=40`);
  const existing = listed.data.filter((status) => status.content.includes(SHOWCASE_TAG));
  for (let index = existing.length; index < SHOWCASE_POSTS; index += 1) {
    const body = { status: `Design showcase ${index + 1} #${SHOWCASE_TAG}`, visibility: "public" };
    if (index === 0) body.poll = { options: ["Light", "Dark"], expires_in: 604800 };
    const created = await api(page, "POST", "/api/v1/statuses", body);
    expect(created.status, "creating a showcase post").toBeLessThan(300);
    existing.unshift(created.data);
  }
  const newest = existing[0];
  await api(page, "POST", `/api/v1/statuses/${newest.id}/favourite`);
  await api(page, "POST", `/api/v1/statuses/${newest.id}/bookmark`);
  const lists = await api(page, "GET", "/api/v1/lists");
  if (!lists.data.some((list) => list.title === "Design showcase")) {
    await api(page, "POST", "/api/v1/lists", { title: "Design showcase" });
  }
  return (existing.find((status) => status.poll) || newest).id;
}

/**
 * Args:
 *   page: signed-in page; the administrator's web.color_scheme preference is set to `value` through the appearance settings form.
 *   value: one of auto, light, dark.
 */
async function pickColorScheme(page, value) {
  await gotoOnion(page, `${base}/settings/preferences/appearance`);
  await page.locator(`#user_settings_attributes_web\\.color_scheme_${value}`).check();
  await page.locator(SETTINGS_SUBMIT).first().click();
  await shown(HEADING)(page);
}

function guestViews() {
  const views = [
    { name: "explore", url: `${base}/explore`, prepare: shown(COLUMN) },
    { name: "about", url: `${base}/about`, prepare: shown(".about__header") },
    { name: "profile-public", url: `${base}/@${adminUsername}`, prepare: shown(".status") },
  ];
  if (ssoEnabled) return views;
  return views.concat([
    { name: "sign-in", url: `${base}/auth/sign_in`, prepare: shown(LOGIN_EMAIL) },
    {
      name: "sign-in-focus",
      url: `${base}/auth/sign_in`,
      prepare: async (page) => {
        await shown(LOGIN_EMAIL)(page);
        await page.locator(LOGIN_EMAIL).focus();
      },
    },
    { name: "password-reset", url: `${base}/auth/password/new`, prepare: shown(LOGIN_EMAIL) },
  ]);
}

function signedInViews(statusId) {
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  return [
    view("home", "/home", ".status"),
    {
      name: "compose-filled",
      url: `${base}/publish`,
      prepare: async (page) => {
        await shown(COMPOSE_TEXT)(page);
        await page.locator(COMPOSE_TEXT).first().fill(`Corporate design check #${SHOWCASE_TAG}`);
      },
    },
    view("notifications", "/notifications", COLUMN),
    view("local-timeline", "/public/local", ".status"),
    view("hashtag", `/tags/${SHOWCASE_TAG}`, ".status"),
    view("status-detail", `/@${adminUsername}/${statusId}`, ".detailed-status .poll"),
    {
      name: "status-menu",
      url: `${base}/@${adminUsername}/${statusId}`,
      prepare: async (page) => {
        await shown(STATUS_MENU)(page);
        await page.locator(STATUS_MENU).first().click();
        const menu = page.locator(".dropdown-menu").first();
        await expect(menu).toBeVisible({ timeout: resolveTimeout(10_000) });
        await expect(menu).toHaveCSS("opacity", "1", { timeout: resolveTimeout(10_000) });
      },
    },
    view("favourites", "/favourites", ".status"),
    view("bookmarks", "/bookmarks", ".status"),
    view("lists", "/lists", COLUMN),
    view("search", `/search?q=${SHOWCASE_TAG}`, COLUMN),
    view("profile-edit", "/profile/edit", COLUMN),
    view("settings-appearance", "/settings/preferences/appearance", "#user_settings_attributes_web\\.color_scheme_auto"),
    view("settings-account", "/auth/edit", HEADING),
    view("settings-filters", "/filters", HEADING),
    view("admin-dashboard", "/admin/dashboard", ".dashboard"),
    view("admin-accounts", "/admin/accounts", ADMIN_ROW),
    view("admin-branding", "/admin/settings/branding", "#form_admin_settings_site_title"),
    view("admin-appearance", "/admin/settings/appearance", "#form_admin_settings_custom_css"),
    view("admin-roles", "/admin/roles", HEADING),
  ];
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "mastodon");
});

test("design: the provisioned administrator signs in natively and reaches the admin dashboard", async ({ page }) => {
  test.skip(ssoEnabled, "with sso OMNIAUTH_ONLY hides the native form; the identity provider owns the password");
  await signIn(page);
  await gotoOnion(page, `${base}/admin/dashboard`);
  await expect(page).toHaveURL(/\/admin\/dashboard/);
  await shown(HEADING)(page);
});

test("design: Mastodon's custom CSS setting carries the token mapping exactly once", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}/explore`);
  await shown(COLUMN)(page);
  const links = page.locator("link[rel='stylesheet'][href*='/custom-']");
  await expect(links).toHaveCount(1);
  const sheet = new URL(await links.first().getAttribute("href"), `${base}/`).href;
  const css = await (await apiGetOnion(page.request, sheet)).text();
  expect(css.split(CUSTOM_CSS_BEGIN).length - 1, "one role block in the custom CSS").toBe(1);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-surface-1", `explore ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `explore ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: every image the custom CSS references is served", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}/explore`);
  const href = await page.locator("link[rel='stylesheet'][href*='/custom-']").first().getAttribute("href");
  const sheet = new URL(href, `${base}/`).href;
  const css = await (await apiGetOnion(page.request, sheet)).text();
  const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
    .filter((target) => !target.startsWith("data:"))
    .map((target) => new URL(target, sheet).href);
  for (const target of targets) {
    const served = await apiGetOnion(page.request, target);
    expect(`${served.status()} ${served.headers()["content-type"]}`, `${target} must be served as an image`).toMatch(/^200 image\//);
  }
});

test("design: the web app takes surfaces, primary action, text and dividers from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await shown(COMPOSE_TEXT)(page);
  await page.locator(COMPOSE_TEXT).first().fill("Design check");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-surface-1", `home ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `home ${mode}`);
    await assertToken(page, PRIMARY, "background-color", "--design-primary", `post button ${mode}`);
    await assertToken(page, PRIMARY, "color", "--design-on-primary", `post button ${mode}`);
    await assertToken(page, ".column-header", "border-top-color", "--design-border", `column header divider ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, COLUMN, "mastodon home");
  await assertReadable(page, [PRIMARY, ".column-header__title", { selector: ".navigation-panel .column-link", optional: true }], "mastodon home");
});

test("design: the administration divides rows with the border token", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, `${base}/admin/accounts`);
  await shown(ADMIN_ROW)(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, ADMIN_ROW, "border-bottom-color", "--design-border", `admin accounts row ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ADMIN_ROW, "mastodon admin");
  await assertReadable(page, [`${HEADING} h1`, ".admin-wrapper .sidebar ul a"], "mastodon admin");
});

test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(ssoEnabled, "with sso OMNIAUTH_ONLY hides the native form");
  await gotoOnion(page, `${base}/auth/sign_in`);
  await shown(LOGIN_EMAIL)(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
    await assertToken(page, LOGIN_SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, LOGIN_SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [LOGIN_SUBMIT, ".form-container label"], "mastodon sign-in");
});

test("design: a color scheme picked in the appearance settings is respected and mirrored", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.emulateMedia({ colorScheme: "light" });
  await signIn(page);
  const html = page.locator("html");
  const surface = () => tokenValue(page, "--design-surface-1", "background-color");
  await expect(html, "a fresh account follows the browser").not.toHaveAttribute("data-design-theme", /./);
  const lightSurface = await surface();
  try {
    await pickColorScheme(page, "dark");
    await gotoOnion(page, `${base}/home`);
    await shown(COLUMN)(page);
    await expect(html).toHaveAttribute("data-color-scheme", "dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(await surface(), "a dark pick switches the tokens while the browser prefers light").not.toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "home after a dark pick");
  } finally {
    await pickColorScheme(page, "auto");
  }
  await gotoOnion(page, `${base}/home`);
  await shown(COLUMN)(page);
  await expect(html, "auto hands the mode back to the browser").not.toHaveAttribute("data-design-theme", /./);
  await page.emulateMedia({ colorScheme: null });
});

test("design: navigation, auth page, administration and tab show the generated logo and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!wordmarkUrl, "logo replacement is disabled for this role");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  const navLogo = page.locator(".navigation-panel__logo svg.logo--wordmark");
  await expect(navLogo).toBeVisible({ timeout: resolveTimeout(10_000) });
  await expect(navLogo).toHaveCSS("background-image", `url("${wordmarkUrl}")`);
  await expect(navLogo.locator("use")).toHaveCSS("visibility", "hidden");
  const box = await navLogo.boundingBox();
  expect(box.width, "the navigation shows the wide lockup").toBeGreaterThan(box.height * 2);
  if (title) await expect(page).toHaveTitle(new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  await gotoOnion(page, `${base}/admin/dashboard`);
  await expect(page.locator(".admin-wrapper .sidebar img.logo--icon")).toHaveCSS("content", `url("${iconUrl}")`);
  await expect(page.locator("link[rel='icon'][sizes='32x32']")).toHaveAttribute("href", /\/site_uploads\//);
  await expect(page.locator("link[rel='apple-touch-icon'][sizes='180x180']")).toHaveAttribute("href", /\/site_uploads\//);
});

test("design: gallery of explore, auth, web app, settings and administration", async ({ page, browser }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(1_500_000));
  const failures = [];
  const guest = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    await captureDesignGallery(await guest.newPage(), guestViews());
  } catch (error) {
    failures.push(error.message);
  } finally {
    await guest.close();
  }
  await signIn(page);
  const views = signedInViews(await seedShowcase(page));
  for (let start = 0; start < views.length; start += GALLERY_CHUNK) {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const chunkPage = await context.newPage();
      await signIn(chunkPage, { fresh: true });
      await captureDesignGallery(chunkPage, views.slice(start, start + GALLERY_CHUNK));
    } catch (error) {
      failures.push(error.message);
    } finally {
      await context.close();
    }
  }
  expect(failures, failures.join("\n")).toEqual([]);
});
