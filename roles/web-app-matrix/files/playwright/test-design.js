const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");
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
const { skipUnlessServiceEnabled } = require("./service-gating");

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const SHOWCASE_ALIAS = "design-showcase";
const SPACE_ALIAS = "design-space";
const SEED_DEVICE = "DESIGNSEED";
const SEED_MESSAGES = [
  "Welcome to the corporate design showcase.",
  "This room shows text, links and code: https://matrix.org",
  "Light mode and dark mode follow the browser.",
  "Hover, focus and selected states use the palette.",
  "The composer below takes the next message.",
];
const MODES = ["light", "dark"];
const DIALOG = ".mx_Dialog";
const MENU = '[role="menu"]';
const RIGHT_PANEL = ".mx_RightPanel";
const OVERLAY = `${DIALOG}, ${MENU}, .mx_ContextualMenu`;

function readyWait() {
  return { timeout: resolveTimeout(10_000) };
}

function bootWait() {
  return { timeout: resolveTimeout(30_000) };
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function apiSession(request, shared) {
  const { matrixBaseUrl, adminUsername, adminPassword } = shared.env;
  const api = `${matrixBaseUrl}/_matrix/client/v3`;
  const login = await apiFetchOnion(request, `${api}/login`, {
    method: "POST",
    data: {
      type: "m.login.password",
      identifier: { type: "m.id.user", user: adminUsername },
      password: adminPassword,
      device_id: SEED_DEVICE,
      initial_device_display_name: "Design showcase seeding",
    },
  });
  expect(login.status(), "seed login through the client-server API").toBe(200);
  const session = await login.json();
  return { api, headers: { Authorization: `Bearer ${session.access_token}` }, userId: session.user_id };
}

async function seedShowcase(request, shared) {
  const { matrixServerName } = shared.env;
  const { api, headers } = await apiSession(request, shared);

  async function ensureRoom(alias, body) {
    const lookup = await apiGetOnion(request, `${api}/directory/room/${encodeURIComponent(`#${alias}:${matrixServerName}`)}`, { headers });
    if (lookup.ok()) return (await lookup.json()).room_id;
    const created = await apiFetchOnion(request, `${api}/createRoom`, {
      method: "POST",
      headers,
      data: { room_alias_name: alias, preset: "private_chat", ...body },
    });
    expect(created.status(), `create the ${alias} room`).toBe(200);
    return (await created.json()).room_id;
  }

  const roomId = await ensureRoom(SHOWCASE_ALIAS, { name: "Design showcase", topic: "Corporate design review" });
  const spaceId = await ensureRoom(SPACE_ALIAS, {
    name: "Design space",
    topic: "Corporate design review space",
    creation_content: { type: "m.space" },
  });
  const child = await apiFetchOnion(
    request,
    `${api}/rooms/${encodeURIComponent(spaceId)}/state/m.space.child/${encodeURIComponent(roomId)}`,
    { method: "PUT", headers, data: { via: [matrixServerName] } },
  );
  expect(child.status(), "link the showcase room into the space").toBe(200);

  const history = await apiGetOnion(request, `${api}/rooms/${encodeURIComponent(roomId)}/messages?dir=b&limit=50`, { headers });
  expect(history.status(), "read the showcase history").toBe(200);
  const sent = new Set(
    ((await history.json()).chunk || []).filter((event) => event.type === "m.room.message").map((event) => event.content?.body),
  );
  for (const [index, body] of SEED_MESSAGES.entries()) {
    if (sent.has(body)) continue;
    const message = await apiFetchOnion(
      request,
      `${api}/rooms/${encodeURIComponent(roomId)}/send/m.room.message/design-seed-${index}-${Date.now()}`,
      { method: "PUT", headers, data: { msgtype: "m.text", body } },
    );
    expect(message.status(), `send showcase message ${index}`).toBe(200);
  }
  return { roomAlias: `#${SHOWCASE_ALIAS}:${matrixServerName}`, spaceAlias: `#${SPACE_ALIAS}:${matrixServerName}` };
}

async function dismissToasts(page) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const button = page
      .locator(".mx_ToastContainer")
      .getByRole("button", { name: /^(ok|later|dismiss|not now|close)$/i })
      .or(page.getByRole("dialog").filter({ hasText: /^introducing/i }).getByRole("button", { name: /^ok$/i }))
      .first();
    if (!(await button.isVisible().catch(() => false))) return;
    await button.click({ timeout: resolveTimeout(4_000) });
    await page.waitForTimeout(resolveTimeout(300));
  }
}

