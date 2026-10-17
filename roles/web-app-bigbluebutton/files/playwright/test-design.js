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
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { isOnionTarget, isSplitRealmOidc, resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.BBB_BASE_URL || "").replace(/\/$/, "");
const oidcIssuer = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const ssoEnabled = process.env.SSO_SERVICE_ENABLED === "true";

const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const EMAIL = "#signInFormEmail";
const PASSWORD = "#signInFormPwd";
const SUBMIT = "form button[type='submit'].btn-brand";
const NAVBAR = "#navbar";
const LOGO = "img[alt='CompanyLogo']";
const HERO = "#homepage-hero h1";
const ROOM_CARD = "#room-card";
const NEW_ROOM = "button.btn-brand.ms-auto";
const ADMIN = "#admin-panel";
const USERS_ROW = "#manage-users-table tbody tr";
const SHOWCASE = "Design Showcase";
const MEETING_NAVBAR = "#Navbar";
const MEETING_ACTIONS = "#ActionsBar";
const MEETING_TITLE = "#presentationTitle";
const MEETING_USERS = "[data-test='userListContainer']";
const MEETING_INPUT = "#message-input";
const MEETING_LEAVE = "[data-test='leaveMeetingDropdown']";
const MEETING_AUDIO_MODAL = "[data-test='audioModal']";
const MEETING_AUDIO_CLOSE = "[data-test='closeModal']";

test.use({ ignoreHTTPSErrors: true });

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

