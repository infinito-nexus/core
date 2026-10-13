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
const { apiFetchOnion, decodeDotenvQuotedValue, gotoOnion, requireDotenvValue } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const HOME = '[data-testid="HomeScreen"]';
const SETTINGS = '[aria-label="Privacy and security"]';
const APPEARANCE = '[data-testid="preferencesThreadsScreen"]';
const NAVIGATION_ROOT_BACKGROUNDS = ["rgb(242, 242, 242)", "rgb(1, 1, 1)"];
const THEME_TOKENS = [
  "surface-1",
  "surface-2",
  "surface-3",
  "surface-hover",
  "surface-active",
  "text",
  "text-muted",
  "link",
  "border",
  "border-strong",
  "primary",
  "on-primary",
  "primary-hover",
  "primary-active",
  "frame",
  "warning",
  ...["", "-subtle", "-border", "-hover", "-active"].flatMap((suffix) => [`danger${suffix}`, `success${suffix}`]),
  ...["300", "500", "600", "800", "900", "950"].map((step) => `neutral-${step}`),
  ...["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"].map((step) => `primary-${step}`),
].map((name) => `--design-${name}`);
const PERSONAL_DETAILS = "app.bsky.actor.defs#personalDetailsPref";
const SHOWCASE_BIRTH_DATE = "1990-01-01T00:00:00.000Z";
const APP_PASSWORD_NAME = "design-showcase";

function storagePayload(account) {
  const entry = { ...account, active: true };
  return {
    colorMode: "system",
    darkTheme: "dim",
    session: { accounts: [entry], currentAccount: entry },
    reminders: {},
    languagePrefs: {
      primaryLanguage: "en",
      contentLanguages: ["en"],
      postLanguage: "en",
      postLanguageHistory: ["en", "ja", "pt", "de"],
      appLanguage: "en",
    },
    requireAltTextEnabled: false,
    largeAltBadgeEnabled: false,
    externalEmbeds: {},
    mutedThreads: [],
    invites: { copiedInvites: [] },
    onboarding: { step: "Home" },
    hiddenPosts: [],
    pdsAddressHistory: [],
    disableHaptics: false,
    disableAutoplay: false,
    kawaii: false,
    hasCheckedForStarterPack: false,
    subtitlesEnabled: true,
    trendingDisabled: false,
    trendingVideoDisabled: false,
  };
}

async function xrpc(page, shared, accessJwt, method, name, data) {
  const response = await apiFetchOnion(page.request, `${shared.env.pdsBaseUrl}/xrpc/${name}`, {
    method,
    headers: { Authorization: `Bearer ${accessJwt}`, "Content-Type": "application/json" },
    ...(data === undefined ? {} : { data }),
  });
  expect(response.status(), `PDS ${name}`).toBe(200);
  return response.text();
}

async function seedBirthDate(page, shared, accessJwt) {
  const { preferences } = JSON.parse(await xrpc(page, shared, accessJwt, "GET", "app.bsky.actor.getPreferences"));
  if (preferences.some((entry) => entry.$type === PERSONAL_DETAILS && entry.birthDate)) return;
  const others = preferences.filter((entry) => entry.$type !== PERSONAL_DETAILS);
  await xrpc(page, shared, accessJwt, "POST", "app.bsky.actor.putPreferences", {
    preferences: [...others, { $type: PERSONAL_DETAILS, birthDate: SHOWCASE_BIRTH_DATE }],
  });
}