async function settledPanel(page, selector) {
  const panel = page.locator(selector).first();
  await expect(panel).toBeVisible(readyWait());
  await expect
    .poll(
      () =>
        panel.evaluate(
          (element) =>
            getComputedStyle(element).opacity === "1" &&
            element
              .getAnimations({ subtree: true })
              .every((animation) => animation.playState !== "running" || animation.effect?.getComputedTiming().iterations === Infinity),
        ),
      readyWait(),
    )
    .toBe(true);
}

async function closeOverlays(page) {
  await dismissToasts(page);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const open = await page.locator(OVERLAY).count();
    if (open === 0) return;
    const close = page.locator(DIALOG).getByRole("button", { name: /^close dialog$/i }).first();
    if (await close.isVisible().catch(() => false)) {
      await close.click({ timeout: resolveTimeout(4_000) });
    } else {
      await page.keyboard.press("Escape");
    }
    await page.waitForTimeout(resolveTimeout(300));
  }
  await expect(page.locator(OVERLAY)).toHaveCount(0, readyWait());
}

async function closeRightPanel(page) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (!(await page.locator(RIGHT_PANEL).isVisible().catch(() => false))) return;
    const panel = page.locator(RIGHT_PANEL);
    await panel
      .locator('[data-testid="base-card-close-button"], .mx_BaseCard_close')
      .or(panel.getByRole("button", { name: /^(close|back)$/i }))
      .first()
      .click({ timeout: resolveTimeout(4_000) });
    await page.waitForTimeout(resolveTimeout(300));
  }
  await expect(page.locator(RIGHT_PANEL)).toBeHidden(readyWait());
}

async function signedIn(page, shared) {
  await shared.signInViaElement(page, shared.env.adminUsername, shared.env.adminPassword, "administrator design");
  await dismissToasts(page);
}

function visitorViews(shared) {
  const base = shared.env.elementBaseUrl;
  const auth = (selector) => async (view) => {
    await dismissToasts(view);
    await expect(view.locator(selector).first()).toBeVisible(readyWait());
  };
  return [
    { name: "welcome", url: `${base}/#/welcome`, prepare: auth('.mx_DefaultWelcome a[href="#/login"]') },
    { name: "login", url: `${base}/#/login`, prepare: auth(".mx_AuthBody") },
    { name: "register", url: `${base}/#/register`, prepare: auth(".mx_AuthBody") },
    { name: "forgot-password", url: `${base}/#/forgot_password`, prepare: auth(".mx_AuthBody") },
    { name: "synapse-landing", url: `${shared.env.matrixBaseUrl}/_matrix/static/`, prepare: auth("h1") },
  ];
}