function skipUnreachable() {
  test.skip(isOnionTarget(), "BigBlueButton is WebRTC (UDP/ICE); not served over Tor");
  test.skip(ssoEnabled && isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the administrator on /rooms, through Keycloak when sso is on, through Greenlight's own form otherwise.
 */
async function signIn(page) {
  await page.context().clearCookies();
  if (ssoEnabled) {
    await gotoOnion(page, `${base}/?sso=true`);
    await page.waitForURL((u) => u.toString().startsWith(`${oidcIssuer}/protocol/openid-connect/auth`), {
      timeout: resolveTimeout(60_000),
    });
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await page.waitForURL(
      (u) => u.toString().startsWith(`${base}/`) && !u.toString().includes("/auth/openid_connect") && !u.toString().includes("sso=true"),
      { timeout: resolveTimeout(60_000) },
    );
    await gotoOnion(page, `${base}/rooms`);
  } else {
    await gotoOnion(page, `${base}/signin`);
    await expect(page.locator(EMAIL)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(EMAIL).fill(adminEmail);
    await expect(page.locator(PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(PASSWORD).fill(adminPassword);
    await page.locator(SUBMIT).click({ timeout: resolveTimeout(10_000) });
  }
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(30_000), message: "the administrator must land on /rooms" })
    .toMatch(/\/rooms(\/|\?|$)/);
  await shown(NAVBAR)(page);
}

/**
 * Args:
 *   page: Playwright page signed in as the administrator; creates the showcase room through Greenlight's API when it is missing.
 *
 * Returns:
 *   {room: friendly id of the showcase room, user: id of the administrator}
 */
async function seedShowcase(page) {
  return page.evaluate(async (name) => {
    const token = document.querySelector("meta[name=csrf-token]").getAttribute("content");
    const headers = { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-TOKEN": token };
    const session = await (await fetch("/api/v1/sessions.json", { headers })).json();
    const find = async () => {
      const list = await (await fetch(`/api/v1/rooms.json?search=${encodeURIComponent(name)}`, { headers })).json();
      return (list.data || []).find((room) => room.name === name);
    };
    let room = await find();
    if (!room) {
      await fetch("/api/v1/rooms.json", {
        method: "POST",
        headers,
        body: JSON.stringify({ room: { name, user_id: session.data.id } }),
      });
      room = await find();
    }
    return { room: room.friendly_id, user: session.data.id };
  }, SHOWCASE);
}

/**
 * Args:
 *   page: Playwright page signed in as the administrator; starts or joins the showcase room meeting and closes the audio dialog.
 *   room: friendly id of the showcase room.
 */
async function joinMeeting(page, room) {
  await gotoOnion(page, `${base}/rooms/${room}`);
  await page.getByRole("button", { name: /(start|join) meeting/i }).first().click({ timeout: resolveTimeout(20_000) });
  await page.waitForURL(/html5client/, { timeout: resolveTimeout(60_000) });
  await shown(MEETING_USERS)(page);
  const close = page.locator(MEETING_AUDIO_CLOSE).first();
  await close.waitFor({ state: "visible", timeout: resolveTimeout(15_000) });
  await close.click();
  await expect(page.locator(MEETING_AUDIO_MODAL)).toHaveCount(0, { timeout: resolveTimeout(10_000) });
  const details = page.getByText("Session Details", { exact: true });
  const appeared = await details.waitFor({ state: "visible", timeout: resolveTimeout(5_000) }).then(
    () => true,
    () => false,
  );
  if (appeared) await page.keyboard.press("Escape");
  await expect(details).toBeHidden({ timeout: resolveTimeout(10_000) });
}

test("design: the meeting client takes frame, panels, primary action, title and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  test.setTimeout(resolveTimeout(240_000));
  await signIn(page);
  await joinMeeting(page, (await seedShowcase(page)).room);
  await expect(page.locator("link[rel='stylesheet'][href*='/meeting.css']")).toHaveCount(1);
  const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
  if (title) {
    await expect.poll(async () => (await page.title()).startsWith(`${title} - `), { message: "the meeting title starts with the configured title" }).toBe(true);
  }
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-frame", `meeting stage ${mode}`);
    await assertToken(page, MEETING_NAVBAR, "background-color", "--design-frame", `meeting header ${mode}`);
    await assertToken(page, MEETING_ACTIONS, "background-color", "--design-frame", `meeting actions bar ${mode}`);
    await assertToken(page, MEETING_TITLE, "color", "--design-on-frame", `presentation title ${mode}`);
    await assertToken(page, MEETING_USERS, "background-color", "--design-surface-2", `user list ${mode}`);
    await assertToken(page, MEETING_USERS, "color", "--design-text", `user list text ${mode}`);
    await assertToken(page, MEETING_INPUT, "background-color", "--design-surface-2", `chat input ${mode}`);
    await assertToken(page, MEETING_LEAVE, "background-color", "--design-danger", `leave button ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, MEETING_USERS, "meeting user list");
  await assertReadable(page, [MEETING_USERS, MEETING_INPUT, MEETING_TITLE, MEETING_LEAVE], "meeting client");
});

test("design: the administrator signs in with the account the role provisions", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  await signIn(page);
  await gotoOnion(page, `${base}/admin/users`);
  await shown(USERS_ROW)(page);
});

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  await gotoOnion(page, `${base}/`);
  await shown(HERO)(page);
  await assertDesignTokens(page, "bigbluebutton");
});

test("design: the home page takes surface, header, primary and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  await page.setViewportSize(DESKTOP);
  await gotoOnion(page, `${base}/`);
  await shown(HERO)(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-surface-1", `body ${mode}`);
    await assertToken(page, NAVBAR, "background-color", "--design-surface-2", `navbar ${mode}`);
    await assertToken(page, HERO, "color", "--design-text", `hero ${mode}`);
    await assertToken(page, ".homepage-card-icon-circle", "background-color", "--design-primary", `feature icon ${mode}`);
    await assertToken(page, ".homepage-card-icon-circle svg", "color", "--design-on-primary", `feature icon glyph ${mode}`);
    await assertToken(page, "#footer a", "color", "--design-link", `footer link ${mode}`);
    await assertToken(page, "#footer-container", "border-top-color", "--design-border", `footer divider ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, "body", "bigbluebutton home");
  await assertReadable(page, [HERO, "#footer a"], "bigbluebutton home");
});

test("design: the sign-in button carries the primary with its on-color in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  test.skip(ssoEnabled, "the identity provider replaces the native sign-in form");
  await gotoOnion(page, `${base}/signin`);
  await shown(EMAIL)(page);
  await page.locator(EMAIL).evaluate((field) => field.blur());
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
    await assertToken(page, EMAIL, "background-color", "--design-surface-2", `email field ${mode}`);
    await assertToken(page, EMAIL, "border-top-color", "--design-border-strong", `email field ${mode}`);
    await page.locator(SUBMIT).hover();
    await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
    await expect(page.locator(SUBMIT), `hovered sign-in ${mode} has no inset shadow`).toHaveCSS("box-shadow", "none");
    await page.mouse.move(0, 0);
    await page.locator(EMAIL).focus();
    await assertToken(page, EMAIL, "border-top-color", "--design-link", `focused email field ${mode}`);
    await page.locator(EMAIL).evaluate((field) => field.blur());
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [SUBMIT, ".card-title", "label"], "bigbluebutton sign-in");
});

test("design: the site settings hold the light primary and the generated logo", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await page.emulateMedia({ colorScheme: "light" });
  const stored = await page.evaluate(async () => {
    const response = await fetch("/api/v1/site_settings.json?names[]=PrimaryColor&names[]=PrimaryColorLight", {
      headers: { Accept: "application/json" },
    });
    return (await response.json()).data;
  });
  const probe = (value) =>
    page.evaluate((color) => {
      const span = document.createElement("span");
      span.style.color = color;
      document.body.appendChild(span);
      const computed = getComputedStyle(span).color;
      span.remove();
      return computed;
    }, value);
  expect(await probe(stored.PrimaryColor), "PrimaryColor must be the light primary").toBe(
    await tokenValue(page, "--design-primary", "color"),
  );
  expect(await probe(stored.PrimaryColorLight), "PrimaryColorLight must be the light primary-100").toBe(
    await tokenValue(page, "--design-primary-100", "color"),
  );
  await page.emulateMedia({ colorScheme: null });
  test.skip(!logoUrl, "logo replacement is disabled for this role");
  const logo = page.locator(`${NAVBAR} ${LOGO}`).first();
  await expect(logo).toHaveAttribute("src", logoUrl);
  await expect.poll(() => logo.evaluate((img) => img.complete && img.naturalWidth), { timeout: resolveTimeout(10_000) }).toBeGreaterThan(0);
  const box = await logo.boundingBox();
  expect(box && box.width > box.height * 2, "the header logo is a wide lockup").toBe(true);
});

