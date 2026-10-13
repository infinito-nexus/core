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
  apiFetchOnion,
  apiGetOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  isAuthChain,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");
const { performKeycloakLoginForm } = require("./personas/utils/keycloak");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = decodeDotenvQuotedValue(requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN"));
const adminUsername = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"));
const adminPassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const designMark = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_MARK, "DESIGN_MARK"));

const MODES = ["light", "dark"];
const PASSWORD = "input[type='password']:visible";
const USERNAME = "input[autocomplete='username']:visible, input[type='text']:visible, input[type='email']:visible";
const SIGN_IN_AFFORDANCE = /^\s*(log\s?in|sign\s?in)\s*$/i;
const SIDEBAR_LOGO = "aside header a img";
const SIDEBAR_LINK = "aside nav a";
const MAIN = "main.color-default-solid";
const HEADING = "main h1, main h2";
const PRIMARY_BUTTON = "main button.color-primary-solid";
const DIVIDER = "main [class*='_table-header_']";
const HERO_HEADING = "main [class*='_introCard_'] h1";
const LOGIN_CARD = "main div.color-primary-solid[class*='_loginCard_']";
const TILE = "main div.color-primary-solid.shape-card";
const POPOVER = ".funkwhale.popover";
const USER_MENU = "aside header nav button.color-default-solid.shape-circle";
const ADMIN_MENU = "aside header nav button.color-default-ghost.shape-circle";
const SHOWCASE = "Design showcase";

/**
 * Args:
 *   page: Playwright page that ends signed in as the Funkwhale administrator, through Keycloak first when the proxy gates /login.
 */