function signedInViews(shared, seeded) {
  const base = shared.env.elementBaseUrl;
  const room = `${base}/#/room/${encodeURIComponent(seeded.roomAlias)}`;
  const home = `${base}/#/home`;
  const ready = (selector) => async (view) => {
    await closeOverlays(view);
    await settledPanel(view, selector);
  };
  const inRoom = (then) => async (view) => {
    await closeOverlays(view);
    await expect(view.locator(".mx_RoomHeader")).toBeVisible(readyWait());
    await closeRightPanel(view);
    await expect(view.locator(".mx_EventTile_body").first()).toBeVisible(readyWait());
    if (then) await then(view);
  };
  const header = (view, name) => view.locator(".mx_RoomHeader").getByRole("button", { name }).first();
  const menu = (opener) => async (view) => {
    await closeOverlays(view);
    await opener(view).click();
    await settledPanel(view, MENU);
  };
  const dialog = (hash, selector) => async (view) => {
    await closeOverlays(view);
    await gotoOnion(view, `${base}/#/${hash}`);
    await settledPanel(view, selector);
  };
  const pickTab = async (view, scope, name) => {
    const tab = view.locator(scope).getByRole("tab", { name }).first();
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true", readyWait());
    await expect(view.locator(`${scope} .mx_SettingsTab`).first()).toBeVisible(readyWait());
  };
  const settingsTab = (name) => async (view) => {
    await dialog("settings", ".mx_UserSettingsDialog")(view);
    await pickTab(view, ".mx_UserSettingsDialog", name);
  };
  const roomInfo = async (view) => {
    await header(view, /^room info$/i).click();
    await settledPanel(view, RIGHT_PANEL);
  };
  const roomSettingsTab = (name) =>
    inRoom(async (view) => {
      await roomInfo(view);
      await view.locator(RIGHT_PANEL).getByRole("menuitem", { name: /^settings$/i }).first().click();
      await settledPanel(view, ".mx_RoomSettingsDialog");
      await pickTab(view, ".mx_RoomSettingsDialog", name);
    });
  return [
    { name: "home", url: home, prepare: ready(".mx_HomePage") },
    { name: "room-timeline", url: room, prepare: inRoom() },
    {
      name: "room-composer-focus",
      url: room,
      prepare: inRoom(async (view) => {
        await view.locator(".mx_BasicMessageComposer_input").click();
        await expect(view.locator(".mx_BasicMessageComposer_input")).toBeFocused(readyWait());
      }),
    },
    {
      name: "message-actions",
      url: room,
      prepare: inRoom(async (view) => {
        await view.locator(".mx_EventTile_last .mx_EventTile_body, .mx_EventTile_body").last().hover();
        await settledPanel(view, ".mx_MessageActionBar");
      }),
    },
    { name: "room-info", url: room, prepare: inRoom(roomInfo) },
    {
      name: "room-members",
      url: room,
      prepare: inRoom(async (view) => {
        await roomInfo(view);
        await view.locator(RIGHT_PANEL).getByRole("menuitem", { name: /^people/i }).first().click();
        await settledPanel(view, ".mx_MemberListView, .mx_MemberList");
      }),
    },
    { name: "room-settings-general", url: room, prepare: roomSettingsTab(/^general$/i) },
    { name: "room-settings-security", url: room, prepare: roomSettingsTab(/security/i) },
    { name: "user-menu", url: home, prepare: menu((view) => view.getByRole("button", { name: /^user menu$/i }).first()) },
    {
      name: "quick-settings",
      url: home,
      prepare: async (view) => {
        await closeOverlays(view);
        await view.getByRole("button", { name: /^quick settings$/i }).first().click();
        await settledPanel(view, ".mx_QuickSettingsButton_ContextMenuWrapper .mx_ContextualMenu");
      },
    },
    { name: "settings-account", url: home, prepare: settingsTab(/^account$/i) },
    { name: "settings-sessions", url: home, prepare: settingsTab(/^sessions$/i) },
    { name: "settings-appearance", url: home, prepare: settingsTab(/^appearance$/i) },
    { name: "settings-notifications", url: home, prepare: settingsTab(/^notifications$/i) },
    { name: "settings-preferences", url: home, prepare: settingsTab(/^preferences$/i) },
    { name: "settings-security", url: home, prepare: settingsTab(/^security & privacy$/i) },
    { name: "settings-encryption", url: home, prepare: settingsTab(/^encryption$/i) },
    { name: "create-room", url: home, prepare: dialog("new", ".mx_CreateRoomDialog") },
    {
      name: "user-profile",
      url: `${base}/#/user/${encodeURIComponent(`@${shared.env.adminUsername}:${shared.env.matrixServerName}`)}`,
      prepare: ready(".mx_UserInfo_container"),
    },
    { name: "space-home", url: `${base}/#/room/${encodeURIComponent(seeded.spaceAlias)}`, prepare: ready(".mx_SpaceRoomView") },
  ];
}