async function signIn(page, shared) {
  const { baseUrl, oidcIssuerUrl, adminUsername, adminPassword, adminHandle, pdsBaseUrl } = shared.env;
  let accessJwt;
  if (isServiceEnabled("sso")) {
    await gotoOnion(page, `${baseUrl}/`);
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000) })
      .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
    await shared.performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect
      .poll(
        () =>
          page
            .evaluate(() => JSON.parse(localStorage.getItem("BSKY_STORAGE") || "{}").session?.currentAccount?.accessJwt || "")
            .catch(() => ""),
        { timeout: resolveTimeout(90_000) },
      )
      .not.toBe("");
    accessJwt = await page.evaluate(() => JSON.parse(localStorage.getItem("BSKY_STORAGE")).session.currentAccount.accessJwt);
  } else {
    const response = await apiFetchOnion(page.request, `${pdsBaseUrl}/xrpc/com.atproto.server.createSession`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      data: { identifier: adminHandle, password: adminPassword },
    });
    expect(response.status(), "PDS createSession accepts the administrator").toBe(200);
    const session = await response.json();
    accessJwt = session.accessJwt;
    const payload = storagePayload({
      service: pdsBaseUrl,
      did: session.did,
      handle: session.handle,
      email: session.email,
      emailConfirmed: true,
      accessJwt: session.accessJwt,
      refreshJwt: session.refreshJwt,
    });
    await page.addInitScript((raw) => {
      if (!localStorage.getItem("BSKY_STORAGE")) localStorage.setItem("BSKY_STORAGE", raw);
    }, JSON.stringify(payload));
  }
  await seedBirthDate(page, shared, accessJwt);
  await gotoOnion(page, `${baseUrl}/`);
  await page.locator(HOME).first().waitFor({ timeout: resolveTimeout(60_000) });
  return accessJwt;
}

async function seedAppPassword(page, shared, accessJwt) {
  const { passwords } = JSON.parse(await xrpc(page, shared, accessJwt, "GET", "com.atproto.server.listAppPasswords"));
  if (passwords.some((entry) => entry.name === APP_PASSWORD_NAME)) return;
  await xrpc(page, shared, accessJwt, "POST", "com.atproto.server.createAppPassword", { name: APP_PASSWORD_NAME });
}

async function openSettings(page, shared) {
  await gotoOnion(page, `${shared.env.baseUrl}/settings`);
  await page.locator(SETTINGS).first().waitFor({ timeout: resolveTimeout(30_000) });
}

async function tokenValues(page) {
  return page.evaluate((names) => {
    const probe = document.createElement("span");
    document.body.appendChild(probe);
    const values = {};
    for (const name of names) {
      probe.style.setProperty("color", `var(${name})`);
      values[name] = getComputedStyle(probe).color;
    }
    probe.remove();
    return values;
  }, THEME_TOKENS);
}

async function contrast(locator) {
  return locator.evaluate((element) => {
    const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    const rgba = (value) => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = value;
      ctx.fillRect(0, 0, 1, 1);
      return [...ctx.getImageData(0, 0, 1, 1).data];
    };
    const luminance = ([r, g, b]) => {
      const lin = (c) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
      return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    };
    let background = [255, 255, 255];
    for (let node = element; node; node = node.parentElement) {
      const color = rgba(getComputedStyle(node).backgroundColor);
      if (color[3] > 128) {
        background = color;
        break;
      }
    }
    const [fg, bg] = [luminance(rgba(getComputedStyle(element).color)), luminance(background)];
    return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
  });
}

async function inlineColors(page) {
  return page.evaluate(() => {
    const seen = { background: new Set(), color: new Set(), border: new Set() };
    for (const element of document.querySelectorAll("#root [style]")) {
      const style = getComputedStyle(element);
      if (element.style.backgroundColor) seen.background.add(style.backgroundColor);
      if (element.style.color) seen.color.add(style.color);
      for (const side of ["Top", "Right", "Bottom", "Left"]) {
        if (element.style[`border${side}Color`] && parseFloat(style[`border${side}Width`]) > 0) {
          seen.border.add(style[`border${side}Color`]);
        }
      }
    }
    return { background: [...seen.background], color: [...seen.color], border: [...seen.border] };
  });
}

