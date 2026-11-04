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
const { adminPassword, adminUsername, baseUrl, ssoLoginAndAssertDashboard } = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");

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
const JOIN = 'button[form="join-form"][type="submit"]';
const HANGUP = '[data-testid="toolbarEndCallButton"]';
const MORE_BUTTON = '[data-testid="toolbarMenuButton"]';
const MORE_MENU = '[data-testid="moreMenu"]:has(.MuiAvatar-root) .MuiPaper-root';
const ROOM_SIDEBAR = `aside:has(> div > aside ${HANGUP})`;
const TOOLBAR_BUTTON = `aside:has(> div > ${HANGUP}) .MuiIconButton-root:not(${HANGUP})`;
const MODERATION_STRIP = "aside > .MuiTabs-vertical > .MuiTabs-scroller";
const PANEL_TABS = 'aside [role="tabpanel"] .MuiTabs-root:not(.MuiTabs-vertical)';
const HEADER_TILE = "header > div > * > .MuiStack-root";

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
 *   page: signed-in Playwright page that joins the meeting room of `event` from its lobby.
 *   event: showcase event with its `room.id`.
 */
async function joinRoom(page, event) {
  await gotoOnion(page, `${BASE}/room/${event.room.id}`);
  await shown(LOBBY)(page);
  await page.locator(JOIN).click();
  await expect(page.locator(HANGUP)).toBeVisible({ timeout: resolveTimeout(60_000) });
  await animationsSettled(page);
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
    {
      name: "room",
      url: `${BASE}/room/${first.room.id}`,
      prepare: async (page) => {
        await shown(LOBBY)(page);
        await page.locator(JOIN).click();
        await shown(HANGUP)(page);
        await page.mouse.move(1, 1);
      },
    },
    {
      name: "room-more-menu",
      url: `${BASE}/room/${first.room.id}`,
      prepare: async (page) => {
        await shown(LOBBY)(page);
        await page.locator(JOIN).click();
        await shown(HANGUP)(page);
        await page.locator(MORE_BUTTON).click();
        await shown(MORE_MENU)(page);
        await page.mouse.move(1, 1);
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

test("design: the dashboard and conference theme settings drive the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(300_000));
  const root = page.locator("html");
  const save = async (dashboard, conference) => {
    await gotoOnion(page, `${BASE}/dashboard/settings/general`);
    await shown(SETTINGS_FORM)(page);
    for (const [label, field, value] of [
      ["Dashboard theme", "dashboard-theme", dashboard],
      ["Conference theme", "conference-theme", conference],
    ]) {
      await page.getByRole("combobox", { name: new RegExp(`^${label}`) }).click();
      await page.locator(`${MENU} [role="option"][data-value="${value}"]`).click();
      await expect(page.locator(`${SETTINGS_FORM} input[name="${field}"]`)).toHaveValue(value);
    }
    const stored = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/v1/users/me" && response.request().method() === "PATCH",
      { timeout: resolveTimeout(30_000) },
    );
    await page.locator(`${SETTINGS_FORM} button[type="submit"]`).click();
    expect((await stored).status(), "the settings form stores both themes").toBeLessThan(300);
  };
  await page.emulateMedia({ colorScheme: "light" });
  await signIn(page);
  const [event] = await seedShowcase(page);
  try {
    await save("dark", "light");
    await gotoOnion(page, `${BASE}/dashboard/settings/general`);
    await shown(SETTINGS_FORM)(page);
    await expect(root, "a dark dashboard theme pins the palette to dark").toHaveAttribute("data-design-theme", "dark");
    await assertToken(page, MAIN, "color", "--design-text", "dashboard on its dark theme");
    await page.emulateMedia({ colorScheme: "dark" });
    await gotoOnion(page, `${BASE}/room/${event.room.id}`);
    await shown(LOBBY)(page);
    await expect(root, "a light conference theme pins the lobby to light").toHaveAttribute("data-design-theme", "light");
    await assertToken(page, `${LOBBY} > div`, "background-color", "--design-surface-2", "lobby on its light theme");
    await save("system", "system");
    await gotoOnion(page, `${BASE}/room/${event.room.id}`);
    await shown(LOBBY)(page);
    await expect(root, "system leaves the palette to the browser").not.toHaveAttribute("data-design-theme", /.+/);
  } finally {
    await page.emulateMedia({ colorScheme: null });
    await api(page, "PATCH", "/users/me", { dashboard_theme: "system", conference_theme: "system" });
  }
});

test("design: the lobby and the conference room take surfaces, text and the leave action from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(300_000));
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  const [event] = await seedShowcase(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${BASE}/room/${event.room.id}`);
    await shown(LOBBY)(page);
    await assertToken(page, `${LOBBY} > div`, "background-color", "--design-surface-2", `lobby panel ${mode}`);
    await assertToken(page, `${LOBBY} > div`, "color", "--design-text", `lobby panel ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [`${LOBBY} .MuiTypography-root`, JOIN], "opentalk lobby");
  await joinRoom(page, event);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, ROOM_SIDEBAR, "background-color", "--design-surface-2", `room sidebar ${mode}`);
    await assertToken(page, ROOM_SIDEBAR, "color", "--design-text", `room sidebar ${mode}`);
    await assertToken(page, TOOLBAR_BUTTON, "background-color", "--design-surface-1", `toolbar button ${mode}`);
    await assertToken(page, `${TOOLBAR_BUTTON} svg`, "fill", "--design-text", `toolbar icon ${mode}`);
    await assertToken(page, HANGUP, "background-color", "--design-danger", `leave action ${mode}`);
    await assertToken(page, `${HANGUP} svg`, "fill", "--design-on-danger", `leave action ${mode}`);
    await assertToken(page, MODERATION_STRIP, "background-color", "--design-surface-3", `moderation strip ${mode}`);
    await assertToken(page, PANEL_TABS, "background-color", "--design-surface-3", `panel tabs ${mode}`);
    await assertToken(page, HEADER_TILE, "background-color", "--design-surface-2", `header tile ${mode}`);
    await assertToken(page, HEADER_TILE, "color", "--design-text", `header tile ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ROOM_SIDEBAR, "opentalk room");
  await assertReadable(page, ["header .MuiTypography-root", { selector: `${ROOM_SIDEBAR} .MuiTypography-root`, optional: true }], "opentalk room");
  await page.locator(MORE_BUTTON).click();
  await shown(MORE_MENU)(page);
  await page.mouse.move(1, 1);
  await assertToken(page, MORE_MENU, "background-color", "--design-surface-2", "more menu");
  await assertToken(page, MORE_BUTTON, "background-color", "--design-primary", "more button while its menu is open");
});

test("design: the dashboard shows the generated logo and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
  test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
  await signIn(page);
  if (title) {
    await expect(page).toHaveTitle(new RegExp(` in ${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  }
  if (logoUrl) {
    expect(faviconUrl, "DESIGN_FAVICON_URL is written whenever the logo is").toBeTruthy();
    await expect(page.locator(`${MAIN} ${LOGO}`)).toHaveCSS("background-image", `url("${logoUrl}")`);
    await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    const box = await page.locator(`${MAIN} ${LOGO}`).boundingBox();
    expect(box.width, "the logo box of the dashboard is wider than high").toBeGreaterThan(box.height * 1.5);
    const svg = await (await apiGetOnion(page.request, logoUrl)).text();
    const dark = svg.match(/@media \(prefers-color-scheme: dark\)\{text\{fill:(#[0-9a-fA-F]{3,8});/);
    const light = svg.match(/<text[^>]*\sfill="(#[0-9a-fA-F]{3,8})"/);
    expect(dark, "the lockup carries a dark rule for its title").not.toBeNull();
    expect(light, "the lockup title has a light fill").not.toBeNull();
    const resolve = (hex) =>
      page.evaluate((color) => {
        const probe = document.createElement("span");
        probe.style.color = color;
        document.body.append(probe);
        const value = getComputedStyle(probe).color;
        probe.remove();
        return value;
      }, hex);
    for (const [mode, fill] of [
      ["light", light[1]],
      ["dark", dark[1]],
    ]) {
      await page.emulateMedia({ colorScheme: mode });
      expect(await resolve(fill), `lockup title fill ${mode}`).toBe(await tokenValue(page, "--design-link", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
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