exports.register = function (shared) {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${shared.env.elementBaseUrl}/#/login`);
    await expect(page.locator(".mx_AuthBody")).toBeVisible(bootWait());
    await assertDesignTokens(page, "matrix element");
  });

  test("design: Element serves the corporate brand and logo through its configuration", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = shared.env.elementBaseUrl;
    const config = await (await apiGetOnion(page.request, `${base}/config.json`)).json();
    expect(config.branding?.welcome_background_url, "no stock wallpaper behind the sign-in").toBe("");
    expect(config.default_theme ?? null, "no configured theme overrides the browser color scheme").toBeNull();
    if (title) expect(config.brand, "config.json brand").toBe(title);
    if (logoUrl) {
      expect(config.branding?.auth_header_logo_url, "config.json auth header logo").toBe(logoUrl);
      const served = await apiGetOnion(page.request, logoUrl);
      expect(served.status(), "the configured logo is served").toBe(200);
      expect(served.headers()["content-type"], "the configured logo is an SVG").toContain("svg");
    }

    await gotoOnion(page, `${base}/#/login`);
    const logo = page.locator(".mx_AuthHeaderLogo img");
    await expect(logo).toBeVisible(bootWait());
    if (logoUrl) await expect(logo).toHaveAttribute("src", logoUrl);
    if (title) await expect(page).toHaveTitle(new RegExp(`^${escapeRegExp(title)}`));
    const box = await logo.boundingBox();
    expect(Math.abs(box.width - box.height), "the sign-in logo box is square like the declared slot").toBeLessThanOrEqual(1);

    await gotoOnion(page, `${base}/#/welcome`);
    const welcomeLogo = page.locator(".mx_DefaultWelcome_logo img");
    await expect(welcomeLogo).toBeVisible(bootWait());
    if (logoUrl) await expect(welcomeLogo).toHaveAttribute("src", logoUrl);
    if (title) await expect(page.locator(".mx_DefaultWelcome h1")).toContainText(title);
  });

  test("design: the sign-in pages sit on the frame with readable footer, panel and primary action", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = shared.env.elementBaseUrl;
    await gotoOnion(page, `${base}/#/welcome`);
    const signIn = '.mx_DefaultWelcome a[href="#/login"]';
    await expect(page.locator(signIn)).toBeVisible(bootWait());
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("body")).toHaveClass(new RegExp(`\\bcpd-theme-${mode}\\b`), readyWait());
      await assertToken(page, signIn, "background-color", "--design-primary", `matrix ${mode} welcome primary action`);
      await assertToken(page, signIn, "color", "--design-on-primary", `matrix ${mode} welcome primary action text`);
    }

    await gotoOnion(page, `${base}/#/login`);
    await expect(page.locator(".mx_AuthBody")).toBeVisible(bootWait());
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("body")).toHaveClass(new RegExp(`\\bcpd-theme-${mode}\\b`), readyWait());
      await assertToken(page, "#matrixchat", "background-color", "--design-frame", `matrix ${mode} sign-in backdrop`);
      await assertToken(page, ".mx_AuthPage_modalContent", "background-color", "--design-surface-2", `matrix ${mode} sign-in panel`);
      await assertToken(page, ".mx_AuthBody", "background-color", "--design-surface-1", `matrix ${mode} sign-in form`);
      await assertToken(page, ".mx_AuthFooter a", "color", "--design-on-frame", `matrix ${mode} sign-in footer link`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".mx_AuthBody", "matrix sign-in form");
    await assertReadable(page, [".mx_AuthBody h1", ".mx_AuthFooter a"], "matrix sign-in");

    const onFrame = await tokenValue(page, "--design-on-frame", "outline-color");
    const footerLinks = await page.locator(".mx_AuthFooter a").count();
    const stops = [];
    for (let press = 0; press < 40 && stops.length < footerLinks; press += 1) {
      await page.keyboard.press("Tab");
      const stop = await page.evaluate(() => {
        const element = document.activeElement;
        if (!element || !element.closest(".mx_AuthFooter")) return null;
        const style = getComputedStyle(element);
        return { label: (element.textContent || "").trim(), color: style.outlineColor, style: style.outlineStyle };
      });
      if (stop) stops.push(stop);
    }
    expect(stops, "every footer link on the frame is a focus stop").toHaveLength(footerLinks);
    for (const stop of stops) {
      expect(stop.style, `focus indicator of '${stop.label}' on the frame`).not.toBe("none");
      expect(stop.color, `focus indicator of '${stop.label}' uses --design-on-frame`).toBe(onFrame);
    }
  });

  test("design: signed-in Element carries surfaces, text, dividers and the primary action", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const seeded = await seedShowcase(page.request, shared);
    await signedIn(page, shared);
    await gotoOnion(page, `${shared.env.elementBaseUrl}/#/room/${encodeURIComponent(seeded.roomAlias)}`);
    await expect(page.locator(".mx_EventTile_body").first()).toBeVisible(bootWait());
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("body")).toHaveClass(new RegExp(`\\bcpd-theme-${mode}\\b`), readyWait());
      await expect(page.locator("html")).not.toHaveAttribute("data-design-theme");
      await assertToken(page, ".mx_RoomHeader", "background-color", "--design-surface-1", `matrix ${mode} room header`);
      await assertToken(page, ".mx_LeftPanel", "background-color", "--design-surface-1", `matrix ${mode} room list`);
      await assertToken(page, ".mx_EventTile_body", "color", "--design-text", `matrix ${mode} message text`);
      await assertToken(page, ".mx_RoomHeader", "border-bottom-color", "--design-border", `matrix ${mode} room header divider`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".mx_RoomHeader", "matrix room header");
    await assertReadable(page, [".mx_EventTile_body", ".mx_RoomHeader_heading", { selector: ".mx_RoomListItemView", optional: true }], "matrix room");

    await closeOverlays(page);
    await gotoOnion(page, `${shared.env.elementBaseUrl}/#/home`);
    const tile = ".mx_HomePage_default_buttons .mx_AccessibleButton";
    await expect(page.locator(tile).first()).toBeVisible(readyWait());
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("body")).toHaveClass(new RegExp(`\\bcpd-theme-${mode}\\b`), readyWait());
      await assertToken(page, tile, "background-color", "--design-primary", `matrix ${mode} home tile`);
      await assertToken(page, tile, "color", "--design-on-primary", `matrix ${mode} home tile text`);
      await assertToken(page, ".mx_HomePage_default h2", "color", "--design-text-muted", `matrix ${mode} home subtitle`);
    }
    await page.emulateMedia({ colorScheme: null });

    await gotoOnion(page, `${shared.env.elementBaseUrl}/#/new`);
    await settledPanel(page, ".mx_CreateRoomDialog");
    const create = ".mx_CreateRoomDialog .mx_Dialog_primary";
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("body")).toHaveClass(new RegExp(`\\bcpd-theme-${mode}\\b`), readyWait());
      await assertToken(page, create, "background-color", "--design-primary", `matrix ${mode} primary action`);
      await assertToken(page, create, "color", "--design-on-primary", `matrix ${mode} primary action text`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the theme picked in Element switches the tokens against the browser preference", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const { api, headers, userId } = await apiSession(page.request, shared);
    const settingsUrl = `${api}/user/${encodeURIComponent(userId)}/account_data/im.vector.web.settings`;
    const before = await apiGetOnion(page.request, settingsUrl, { headers });
    const original = before.ok() ? await before.json() : {};
    await signedIn(page, shared);
    await page.emulateMedia({ colorScheme: "light" });
    await expect(page.locator("body")).toHaveClass(/\bcpd-theme-light\b/, readyWait());
    await expect(page.locator("html")).not.toHaveAttribute("data-design-theme");
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");
    await closeOverlays(page);
    await gotoOnion(page, `${shared.env.elementBaseUrl}/#/settings`);
    await settledPanel(page, ".mx_UserSettingsDialog");
    await page.locator(".mx_UserSettingsDialog").getByRole("tab", { name: /^appearance$/i }).click();
    const system = page.locator(".mx_UserSettingsDialog").getByRole("switch", { name: /match system theme/i }).first();
    await expect(system).toBeVisible(readyWait());
    try {
      if (await system.isChecked()) await system.click();
      await page.locator(".mx_UserSettingsDialog").getByRole("radio", { name: /^dark$/i }).first().check();
      await expect(page.locator("body")).toHaveClass(/\bcpd-theme-dark\b/, readyWait());
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark", readyWait());
      expect(await tokenValue(page, "--design-surface-1", "background-color"), "the picked dark theme darkens the tokens").not.toBe(lightSurface);
      await assertToken(page, ".mx_Dialog:has(.mx_UserSettingsDialog)", "background-color", "--design-surface-1", "matrix picked dark theme dialog");
    } finally {
      if (!(await system.isChecked())) await system.click();
      await page.emulateMedia({ colorScheme: null });
      const restored = await apiFetchOnion(page.request, settingsUrl, { method: "PUT", headers, data: original });
      expect(restored.status(), "restore the account-level Element settings").toBe(200);
    }
  });

  test("design: the Synapse landing page carries the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${shared.env.matrixBaseUrl}/_matrix/static/`);
    await expect(page.locator("h1")).toBeVisible(bootWait());
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `synapse ${mode} landing`);
      await assertToken(page, "h1", "color", "--design-text", `synapse ${mode} heading`);
      await assertToken(page, "p a", "color", "--design-link", `synapse ${mode} link`);
      await assertToken(page, "hr", "background-color", "--design-border", `synapse ${mode} divider`);
      await assertToken(page, ".logo svg g[fill]:not([fill='none'])", "fill", "--design-text", `synapse ${mode} logo`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "h1", "synapse landing");
    await assertReadable(page, ["h1", "p", "p a"], "synapse landing");
  });

  test("design: gallery of sign-in, Element and Synapse views", async ({ page, browser }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    const failures = [];
    const visitor = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      await captureDesignGallery(await visitor.newPage(), visitorViews(shared));
    } catch (error) {
      failures.push(error.message);
    } finally {
      await visitor.close();
    }
    const seeded = await seedShowcase(page.request, shared);
    await signedIn(page, shared);
    try {
      await captureDesignGallery(page, signedInViews(shared, seeded));
    } catch (error) {
      failures.push(error.message);
    }
    expect(failures, "design gallery").toEqual([]);
  });
};