exports.register = function (shared) {
  test("design: the desktop sign-in layout paints its legacy panels with tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(isServiceEnabled("sso"), "the oauth2 gate hands every visitor a session, so the sign-in form never renders");
    await page.setViewportSize({ width: 1440, height: 900 });
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${shared.env.baseUrl}/settings`);
      await page.locator('[data-testid="signInButton"]').click();
      const form = page.locator('[data-testid="loginForm"]');
      await form.waitFor({ timeout: resolveTimeout(30_000) });
      const label = `bluesky sign-in ${mode}`;
      const tokens = await tokenValues(page);
      const census = await inlineColors(page);
      const allowed = new Set([...Object.values(tokens), ...NAVIGATION_ROOT_BACKGROUNDS]);
      const foreign = [...census.background, ...census.color, ...census.border].filter(
        (value) => !/^rgba\(.*, 0(\.\d+)?\)$/.test(value) && !allowed.has(value),
      );
      expect(foreign, `${label}: opaque inline colors that are no design token`).toEqual([]);
      const panel = await form.evaluate((element) => {
        for (let node = element; node; node = node.parentElement) {
          if (node.style && node.style.backgroundColor) return getComputedStyle(node).backgroundColor;
        }
        return null;
      });
      expect(panel, `${label}: the form panel is --design-surface-1`).toBe(tokens["--design-surface-1"]);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    await assertDesignTokens(page, "bluesky");
  });

  test("design: every opaque ALF color on the settings screen is a design token", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, shared);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await openSettings(page, shared);
      const label = `bluesky ${mode}`;
      const tokens = await tokenValues(page);
      const census = await inlineColors(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", label);
      expect(census.background, `${label}: the ALF page surface is --design-surface-1`).toContain(tokens["--design-surface-1"]);
      expect(census.background, `${label}: the ALF panel surface is --design-surface-3`).toContain(tokens["--design-surface-3"]);
      expect(census.border, `${label}: the ALF dividers are --design-border`).toContain(tokens["--design-border"]);
      expect(census.color, `${label}: the ALF body text is --design-text`).toContain(tokens["--design-text"]);
      expect(census.color, `${label}: the ALF secondary text is --design-text-muted`).toContain(tokens["--design-text-muted"]);
      const allowed = new Set([...Object.values(tokens), ...NAVIGATION_ROOT_BACKGROUNDS]);
      const foreign = [...census.background, ...census.color, ...census.border].filter(
        (value) => !/^rgba\(.*, 0(\.\d+)?\)$/.test(value) && !allowed.has(value),
      );
      expect(foreign, `${label}: opaque inline colors that are no design token`).toEqual([]);
      await assertToken(page, 'button[aria-label="Compose new post"]', "background-color", "--design-primary", label);
      await assertToken(page, 'button[aria-label="Compose new post"] [dir="auto"]', "color", "--design-on-primary", label);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, SETTINGS, "bluesky settings");
    await assertReadable(
      page,
      [`${SETTINGS} [dir="auto"]`, '[aria-label="Account"] [dir="auto"]', 'nav a[href="/settings"] [dir="auto"]'],
      "bluesky",
    );
  });

  test("design: the native color mode drives the tokens over the browser preference", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    await page.emulateMedia({ colorScheme: "light" });
    await gotoOnion(page, `${shared.env.baseUrl}/settings/appearance`);
    await page.locator(APPEARANCE).first().waitFor({ timeout: resolveTimeout(30_000) });
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");
    const colorMode = page.getByRole("radiogroup", { name: "Color mode" });
    await colorMode.getByRole("radio", { name: "Dark" }).click();
    await expect(page.locator("html")).toHaveClass(/theme--(dim|dark)/);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    const darkSurface = await tokenValue(page, "--design-surface-1", "background-color");
    expect(darkSurface, "the app's Dark choice switches the tokens in a light browser").not.toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "bluesky app dark mode");
    await expect.poll(async () => (await inlineColors(page)).background, { timeout: resolveTimeout(10_000) }).toContain(darkSurface);
    await page.emulateMedia({ colorScheme: "dark" });
    await colorMode.getByRole("radio", { name: "Light" }).click();
    await expect(page.locator("html")).toHaveClass(/theme--light/);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
    expect(await tokenValue(page, "--design-surface-1", "background-color"), "the app's Light choice wins in a dark browser").toBe(lightSurface);
    await expect.poll(async () => (await inlineColors(page)).background, { timeout: resolveTimeout(10_000) }).toContain(lightSurface);
    await colorMode.getByRole("radio", { name: "System" }).click();
    await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /./);
  });

  test("design: logo, favicon and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const symbolUrl = decodeDotenvQuotedValue(process.env.DESIGN_SYMBOL_URL || "");
    const faviconUrl = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_FAVICON_URL, "DESIGN_FAVICON_URL"));
    const title = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_TITLE, "DESIGN_TITLE"));
    await signIn(page, shared);
    await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    test.skip(!symbolUrl, "the logo replacement is disabled for this role");
    await expect(page.locator('link[rel~="icon"]').first()).toHaveAttribute("href", faviconUrl);
    const logo = page.locator('svg[viewBox="0 0 64 57"]').first();
    await logo.waitFor({ timeout: resolveTimeout(30_000) });
    expect(
      await logo.evaluate((element) => getComputedStyle(element).backgroundImage),
      "the Bluesky butterfly is replaced by the generated symbol",
    ).toContain(symbolUrl);
    expect(
      await logo.evaluate((element) => getComputedStyle(element.querySelector("path")).fill),
      "the upstream butterfly path is hidden",
    ).toBe("rgba(0, 0, 0, 0)");
    const served = await apiFetchOnion(page.request, symbolUrl, { method: "GET" });
    expect(served.status(), "the generated symbol is served").toBe(200);
  });

  test("design: the default avatar takes --design-primary and --design-on-primary", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, shared);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${shared.env.baseUrl}/`);
      const avatar = page.locator('svg[data-testid="userAvatarFallback"]').first();
      await avatar.waitFor({ timeout: resolveTimeout(30_000) });
      const fills = await avatar.evaluate((element) =>
        [...element.querySelectorAll("[fill]")].map((part) => [part.getAttribute("fill").toLowerCase(), getComputedStyle(part).fill]),
      );
      const disc = fills.filter(([attribute]) => attribute === "#0070ff").map(([, computed]) => computed);
      const glyph = fills.filter(([attribute]) => ["#fff", "#ffffff", "white"].includes(attribute)).map(([, computed]) => computed);
      expect(glyph.length, `bluesky ${mode}: the default avatar draws its glyph`).toBeGreaterThan(0);
      expect(disc.length, `bluesky ${mode}: the default avatar draws its disc`).toBeGreaterThan(0);
      expect(new Set(disc), `bluesky ${mode}: the avatar disc is --design-primary`).toEqual(
        new Set([await tokenValue(page, "--design-primary", "fill")]),
      );
      expect(new Set(glyph), `bluesky ${mode}: the avatar glyph is --design-on-primary`).toEqual(
        new Set([await tokenValue(page, "--design-on-primary", "fill")]),
      );
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the destructive confirmation takes --design-danger and --design-on-danger", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    const accessJwt = await signIn(page, shared);
    await seedAppPassword(page, shared, accessJwt);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${shared.env.baseUrl}/settings/app-passwords`);
      await page.getByText(APP_PASSWORD_NAME).first().waitFor({ timeout: resolveTimeout(30_000) });
      await page.locator('[aria-label="Delete app password"]').first().click();
      const confirm = page.locator('[role="dialog"] [data-testid="confirmBtn"]').last();
      await confirm.waitFor({ timeout: resolveTimeout(10_000) });
      const label = `bluesky ${mode}: the destructive confirmation`;
      await assertToken(page, '[role="dialog"] [data-testid="confirmBtn"]', "background-color", "--design-danger", label);
      await assertToken(page, '[role="dialog"] [data-testid="confirmBtn"] [dir="auto"]', "color", "--design-on-danger", label);
      expect(await contrast(confirm.locator('[dir="auto"]').first()), `${label} text contrast`).toBeGreaterThanOrEqual(4.5);
      await page.keyboard.press("Escape");
      await confirm.waitFor({ state: "detached", timeout: resolveTimeout(10_000) });
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: primary text uses and the primary hover keep AA contrast", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, shared);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `bluesky ${mode}`;
      await gotoOnion(page, `${shared.env.baseUrl}/settings/account`);
      const verify = page.getByText("Verify your email", { exact: true }).first();
      await verify.waitFor({ timeout: resolveTimeout(30_000) });
      expect(await verify.evaluate((element) => getComputedStyle(element).color), `${label}: the verify row text is --design-link`).toBe(
        await tokenValue(page, "--design-link", "color"),
      );
      expect(await contrast(verify), `${label}: the verify row text contrast`).toBeGreaterThanOrEqual(4.5);
      await openSettings(page, shared);
      const compose = page.locator('button[aria-label="Compose new post"]').first();
      const text = compose.locator('[dir="auto"]').first();
      const rest = await contrast(text);
      await compose.hover();
      await assertToken(page, 'button[aria-label="Compose new post"]', "background-color", "--design-primary-hover", `${label} hovered primary action`);
      expect(await contrast(text), `${label}: the hovered primary action keeps at least its resting contrast`).toBeGreaterThanOrEqual(rest);
      await page.mouse.move(0, 0);
      await compose.click();
      await page.locator('[data-testid="composePostView"]').waitFor({ timeout: resolveTimeout(10_000) });
      for (const name of ["English", "Anyone can interact"]) {
        const control = page.locator('[data-testid="composePostView"]').getByText(name, { exact: true }).first();
        await control.waitFor({ timeout: resolveTimeout(10_000) });
        expect(await contrast(control), `${label}: composer '${name}' text contrast`).toBeGreaterThanOrEqual(4.5);
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the visitor splash takes the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(isServiceEnabled("sso"), "the oauth2 gate hands every visitor a session, so the splash never renders");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${shared.env.baseUrl}/settings`);
      const create = page.locator('[data-testid="createAccountButton"]');
      await create.waitFor({ timeout: resolveTimeout(30_000) });
      const label = `bluesky splash ${mode}`;
      await assertToken(page, "body", "background-color", "--design-surface-1", label);
      await assertToken(page, '[data-testid="createAccountButton"]', "background-color", "--design-primary", label);
      expect(
        await create.evaluate((element) => getComputedStyle(element.querySelector('[dir="auto"]') || element).color),
        `${label}: text on the primary action is --design-on-primary`,
      ).toBe(await tokenValue(page, "--design-on-primary", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: gallery of visitor, account and settings views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    const base = shared.env.baseUrl;
    const ready = (selector) => async (view) => {
      await view.locator(selector).first().waitFor({ timeout: resolveTimeout(10_000) });
    };
    const settled = async (view, selector) => {
      const panel = view.locator(selector).first();
      await panel.waitFor({ timeout: resolveTimeout(10_000) });
      await expect
        .poll(() => panel.evaluate((element) => element.getAnimations({ subtree: true }).filter((a) => a.playState === "running").length), {
          timeout: resolveTimeout(10_000),
        })
        .toBe(0);
    };
    const back = ready('button[aria-label="Go back"]');
    const failures = [];
    if (!isServiceEnabled("sso")) {
      await captureDesignGallery(page, [
        { name: "splash", url: `${base}/settings`, prepare: ready('[data-testid="createAccountButton"]') },
        {
          name: "login",
          url: `${base}/settings`,
          prepare: async (view) => {
            await view.locator('[data-testid="signInButton"]').click();
            await settled(view, '[data-testid="loginForm"]');
          },
        },
        {
          name: "signup",
          url: `${base}/settings`,
          prepare: async (view) => {
            await view.locator('[data-testid="createAccountButton"]').click();
            const heading = view.getByText("Your account", { exact: true }).first();
            await heading.waitFor({ timeout: resolveTimeout(10_000) });
            await expect
              .poll(
                () =>
                  heading.evaluate((element) => {
                    let opacity = 1;
                    for (let node = element; node; node = node.parentElement) opacity *= parseFloat(getComputedStyle(node).opacity);
                    return opacity;
                  }),
                { timeout: resolveTimeout(10_000) },
              )
              .toBe(1);
          },
        },
      ]).catch((error) => failures.push(error.message));
    }
    const accessJwt = await signIn(page, shared);
    await seedAppPassword(page, shared, accessJwt);
    await captureDesignGallery(page, [
      { name: "home", url: `${base}/`, prepare: ready(HOME) },
      {
        name: "composer",
        url: `${base}/`,
        afterOnly: true,
        prepare: async (view) => {
          await ready(HOME)(view);
          await view.getByRole("button", { name: /^(Compose new post|New post)$/ }).first().click();
          await settled(view, '[data-testid="composePostView"]');
        },
      },
      { name: "explore", url: `${base}/search`, prepare: ready('[data-testid="searchScreen"]') },
      { name: "notifications", url: `${base}/notifications`, prepare: ready('[data-testid="notificationsScreen"]') },
      { name: "feeds", url: `${base}/feeds`, prepare: ready('[data-testid="FeedsScreen"]') },
      { name: "lists", url: `${base}/lists`, prepare: ready('[data-testid="listsScreen"]') },
      { name: "settings", url: `${base}/settings`, prepare: ready(SETTINGS) },
      { name: "settings-account", url: `${base}/settings/account`, prepare: back },
      { name: "settings-privacy", url: `${base}/settings/privacy-and-security`, prepare: back },
      { name: "settings-notifications", url: `${base}/settings/notifications`, prepare: back },
      { name: "settings-content-media", url: `${base}/settings/content-and-media`, prepare: back },
      { name: "settings-appearance", url: `${base}/settings/appearance`, prepare: ready(APPEARANCE) },
      { name: "settings-accessibility", url: `${base}/settings/accessibility`, prepare: back },
      { name: "settings-language", url: `${base}/settings/language`, prepare: back },
      { name: "settings-app-passwords", url: `${base}/settings/app-passwords`, prepare: ready(`text=${APP_PASSWORD_NAME}`) },
      {
        name: "settings-app-passwords-delete",
        url: `${base}/settings/app-passwords`,
        prepare: async (view) => {
          await ready(`text=${APP_PASSWORD_NAME}`)(view);
          await view.locator('[aria-label="Delete app password"]').first().click();
          await settled(view, '[role="dialog"] [data-testid="confirmBtn"]');
          await expect
            .poll(
              () =>
                view
                  .locator('[role="dialog"]')
                  .last()
                  .evaluate((element) => {
                    let opacity = 1;
                    for (let node = element; node; node = node.parentElement) opacity *= parseFloat(getComputedStyle(node).opacity);
                    return opacity;
                  }),
              { timeout: resolveTimeout(10_000) },
            )
            .toBe(1);
        },
      },
      { name: "settings-threads", url: `${base}/settings/threads`, prepare: back },
      { name: "settings-following-feed", url: `${base}/settings/following-feed`, prepare: back },
      { name: "settings-external-embeds", url: `${base}/settings/external-embeds`, prepare: back },
      { name: "moderation", url: `${base}/moderation`, prepare: ready('[data-testid="moderationScreen"]') },
      { name: "moderation-muted", url: `${base}/moderation/muted-accounts`, prepare: ready('[data-testid="mutedAccountsScreen"]') },
      { name: "moderation-modlists", url: `${base}/moderation/modlists`, prepare: ready('[data-testid="moderationModlistsScreen"]') },
      { name: "settings-about", url: `${base}/settings/about`, prepare: back },
    ]).catch((error) => failures.push(error.message));
    expect(failures, "design gallery views failed").toEqual([]);
  });
};
