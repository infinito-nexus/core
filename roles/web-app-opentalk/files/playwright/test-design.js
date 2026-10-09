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
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { adminPassword, adminUsername, baseUrl, ssoLoginAndAssertDashboard } = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const BASE = baseUrl.replace(/\/+$/, "");
const MAIN = "#main-content-dashboard";
const FRAME = '[data-testid="PrimaryNavigation"]';
const NAV_ITEM = `${FRAME} [data-testid="PrimaryNavItem"]`;
const NAV_ACTIVE = `${FRAME} .active-link`;
const SUBNAV = '[data-testid="SecondaryNavigation"]';
const SUBNAV_ITEM = '[data-testid="SecondaryNavItem"]';
const SETTINGS_FORM = 'form[name="settings-general-form"]';
const SAVE = `${MAIN} .MuiButton-containedSecondary`;
const DIVIDER = `${MAIN} .MuiDivider-root`;
const MENU = ".MuiMenu-paper";
const LOGO = 'svg[viewBox="0 0 206.392 45.061"]';
const ERROR_TITLE = "#root .MuiTypography-h5";
const LOBBY = '[data-testid="selfTest"]';
const EMPTY_ENTRY = `${MAIN} [data-testid="empty-entry"]`;
const SHOWCASE = ["Design Showcase Weekly", "Design Showcase Review"];

/**
 * Args:
 *   page: Playwright page whose finite animations must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          document
            .getAnimations()
            .some((a) => a.playState === "running" && a.effect?.getComputedTiming().iterations !== Infinity),
        ),
      { timeout: resolveTimeout(10_000) },
    )
    .toBe(false);
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    await animationsSettled(page);
  };
}

/**
 * Args:
 *   page: signed-in Playwright page; the call runs inside the page with the access token the app keeps in its own storage.
 *   method: HTTP verb.
 *   path: path below `/v1`.
 *   body: JSON body for writing calls.
 *
 * Returns:
 *   The parsed JSON body, or null for an empty response.
 */
async function api(page, method, path, body) {
  const result = await page.evaluate(
    async ([verb, url, payload]) => {
      const response = await fetch(url, {
        method: verb,
        headers: {
          authorization: `Bearer ${window.localStorage.getItem("access_token")}`,
          "content-type": "application/json",
        },
        body: payload === null ? undefined : JSON.stringify(payload),
      });
      return { status: response.status, text: await response.text() };
    },
    [method, `${BASE}/v1${path}`, body === undefined ? null : body],
  );
  expect(result.status, `${method} /v1${path} answered ${result.status}`).toBeLessThan(300);
  return result.text ? JSON.parse(result.text) : null;
}

/**
 * Args:
 *   page: Playwright page that ends signed in on the dashboard, with both theme settings of the account on `system`.
 */
async function signIn(page) {
  skipUnlessServiceEnabled("sso");
  await ssoLoginAndAssertDashboard(page, adminUsername, adminPassword);
  await api(page, "PATCH", "/users/me", { dashboard_theme: "system", conference_theme: "system" });
  await gotoOnion(page, `${BASE}/dashboard`);
  await shown(MAIN)(page);
}

/**
 * Args:
 *   page: signed-in Playwright page that seeds the showcase meetings the lists and detail pages show.
 *
 * Returns:
 *   The showcase events, each with its `id` and its `room.id`.
 */
async function seedShowcase(page) {
  const listed = await api(page, "GET", "/events?per_page=100");
  const existing = Array.isArray(listed) ? listed : [];
  const events = [];
  for (const name of SHOWCASE) {
    events.push(
      existing.find((event) => event.title === name) ||
        (await api(page, "POST", "/events", {
          title: name,
          description: "Showcase meeting of the design gallery.",
          is_time_independent: true,
          waiting_room: false,
          password: null,
          e2e_encryption: false,
          is_adhoc: false,
          has_shared_folder: false,
          show_meeting_details: true,
        })),
    );
  }
  return events;
}

/**
 * Args:
 *   page: Playwright page on a dashboard route; a navigation the viewport collapses gets opened.
 */
async function navigationOpened(page) {
  const toggle = page.getByRole("button", { name: /open navigation/i });
  if (await toggle.isVisible()) {
    await toggle.click();
  }
  await shown(NAV_ITEM)(page);
}

function visitorViews() {
  const view = (name, path) => ({ name, url: `${BASE}${path}`, prepare: shown(ERROR_TITLE) });
  return [
    view("not-found", "/design-showcase-missing"),
    view("server-issue", "/server-issue"),
    view("invite-invalid", "/invite/00000000-0000-4000-8000-000000000000"),
    view("room-invite-invalid", "/room/00000000-0000-4000-8000-000000000000?invite=00000000-0000-4000-8000-000000000000"),
  ];
}