test("design: the rooms list and its card follow the palette in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await seedShowcase(page);
  await gotoOnion(page, `${base}/rooms`);
  await shown(ROOM_CARD)(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, ROOM_CARD, "background-color", "--design-surface-2", `room card ${mode}`);
    await assertToken(page, `${ROOM_CARD} .room-icon`, "background-color", "--design-primary-100", `room icon ${mode}`);
    await assertToken(page, `${ROOM_CARD} .btn-brand-outline`, "color", "--design-link", `start button ${mode}`);
    await assertToken(page, NEW_ROOM, "background-color", "--design-primary", `new room ${mode}`);
    await assertToken(page, NEW_ROOM, "color", "--design-on-primary", `new room ${mode}`);
    await assertToken(page, ".wide-white", "background-color", "--design-surface-2", `tab strip ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ROOM_CARD, "bigbluebutton rooms");
  await assertReadable(page, [`${ROOM_CARD} .card-title`, { selector: `${ROOM_CARD} .text-muted`, optional: true }, ".nav-tabs .nav-link"], "bigbluebutton rooms");
});

test("design: admin tables use the border token as divider in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, `${base}/admin/users`);
  await shown(USERS_ROW)(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, `${USERS_ROW} td`, "border-bottom-color", "--design-border", `user row ${mode}`);
    await assertToken(page, "#admin-sidebar", "border-right-color", "--design-border", `sidebar divider ${mode}`);
    await assertToken(page, "#admin-sidebar .nav-link.active", "background-color", "--design-surface-active", `active entry ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [`${USERS_ROW} td`, "#admin-sidebar .nav-link"], "bigbluebutton admin users");
});

test("design: the favicon is the configured one", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  test.skip(!faviconUrl, "logo replacement is disabled for this role");
  await gotoOnion(page, `${base}/`);
  await shown(HERO)(page);
  await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
});

test("design: Greenlight pages carry the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
  test.skip(!title, "title replacement is disabled for this role");
  await gotoOnion(page, `${base}/`);
  await shown(HERO)(page);
  await expect(page).toHaveTitle(title);
  await signIn(page);
  await expect(page).toHaveTitle(title);
  await gotoOnion(page, `${base}/admin/users`);
  await shown(USERS_ROW)(page);
  await expect(page).toHaveTitle(title);
});

/**
 * Args:
 *   page: Playwright page on `url`; signs in again and reopens `url` when the session is gone.
 *   url: absolute URL of the view.
 */
async function signedInAt(page, url) {
  const signedIn = await page.evaluate(async () => {
    const response = await fetch("/api/v1/sessions.json", { headers: { Accept: "application/json" } });
    return Boolean((await response.json()).data?.id);
  });
  if (!signedIn) {
    await signIn(page);
    await gotoOnion(page, url);
  }
}

function view(name, path, ready) {
  const url = `${base}${path}`;
  return {
    name,
    url,
    prepare: async (page) => {
      await signedInAt(page, url);
      await shown(ready)(page);
    },
  };
}

function visitor(name, path, ready) {
  const url = `${base}${path}`;
  return {
    name,
    url,
    prepare: async (page) => {
      await page.context().clearCookies();
      await gotoOnion(page, "about:blank");
      await gotoOnion(page, url);
      await shown(ready)(page);
    },
  };
}