async function signIn(page) {
  await gotoOnion(page, `${base}/login`);
  if (isAuthChain(page.url()) && new URL(page.url()).hostname !== canonicalDomain) {
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect.poll(() => new URL(page.url()).hostname, { timeout: resolveTimeout(60_000) }).toBe(canonicalDomain);
    await gotoOnion(page, `${base}/login`);
  }
  const password = page.locator(PASSWORD).first();
  await expect(password).toBeEditable({ timeout: resolveTimeout(30_000) });
  const username = page.locator(USERNAME).first();
  await expect(username).toBeEditable({ timeout: resolveTimeout(10_000) });
  await username.fill(adminUsername);
  await password.fill(adminPassword);
  await password.press("Enter");
  await expect(page.getByText(SIGN_IN_AFFORDANCE).first()).toBeHidden({ timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   page: signed-in Playwright page; the request runs inside it so the session and CSRF cookies travel along.
 *   method: HTTP verb.
 *   path: path below the Funkwhale origin.
 *   payload: JSON body, omitted for a request without one.
 *
 * Returns:
 *   The HTTP status and the parsed answer.
 */
async function api(page, method, path, payload) {
  return page.evaluate(
    async ([verb, url, body]) => {
      const csrf = (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || "";
      const response = await fetch(url, {
        method: verb,
        credentials: "same-origin",
        headers: { "content-type": "application/json", "x-csrftoken": decodeURIComponent(csrf) },
        body: body === null ? undefined : JSON.stringify(body),
      });
      return { status: response.status, data: await response.json().catch(() => null) };
    },
    [method, path, payload === undefined ? null : payload],
  );
}

/**
 * Args:
 *   page: signed-in Playwright page of the administrator; a public playlist named after the showcase gets created when it is missing.
 *
 * Returns:
 *   The uuid of the showcase playlist.
 */
async function seedShowcase(page) {
  const playlists = await api(page, "GET", `/api/v2/playlists/?q=${encodeURIComponent(SHOWCASE)}`);
  expect(playlists.status, "the session lists playlists").toBe(200);
  let playlist = (playlists.data.results || []).find((entry) => entry.name === SHOWCASE);
  if (!playlist) {
    const created = await api(page, "POST", "/api/v2/playlists/", { name: SHOWCASE, privacy_level: "everyone" });
    expect(created.status, "seeding the showcase playlist").toBeLessThan(300);
    playlist = created.data;
  }
  return playlist.uuid;
}

/**
 * Args:
 *   page: Playwright page on any Funkwhale view.
 *   hex: a #rrggbb literal.
 *
 * Returns:
 *   The literal as the browser serialises a computed color.
 */
async function computedColor(page, hex) {
  return page.evaluate((value) => {
    const probe = document.createElement("span");
    probe.style.color = value;
    document.body.appendChild(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  }, hex);
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

function opened(trigger) {
  return async (page) => {
    await shown(trigger)(page);
    await page.locator(trigger).first().click();
    const panel = page.locator(POPOVER).first();
    await expect(panel).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(panel).toHaveCSS("opacity", "1", { timeout: resolveTimeout(10_000) });
    await expect
      .poll(() => panel.evaluate((element) => element.getAnimations({ subtree: true }).filter((a) => a.playState === "running").length), {
        timeout: resolveTimeout(10_000),
      })
      .toBe(0);
  };
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await assertDesignTokens(page, "funkwhale");
  });

  test("design: the instance theming carries the light palette, the custom CSS mapping and the pod name", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await gotoOnion(page, `${base}/about`);
    await shown(MAIN)(page);
    const settings = await apiGetOnion(page.request, `${base}/api/v2/instance/settings/`);
    expect(settings.ok(), "the instance settings are public").toBe(true);
    const value = Object.fromEntries((await settings.json()).map((entry) => [`${entry.section}__${entry.name}`, entry.value]));
    for (const [name, token] of [
      ["ui__theme_primary_color", "--design-primary"],
      ["ui__theme_accent_color", "--design-link"],
    ]) {
      expect(await computedColor(page, value[name]), `${name} carries the light ${token}`).toBe(await tokenValue(page, token, "color"));
    }
    expect(String(value.ui__custom_css).startsWith(designMark), "the custom CSS setting carries the role mapping").toBe(true);
    await expect
      .poll(() => page.evaluate((mark) => [...document.querySelectorAll("style")].some((style) => style.textContent.startsWith(mark)), designMark))
      .toBe(true);
    if (title) {
      expect(value.instance__name, "the pod name is the configured title").toBe(title);
    }
  });

  test("design: the start page hero and the sign-in card read on token surfaces", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const size of [
      { width: 1440, height: 900 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(size);
      await gotoOnion(page, `${base}/about`);
      await shown(HERO_HEADING)(page);
      await assertReadable(page, [HERO_HEADING], `hero heading at ${size.width}px`);
    }
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await shown(LOGIN_CARD)(page);
      await assertToken(page, LOGIN_CARD, "background-color", "--design-surface-2", `sign-in card ${mode}`);
      await assertToken(page, LOGIN_CARD, "color", "--design-text", `sign-in card text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${LOGIN_CARD} label`, { selector: `${LOGIN_CARD} a[href]`, optional: true }], "sign-in card");
  });

  test("design: the signed-in interface takes page, sidebar backdrop, primary action, panels, text and dividers from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/library/podcasts`);
      await shown(TILE)(page);
      await assertToken(page, TILE, "background-color", "--design-surface-2", `podcast tile ${mode}`);
      await assertToken(page, TILE, "color", "--design-text", `podcast tile text ${mode}`);
      await gotoOnion(page, `${base}/library/playlists`);
      await shown(PRIMARY_BUTTON)(page);
      await assertToken(page, MAIN, "background-color", "--design-surface-1", `content ${mode}`);
      await assertToken(page, MAIN, "color", "--design-text", `text ${mode}`);
      await assertToken(page, "body", "background-color", "--design-surface-3", `sidebar backdrop ${mode}`);
      await assertToken(page, PRIMARY_BUTTON, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, PRIMARY_BUTTON, "color", "--design-on-primary", `primary action text ${mode}`);
      await gotoOnion(page, `${base}/manage/users/users`);
      await shown(DIVIDER)(page);
      await assertToken(page, DIVIDER, "border-top-color", "--design-border", `table divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await gotoOnion(page, `${base}/library/playlists`);
    await shown(PRIMARY_BUTTON)(page);
    await assertLightAndDark(page, MAIN, "funkwhale content");
    await assertReadable(page, [HEADING, PRIMARY_BUTTON, { selector: SIDEBAR_LINK, optional: true }], "funkwhale shell");
  });

  test("design: a theme picked in Funkwhale is mirrored onto the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await gotoOnion(page, `${base}/about`);
    await shown(MAIN)(page);
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");
    await page.evaluate(() => localStorage.setItem("vueuse-color-scheme", "dark"));
    await gotoOnion(page, `${base}/about`);
    await shown(MAIN)(page);
    await expect(page.locator("body")).toHaveClass(/theme-dark/);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    expect(await tokenValue(page, "--design-surface-1", "background-color"), "a dark theme picked in Funkwhale switches the tokens").not.toBe(lightSurface);
    await assertToken(page, MAIN, "background-color", "--design-surface-1", "content in the picked dark theme");
  });

  test("design: logo, favicon and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!faviconUrl && !title && !logoUrl, "logo and title replacement are disabled for this role");
    await gotoOnion(page, `${base}/about`);
    await shown(MAIN)(page);
    if (title) {
      await expect.poll(() => page.title(), { message: "the page carries the configured title" }).toContain(title);
    }
    if (faviconUrl) {
      await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    }
    if (logoUrl) {
      const logo = page.locator(SIDEBAR_LOGO).first();
      await expect(logo).toBeVisible({ timeout: resolveTimeout(10_000) });
      await expect.poll(() => logo.evaluate((image) => image.complete && image.naturalWidth > 0)).toBe(true);
      const box = await logo.boundingBox();
      expect(Math.abs(box.width - box.height), "the sidebar logo box is square").toBeLessThan(2);
      const served = await apiGetOnion(page.request, await logo.getAttribute("src"));
      const configured = await apiGetOnion(page.request, logoUrl);
      expect(served.ok() && configured.ok(), "the sidebar logo and the configured one are served").toBe(true);
      expect(Buffer.compare(await served.body(), await configured.body()), "the sidebar shows the configured logo").toBe(0);
    }
  });

  test("design: the platform administrator signs in with administration rights", async ({ page }) => {
    await signIn(page);
    const me = await api(page, "GET", "/api/v2/users/me/");
    expect(me.status, "the administrator holds a session").toBe(200);
    expect(me.data.is_superuser, "the administrator is a superuser").toBe(true);
    await gotoOnion(page, `${base}/manage/settings`);
    await expect(page.locator(HEADING).first()).toContainText(/instance settings/i, { timeout: resolveTimeout(10_000) });
  });

  test("design: a visitor cannot create an account", async ({ page }) => {
    const nodeinfo = await apiGetOnion(page.request, `${base}/api/v2/instance/nodeinfo/2.1/`);
    expect(nodeinfo.ok(), "nodeinfo answers").toBe(true);
    expect((await nodeinfo.json()).openRegistrations, "registration is closed").toBe(false);
    const suffix = Date.now().toString(36);
    const attempt = await apiFetchOnion(page.request, `${base}/api/v2/auth/registration/`, {
      method: "POST",
      data: { username: `visitor${suffix}`, email: `visitor${suffix}@example.invalid`, password1: `Pw-${suffix}-x9!Q`, password2: `Pw-${suffix}-x9!Q` },
    });
    expect(attempt.status(), "a visitor registration is refused").toBe(403);
  });

  function visitorViews() {
    const views = [
      { name: "start", url: `${base}/`, prepare: shown(MAIN) },
      { name: "about", url: `${base}/about`, prepare: shown(HEADING) },
      { name: "password-reset", url: `${base}/auth/password/reset`, prepare: shown(HEADING) },
      { name: "signup", url: `${base}/signup`, prepare: shown(HEADING) },
    ];
    if (isServiceEnabled("sso")) return views;
    return [
      { name: "login", url: `${base}/login`, prepare: shown(PASSWORD) },
      {
        name: "login-focus",
        url: `${base}/login`,
        prepare: async (page) => {
          await shown(PASSWORD)(page);
          await page.locator(USERNAME).first().focus();
        },
      },
      ...views,
    ];
  }

  function signedInViews(playlistUuid) {
    const view = (name, path, selector = HEADING) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
    return [
      view("home", "/library"),
      view("artists", "/library/artists"),
      view("albums", "/library/albums"),
      view("playlists", "/library/playlists", PRIMARY_BUTTON),
      view("playlist", `/library/playlists/${playlistUuid}`),
      view("radios", "/library/radios"),
      view("podcasts", "/library/podcasts"),
      view("channels", "/library/channels"),
      view("favorites", "/favorites"),
      view("search", `/search?q=${encodeURIComponent("design")}`),
      view("settings", "/settings"),
      view("notifications", "/notifications"),
      view("profile", `/@${adminUsername}`),
      view("admin-settings", "/manage/settings"),
      view("admin-users", "/manage/users/users", DIVIDER),
      view("admin-invitations", "/manage/users/invitations"),
      view("admin-library", "/manage/library/artists"),
      view("moderation-domains", "/manage/moderation/domains"),
      view("moderation-reports", "/manage/moderation/reports"),
      { name: "user-menu", url: `${base}/library`, prepare: opened(USER_MENU) },
      { name: "admin-menu", url: `${base}/library`, prepare: opened(ADMIN_MENU) },
    ];
  }

  test("design: gallery of start page, library, settings and administration", async ({ browser, page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_800_000));
    const failures = [];
    const visitor = await browser.newPage({ ignoreHTTPSErrors: true });
    try {
      await captureDesignGallery(visitor, visitorViews());
    } catch (error) {
      failures.push(error.message);
    }
    await visitor.close();
    await signIn(page);
    const playlistUuid = await seedShowcase(page);
    try {
      await captureDesignGallery(page, signedInViews(playlistUuid));
    } catch (error) {
      failures.push(error.message);
    }
    expect(failures, "design gallery views failed").toEqual([]);
  });
};