function signedInViews([first, second]) {
  const view = (name, path, selector) => ({ name, url: `${BASE}${path}`, prepare: shown(selector) });
  const opened = (name, path, ready, trigger, panel) => ({
    name,
    url: `${BASE}${path}`,
    prepare: async (page) => {
      await shown(ready)(page);
      await page.locator(trigger).first().click();
      await shown(panel)(page);
      await expect(page.locator(panel).first()).toHaveCSS("opacity", "1");
    },
  });
  return [
    view("dashboard-home", "/dashboard", `${MAIN} .MuiButton-root`),
    {
      name: "navigation-hover",
      url: `${BASE}/dashboard`,
      prepare: async (page) => {
        await shown(`${MAIN} .MuiButton-root`)(page);
        await navigationOpened(page);
        const box = await page.locator(NAV_ITEM).nth(1).boundingBox();
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await animationsSettled(page);
      },
    },
    {
      name: "navigation-focus",
      url: `${BASE}/dashboard`,
      prepare: async (page) => {
        await shown(`${MAIN} .MuiButton-root`)(page);
        await navigationOpened(page);
        await page.locator(NAV_ITEM).first().focus();
        await page.keyboard.press("Tab");
        await animationsSettled(page);
      },
    },
    opened("join-meeting-dialog", "/dashboard", `${MAIN} .MuiButton-root`, `${MAIN} button:has-text("Join")`, ".MuiDialog-paper"),
    view("meetings", "/dashboard/meetings", '[data-testid^="events-page-header"]'),
    view("meeting-details", `/dashboard/meetings/${first.id}`, '[data-testid="event-details"]'),
    view("meeting-create", "/dashboard/meetings/create", `${MAIN} input`),
    view("meeting-edit", `/dashboard/meetings/update/${second.id}/0`, `${MAIN} input`),
    view("meeting-edit-participants", `/dashboard/meetings/update/${second.id}/1`, `${MAIN} input`),
    view("settings-general", "/dashboard/settings/general", SETTINGS_FORM),
    opened("settings-theme-menu", "/dashboard/settings/general", SETTINGS_FORM, `${SETTINGS_FORM} [role="combobox"]`, MENU),
    view("settings-profile", "/dashboard/settings/profile", `${MAIN} input`),
    view("settings-account", "/dashboard/settings/account", `${MAIN} .MuiTypography-root`),
    view("settings-storage", "/dashboard/settings/storage", `${MAIN} .MuiTypography-root`),
    {
      name: "settings-navigation",
      url: `${BASE}/dashboard/settings/general`,
      prepare: async (page) => {
        await shown(SETTINGS_FORM)(page);
        await navigationOpened(page);
        const box = await page.locator(SUBNAV_ITEM).nth(1).boundingBox();
        if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await animationsSettled(page);
      },
    },
    view("help", "/dashboard/help/user-manual", `${MAIN} .MuiTypography-root`),
    view("lobby", `/room/${first.room.id}`, LOBBY),
    {
      name: "lobby-name-focus",
      url: `${BASE}/room/${first.room.id}`,
      prepare: async (page) => {
        await shown(LOBBY)(page);
        await page.locator("#join-form input").first().focus();
        await animationsSettled(page);
      },
    },
  ];
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "opentalk");
});