async function settled(page, selector) {
  await shown(selector)(page);
  await expect
    .poll(
      () =>
        page
          .locator(selector)
          .first()
          .evaluate((el) => getComputedStyle(el).opacity === "1" && el.getAnimations({ subtree: true }).every((a) => a.playState !== "running")),
      { timeout: resolveTimeout(10_000) },
    )
    .toBe(true);
}

function tab(name, path, label, ready) {
  const url = `${base}${path}`;
  return {
    name,
    url,
    prepare: async (page) => {
      await signedInAt(page, url);
      const target = page.getByRole("tab", { name: label }).first();
      await expect(target).toBeVisible({ timeout: resolveTimeout(10_000) });
      await target.click({ timeout: resolveTimeout(10_000) });
      await settled(page, ready);
    },
  };
}

function opened(name, path, trigger, ready) {
  const url = `${base}${path}`;
  return {
    name,
    url,
    prepare: async (page) => {
      await signedInAt(page, url);
      await shown(trigger)(page);
      await page.locator(trigger).first().click({ timeout: resolveTimeout(10_000) });
      await settled(page, ready);
    },
  };
}

function userMenu() {
  const url = `${base}/rooms`;
  return {
    name: "user-menu",
    url,
    prepare: async (page) => {
      await signedInAt(page, url);
      const toggler = page.locator(".navbar-toggler");
      if (await toggler.isVisible()) {
        await toggler.click({ timeout: resolveTimeout(10_000) });
        await settled(page, "#navbar-menu.show");
      } else {
        await page.locator("#nav-user-dropdown").click({ timeout: resolveTimeout(10_000) });
        await settled(page, ".dropdown-menu.show");
      }
    },
  };
}

function galleryViews(seed) {
  return [
    view("rooms", "/rooms", ROOM_CARD),
    opened("rooms-new-modal", "/rooms", NEW_ROOM, ".modal.show .modal-content"),
    tab("rooms-recordings", "/rooms", /recordings/i, ".tab-pane.active"),
    userMenu(),
    view("room", `/rooms/${seed.room}`, ".room-header-wrapper h1"),
    tab("room-access", `/rooms/${seed.room}`, /access/i, ".tab-pane.active"),
    tab("room-settings", `/rooms/${seed.room}`, /settings/i, "#room-settings"),
    view("profile", "/profile", "#profile-sidebar"),
    tab("profile-password", "/profile", /password/i, ".tab-pane.active form"),
    view("admin-users", "/admin/users", USERS_ROW),
    opened("admin-users-new-modal", "/admin/users", `${ADMIN} .btn-brand`, ".modal.show form"),
    view("admin-user-edit", `/admin/users/edit/${seed.user}`, `${ADMIN} form`),
    view("admin-server-rooms", "/admin/server_rooms", "#server-rooms-table"),
    view("admin-server-recordings", "/admin/server_recordings", "#server-recordings"),
    view("admin-appearance", "/admin/site_settings", `${ADMIN} .btn-brand-light`),
    opened("admin-brand-popover", "/admin/site_settings", `${ADMIN} .tab-pane.active .btn-brand`, ".popover.show"),
    tab("admin-administration", "/admin/site_settings", /administration/i, `${ADMIN} .tab-pane.active form`),
    tab("admin-settings", "/admin/site_settings", /^settings$/i, `${ADMIN} .tab-pane.active .form-switch`),
    tab("admin-registration", "/admin/site_settings", /registration/i, `${ADMIN} .tab-pane.active .setting-select`),
    view("admin-room-config", "/admin/room_configuration", `${ADMIN} .setting-select`),
    opened("admin-room-config-menu", "/admin/room_configuration", `${ADMIN} .setting-select button`, ".setting-select .dropdown-menu.show"),
    view("admin-roles", "/admin/roles", `${ADMIN} table tbody tr`),
    visitor("home", "/", HERO),
    visitor("sign-in", "/signin", EMAIL),
    visitor("sign-up", "/signup", ".card input[type=email]"),
    visitor("room-join", `/rooms/${seed.room}/join`, ".card input"),
    {
      name: "meeting",
      url: `${base}/rooms/${seed.room}`,
      prepare: async (page) => {
        await signedInAt(page, `${base}/rooms/${seed.room}`);
        await joinMeeting(page, seed.room);
      },
    },
  ];
}

test("design: gallery of visitor pages, rooms, profile and administration", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  skipUnreachable();
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(900_000));
  await signIn(page);
  await captureDesignGallery(page, galleryViews(await seedShowcase(page)));
});