test("design: visitor pages sit on the frame", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${BASE}/design-showcase-missing`);
    await shown(ERROR_TITLE)(page);
    await assertToken(page, "body", "background-color", "--design-frame", `visitor page ${mode}`);
    await assertToken(page, ERROR_TITLE, "color", "--design-on-frame", `visitor page ${mode}`);
  }
});

test("design: the dashboard takes frame, surfaces, actions, text and dividers from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(240_000));
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${BASE}/dashboard/settings/general`);
    await shown(SETTINGS_FORM)(page);
    await expect(page.locator("html"), "with both themes on system the palette follows the browser").not.toHaveAttribute(
      "data-design-theme",
      /.+/,
    );
    await assertToken(page, FRAME, "background-color", "--design-frame", `frame ${mode}`);
    await assertToken(page, NAV_ITEM, "color", "--design-on-frame", `frame ${mode}`);
    await assertToken(page, NAV_ACTIVE, "background-color", "--design-frame-active", `selected entry ${mode}`);
    await assertToken(page, SUBNAV, "background-color", "--design-surface-3", `secondary navigation ${mode}`);
    await assertToken(page, MAIN, "color", "--design-text", `content ${mode}`);
    await assertToken(page, `${MAIN} .MuiTypography-h1`, "color", "--design-text", `heading ${mode}`);
    await assertToken(page, DIVIDER, "border-bottom-color", "--design-border", `content divider ${mode}`);
    await assertToken(page, SAVE, "background-color", "--design-primary", `primary action ${mode}`);
    await assertToken(page, SAVE, "color", "--design-on-primary", `primary action ${mode}`);
    await assertToken(page, `${SETTINGS_FORM} .MuiInputBase-root`, "background-color", "--design-surface-2", `field ${mode}`);
    await page.locator(NAV_ITEM).nth(1).hover();
    await assertToken(page, `${NAV_ITEM}:hover`, "background-color", "--design-frame-hover", `hovered entry ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await gotoOnion(page, `${BASE}/dashboard/settings/general`);
  await shown(SETTINGS_FORM)(page);
  await assertLightAndDark(page, `${MAIN} .MuiTypography-h1`, "opentalk dashboard");
  await assertReadable(page, [`${MAIN} .MuiTypography-h1`, SAVE, NAV_ITEM, NAV_ACTIVE, SUBNAV_ITEM], "opentalk dashboard");
  await gotoOnion(page, `${BASE}/dashboard`);
  await shown(`${MAIN} .MuiButton-root`)(page);
  await assertReadable(
    page,
    [`${MAIN} .MuiButton-containedSecondary`, `${MAIN} .MuiButton-containedPrimary`, { selector: EMPTY_ENTRY, optional: true }],
    "opentalk home",
  );
});

test("design: every focus stop inside the frame draws its indicator in the frame text color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const expected = await tokenValue(page, "--design-on-frame", "color");
  await page.locator(NAV_ITEM).first().focus();
  await page.keyboard.press("Shift+Tab");
  const stops = [];
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate((frame) => {
      const el = document.activeElement;
      if (!el || !el.closest(frame)) return null;
      const cs = getComputedStyle(el);
      return { name: el.textContent.trim().slice(0, 30), style: cs.outlineStyle, color: cs.outlineColor };
    }, FRAME);
    if (stop) stops.push(stop);
  }
  expect(stops.length, "the frame holds focus stops").toBeGreaterThan(0);
  for (const stop of stops) {
    expect(stop.style, `${stop.name}: focus outline`).not.toBe("none");
    expect(stop.color, `${stop.name}: focus outline color`).toBe(expected);
  }
});

test("design: the native theme setting drives the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(180_000));
  await page.emulateMedia({ colorScheme: "light" });
  await signIn(page);
  const root = page.locator("html");
  const light = await tokenValue(page, "--design-surface-1", "color");
  try {
    await api(page, "PATCH", "/users/me", { dashboard_theme: "dark" });
    await gotoOnion(page, `${BASE}/dashboard/settings/general`);
    await shown(SETTINGS_FORM)(page);
    await expect(root).toHaveAttribute("data-design-theme", "dark");
    expect(await tokenValue(page, "--design-surface-1", "color"), "the dark palette must differ").not.toBe(light);
    await assertToken(page, MAIN, "color", "--design-text", "switched to dark");
    await api(page, "PATCH", "/users/me", { dashboard_theme: "system" });
    await gotoOnion(page, `${BASE}/dashboard/settings/general`);
    await shown(SETTINGS_FORM)(page);
    await expect(root).not.toHaveAttribute("data-design-theme", /.+/);
    expect(await tokenValue(page, "--design-surface-1", "color")).toBe(light);
  } finally {
    await api(page, "PATCH", "/users/me", { dashboard_theme: "system", conference_theme: "system" });
  }
});

test("design: the dashboard shows the generated logo and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
  await signIn(page);
  if (title) {
    await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  if (logoUrl) {
    await expect(page.locator(`${MAIN} ${LOGO}`)).toHaveCSS("background-image", `url("${logoUrl}")`);
    await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    const box = await page.locator(`${MAIN} ${LOGO}`).boundingBox();
    expect(box.width, "the logo box of the dashboard is wider than high").toBeGreaterThan(box.height * 1.5);
  }
});

test("design: gallery of dashboard, meetings, settings, lobby and visitor pages", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  await page.context().grantPermissions(["camera", "microphone"]);
  await signIn(page);
  const showcase = await seedShowcase(page);
  await captureDesignGallery(page, [...signedInViews(showcase), ...visitorViews()]);
});
