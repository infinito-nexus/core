const { test, expect } = require("./onion-test");

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
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { adminPassword, adminUsername, baseUrl, ssoLoginAndAssertUsername } = require("./_shared");

const SHOWCASE_FOLDER = "design-showcase";
const SHOWCASE_SPACE = "Design Showcase";
const SHOWCASE_GROUP = "design-showcase";

const base = baseUrl.replace(/\/$/, "");
const idmUsername = decodeDotenvQuotedValue(process.env.IDM_ADMIN_USERNAME);
const idmPassword = decodeDotenvQuotedValue(process.env.IDM_ADMIN_PASSWORD);
const themePath = decodeDotenvQuotedValue(process.env.DESIGN_THEME_PATH);
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);

test.use({ ignoreHTTPSErrors: true });

async function allowBrowser(page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem(
        "forceAllowOldBrowser",
        JSON.stringify({ expiry: Date.now() + 30 * 24 * 60 * 60 * 1000 }),
      );
    } catch {}
  });
}

async function startWithClosedSidebar(page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("oc_sideBarOpen", "false");
    } catch {}
  });
}

async function signIn(page) {
  if (isServiceEnabled("sso")) {
    await ssoLoginAndAssertUsername(page, adminUsername, adminPassword);
    return;
  }
  await allowBrowser(page);
  await gotoOnion(page, `${base}/`);
  await page.locator("#oc-login-username").fill(idmUsername, { timeout: resolveTimeout(90_000) });
  await page.locator("#oc-login-password").fill(idmPassword);
  await page.locator("#oc-login-password").press("Enter");
  await expect(page.locator("#oc-topbar")).toBeVisible({ timeout: resolveTimeout(90_000) });
}

async function accessToken(page) {
  return page.evaluate(() => {
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i);
        if (key.startsWith("oc_oAuth.user:")) return JSON.parse(store.getItem(key)).access_token;
      }
    }
    return "";
  });
}

async function seedShowcase(page) {
  const headers = { Authorization: `Bearer ${await accessToken(page)}` };
  const api = (url, options = {}) =>
    apiFetchOnion(page.request, `${base}${url}`, { headers, failOnStatusCode: false, ...options });
  const drives = await (await apiGetOnion(page.request, `${base}/graph/v1.0/me/drives`, { headers })).json();
  const personal = drives.value.find((drive) => drive.driveType === "personal");
  const dav = `/remote.php/dav/spaces/${encodeURIComponent(personal.id)}`;
  await api(`${dav}/${SHOWCASE_FOLDER}`, { method: "MKCOL" });
  await api(`${dav}/${SHOWCASE_FOLDER}/empty`, { method: "MKCOL" });
  await api(`${dav}/${SHOWCASE_FOLDER}/notes.md`, { method: "PUT", data: "# Corporate design\n\n- light\n- dark\n" });
  await api(`${dav}/${SHOWCASE_FOLDER}/report.txt`, { method: "PUT", data: "Corporate design showcase\n" });
  if (!drives.value.some((drive) => drive.driveType === "project" && drive.name === SHOWCASE_SPACE)) {
    await api("/graph/v1.0/drives", { method: "POST", data: { name: SHOWCASE_SPACE, driveType: "project" } });
  }
  const groups = await api("/graph/v1.0/groups", { method: "GET" });
  if (groups.ok() && !(await groups.json()).value.some((group) => group.displayName === SHOWCASE_GROUP)) {
    await api("/graph/v1.0/groups", { method: "POST", data: { displayName: SHOWCASE_GROUP } });
  }
  return `${base}/files/spaces/${personal.driveAlias}/${SHOWCASE_FOLDER}`;
}

async function panelOpen(page, selector) {
  const panel = page.locator(selector);
  await expect(panel).toBeVisible({ timeout: resolveTimeout(15_000) });
  await expect
    .poll(() =>
      panel.evaluate(
        (element) =>
          getComputedStyle(element).opacity === "1" &&
          element.getAnimations({ subtree: true }).every((animation) => animation.playState !== "running"),
      ),
    )
    .toBe(true);
}

const ready = (selector) => async (view) => {
  await expect(view.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
};

function signedOutViews() {
  const views = [];
  if (!isServiceEnabled("sso")) {
    views.push(
      { name: "sign-in", url: `${base}/`, prepare: ready("#oc-login-username") },
      {
        name: "sign-in-error",
        url: `${base}/`,
        prepare: async (view) => {
          await view.locator("#oc-login-username").fill(SHOWCASE_FOLDER);
          await view.locator("#oc-login-password").fill(SHOWCASE_FOLDER);
          await view.locator("#oc-login-password").press("Enter");
          await ready("#oc-login-error-message")(view);
        },
      },
    );
  }
  views.push({ name: "access-denied", url: `${base}/access-denied`, prepare: ready("#exitAnchor") });
  return views;
}

function signedInViews(folder) {
  return [
    { name: "files-personal", url: `${base}/files/spaces/personal?view-mode=resource-tiles`, prepare: ready("#files-app-bar") },
    { name: "files-folder", url: `${folder}?view-mode=resource-table`, prepare: ready("#files-space-table") },
    { name: "files-folder-tiles", url: `${folder}?view-mode=resource-tiles`, prepare: ready(".oc-tile-card") },
    { name: "files-empty-folder", url: `${folder}/empty`, prepare: ready("#files-space-empty") },
    {
      name: "files-row-selected",
      url: `${folder}?view-mode=resource-table`,
      prepare: async (view) => {
        await ready("#files-space-table")(view);
        await view.locator("#files-space-table tbody tr input[type=checkbox]").first().check();
        await ready(".oc-table-highlighted")(view);
      },
    },
    { name: "files-favorites", url: `${base}/files/favorites`, prepare: ready("#files-app-bar") },
    { name: "files-shared-with-me", url: `${base}/files/shares/with-me`, prepare: ready("#files-shared-with-me-view") },
    { name: "files-shared-with-others", url: `${base}/files/shares/with-others`, prepare: ready("#files-app-bar") },
    { name: "files-shared-via-link", url: `${base}/files/shares/via-link`, prepare: ready("#files-app-bar") },
    { name: "files-spaces", url: `${base}/files/spaces/projects`, prepare: ready("#files-app-bar") },
    { name: "files-trash", url: `${base}/files/trash/overview`, prepare: ready("#files-app-bar") },
    {
      name: "search-results",
      url: `${base}/search/list?term=design&provider=files.sdk`,
      prepare: ready('.files-search-result-filter ~ * .oc-resource-name, img[src*="empty-search-results"]'),
    },
    { name: "account-information", url: `${base}/account/information`, prepare: ready("#account-information") },
    { name: "account-preferences", url: `${base}/account/preferences`, prepare: ready("#account-preferences") },
    { name: "account-extensions", url: `${base}/account/extensions`, prepare: ready("#account-extensions") },
    { name: "account-calendar", url: `${base}/account/calendar`, prepare: ready("#account-calendar") },
    { name: "account-gdpr", url: `${base}/account/gdpr`, prepare: ready("#account-gdpr") },
    {
      name: "user-menu",
      url: `${base}/account/information`,
      prepare: async (view) => {
        await ready("#account-information")(view);
        await view.locator("#_userMenuButton").click();
        await panelOpen(view, "#account-info-container");
      },
    },
    {
      name: "app-switcher",
      url: `${base}/account/information`,
      prepare: async (view) => {
        await ready("#account-information")(view);
        await view.locator("#_appSwitcherButton").click();
        await panelOpen(view, "#app-switcher-dropdown");
      },
    },
    {
      name: "navigation",
      url: `${base}/files/spaces/personal?view-mode=resource-tiles`,
      prepare: async (view) => {
        await ready("#files-app-bar")(view);
        if (await view.locator("#mobile-nav-button").isVisible()) {
          await view.locator("#mobile-nav-button").click();
          await panelOpen(view, "#sidebar-nav-mobile-panel");
        } else {
          await view.locator("#web-nav-sidebar .oc-sidebar-nav-item-link").nth(1).hover();
        }
      },
    },
    {
      name: "notifications",
      url: `${base}/account/information`,
      prepare: async (view) => {
        await ready("#account-information")(view);
        await view.locator("#oc-notifications-bell").click();
        await panelOpen(view, "#oc-notifications-drop");
      },
    },
    {
      name: "theme-select",
      url: `${base}/account/preferences`,
      prepare: async (view) => {
        await ready("#account-preferences")(view);
        await view.locator(".account-page-info-theme .vs__dropdown-toggle").click();
        await panelOpen(view, ".account-page-info-theme .vs__dropdown-menu");
      },
    },
    {
      name: "view-options",
      url: `${folder}?view-mode=resource-table`,
      prepare: async (view) => {
        await ready("#files-space-table")(view);
        await view.locator("#files-view-options-btn").click();
        await panelOpen(view, "#files-view-options-drop");
      },
    },
    {
      name: "files-details",
      url: `${folder}?view-mode=resource-table`,
      prepare: async (view) => {
        await ready("#files-space-table")(view);
        await view.locator("#files-space-table tbody tr input[type=checkbox]").first().check();
        if (await view.locator("#files-toggle-sidebar").isVisible()) {
          await view.locator("#files-toggle-sidebar").click();
        } else {
          await view.locator("#files-space-table tbody tr .resource-table-btn-action-dropdown").first().click();
          await view.locator(".oc-files-actions-show-details-trigger").first().click();
        }
        await panelOpen(view, "#app-sidebar");
      },
    },
    {
      name: "text-editor",
      url: `${folder.replace("/files/spaces/", "/text-editor/")}/notes.md`,
      prepare: ready("#app-top-bar-resource"),
    },
    {
      name: "create-user",
      url: `${base}/admin-settings/users`,
      prepare: async (view) => {
        await ready("#admin-settings-app-bar")(view);
        await view.locator(".oc-app-floating-action-button:visible").first().click();
        await ready("#create-user-input-user-name")(view);
        await panelOpen(view, ".oc-modal");
      },
    },
    {
      name: "admin-general",
      url: `${base}/admin-settings/general`,
      prepare: async (view) => {
        await ready('img[alt="OpenCloud logo"]')(view);
        await view.locator('img[alt="OpenCloud logo"]').evaluate(async (image) => {
          const symbol = /url\("?(.*?)"?\)/.exec(getComputedStyle(image).content);
          if (!symbol) return;
          const probe = new Image();
          probe.src = symbol[1];
          await probe.decode();
        });
      },
    },
    { name: "admin-users", url: `${base}/admin-settings/users`, prepare: ready("#admin-settings-app-bar") },
    { name: "admin-groups", url: `${base}/admin-settings/groups`, prepare: ready("#admin-settings-app-bar") },
    { name: "admin-spaces", url: `${base}/admin-settings/spaces`, prepare: ready("#admin-settings-app-bar") },
    { name: "app-store", url: `${base}/app-store/list`, prepare: ready("#apps-filter") },
  ];
}

async function open(page, path, selector) {
  await gotoOnion(page, path.startsWith("http") ? path : `${base}${path}`);
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(90_000) });
}

async function eachMode(page, check) {
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await check(mode);
  }
  await page.emulateMedia({ colorScheme: null });
}

async function assertTopBarFocus(page) {
  const expected = await tokenValue(page, "--design-on-frame", "outline-color");
  const stops = [];
  for (let step = 0; step < 24; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate(() => {
      const element = document.activeElement;
      if (!element || !element.closest("#oc-topbar")) return null;
      const style = getComputedStyle(element);
      return {
        name: `${element.tagName.toLowerCase()}#${element.id}`,
        color: style.outlineColor,
        drawn: style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0,
      };
    });
    if (stop) stops.push(stop);
  }
  expect(stops.length, "the Tab walk must reach the controls of the top bar").toBeGreaterThanOrEqual(4);
  expect(
    stops.filter((stop) => !stop.drawn || stop.color !== expected),
    "focus stops of the top bar without an on-frame indicator",
  ).toEqual([]);
}

async function assertMenuFocus(page) {
  await page.locator("#_userMenuButton").click();
  await expect(page.locator("#account-info-container")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  const entry = page.locator("#account-info-container :focus-visible");
  await expect(entry, "the arrow key must focus an entry of the user menu").toHaveCount(1);
  expect(
    await entry.evaluate((element) => getComputedStyle(element).boxShadow),
    "a focused entry of a menu the top bar hosts must draw the ring of the content surface",
  ).toContain(await tokenValue(page, "--design-link", "color"));
  expect(
    await entry.evaluate((element) => getComputedStyle(element).outlineColor),
    "a focused entry of a menu the top bar hosts must not take the on-frame outline",
  ).toBe(await tokenValue(page, "--design-surface-1", "outline-color"));
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "opencloud");
});

test("design: the corporate OpenCloud theme carries frame, page, text and dividers", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await open(page, "/account/preferences", "#account-preferences");

  const config = await (await apiGetOnion(page.request, `${base}/config.json`)).json();
  expect(new URL(config.theme).pathname, "the web client must load the corporate theme").toBe(
    `${themePath}/theme.json`,
  );
  const theme = await (await apiGetOnion(page.request, config.theme)).json();
  const tokens = theme.clients.web.defaults.designTokens;
  expect(
    Object.entries({ ...tokens.roles, ...tokens.colorPalette }).filter(
      ([, value]) => !/^var\(--design-[a-z0-9-]+\)$/.test(value),
    ),
    "every color of the corporate theme must be a palette token",
  ).toEqual([]);
  expect(
    await page.evaluate(() => document.documentElement.style.getPropertyValue("--oc-role-chrome")),
    "the web client must apply the roles of the corporate theme",
  ).toBe("var(--design-frame)");

  await eachMode(page, async (mode) => {
    await assertToken(page, "#web", "background-color", "--design-frame", `opencloud ${mode}`);
    await assertToken(page, "#_appSwitcherButton", "color", "--design-on-frame", `opencloud ${mode}`);
    await assertToken(page, "#account", "background-color", "--design-surface-1", `opencloud ${mode}`);
    await assertToken(page, "#account-preferences h1", "color", "--design-text", `opencloud ${mode}`);
    await assertToken(page, "#account", "border-top-color", "--design-border", `opencloud ${mode}`);
    await assertToken(
      page,
      "#account-preferences tr.account-page-info-language",
      "border-bottom-color",
      "--design-border",
      `opencloud ${mode}`,
    );
    await assertToken(
      page,
      ".oc-sidebar-nav-item-link.active",
      "background-color",
      "--design-surface-active",
      `opencloud ${mode}`,
    );
  });
  expect(
    await page
      .locator("#account-preferences tr.account-page-info-language")
      .evaluate((row) => getComputedStyle(row).borderBottomWidth),
    "the rows of the preferences must draw a divider",
  ).toBe("1px");
  await assertLightAndDark(page, "#account-preferences", "opencloud");
  await assertReadable(
    page,
    [
      "#account-preferences h1",
      "#account-preferences td",
      "#_appSwitcherButton",
      { selector: "#web-nav-sidebar .oc-sidebar-nav-item-link.active", optional: true },
      { selector: "#web-nav-sidebar .oc-sidebar-nav-item-link:not(.active)", optional: true },
    ],
    "opencloud",
  );
});

test("design: selected, hovered and primary controls take their state tokens", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const folder = await seedShowcase(page);
  await open(page, `${folder}?view-mode=resource-table`, "#files-space-table tbody tr");
  const row = page.locator("#files-space-table tbody tr").first();
  await row.locator("input[type=checkbox]").check();
  await expect(row).toHaveClass(/oc-table-highlighted/);
  const other = page.locator("#files-space-table tbody tr:not(.oc-table-highlighted)").first();
  await other.hover();

  await eachMode(page, async (mode) => {
    await assertToken(
      page,
      "#files-space-table tbody tr.oc-table-highlighted",
      "background-color",
      "--design-surface-active",
      `opencloud ${mode}`,
    );
    await assertToken(
      page,
      "#files-space-table tbody tr:not(.oc-table-highlighted):hover",
      "background-color",
      "--design-surface-hover",
      `opencloud ${mode}`,
    );
    await assertToken(
      page,
      "#files-space-table tbody tr:not(.oc-table-highlighted)",
      "border-top-color",
      "--design-border",
      `opencloud ${mode}`,
    );
    await assertToken(
      page,
      "#files-space-table tbody tr.oc-table-highlighted input[type=checkbox]",
      "background-color",
      "--design-primary",
      `opencloud ${mode}`,
    );
  });
  await assertReadable(
    page,
    ["#files-space-table tbody tr.oc-table-highlighted .oc-resource-name", "#files-space-table th"],
    "opencloud file list",
  );
});

test("design: a primary-filled control takes the primary color and its on-color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await allowBrowser(page);
  await open(page, "/access-denied", "#exitAnchor");
  await eachMode(page, async (mode) => {
    await assertToken(page, "#exitAnchor", "background-color", "--design-primary", `opencloud ${mode}`);
    await assertToken(page, "#exitAnchor", "color", "--design-on-primary", `opencloud ${mode}`);
  });
  await assertReadable(page, ["#exitAnchor", ".oc-login .oc-card h2"], "opencloud access denied");
  await expect(
    page.locator('img[alt="OpenCloud emblem"]'),
    "the upstream emblem must not show on the corporate frame",
  ).toBeHidden();
});

test("design: every focus stop inside the top bar draws its indicator in the on-frame color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await open(page, "/account/preferences", "#account-preferences");
  await assertTopBarFocus(page);

  await assertMenuFocus(page);
});

test("design: the theme a user picks overrides the browser preference", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await page.emulateMedia({ colorScheme: "light" });
  await open(page, "/account/preferences", "#account-preferences");
  await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
  const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");

  const pick = async (option) => {
    await page.locator(".account-page-info-theme .vs__dropdown-toggle").click();
    await page.locator(".account-page-info-theme .vs__dropdown-menu li").filter({ hasText: option }).click();
  };

  await pick("Dark Theme");
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
  expect(
    await tokenValue(page, "--design-surface-1", "background-color"),
    "the dark theme must switch the tokens while the browser prefers light",
  ).not.toBe(lightSurface);
  await assertToken(page, "#account", "background-color", "--design-surface-1", "opencloud dark theme");
  await open(page, "/account/preferences", "#account-preferences");
  await expect(page.locator("html"), "a reload must keep the picked theme").toHaveAttribute(
    "data-design-theme",
    "dark",
  );

  await page.emulateMedia({ colorScheme: "dark" });
  await pick("Light Theme");
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
  expect(
    await tokenValue(page, "--design-surface-1", "background-color"),
    "the light theme must keep the light tokens while the browser prefers dark",
  ).toBe(lightSurface);
  await assertToken(page, "#account", "background-color", "--design-surface-1", "opencloud light theme");

  await page.locator(".account-page-info-theme .vs__dropdown-toggle").click();
  await page.locator(".account-page-info-theme .vs__dropdown-menu li").first().click();
  await expect(page.locator("html"), "the automatic theme must follow the browser again").not.toHaveAttribute(
    "data-design-theme",
    /.+/,
  );
  await page.emulateMedia({ colorScheme: null });
});

test("design: OpenCloud serves the generated logo and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await open(page, "/account/preferences", "#account-preferences");
  await expect(page).toHaveTitle(new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  if (!logoUrl) return;

  const served = await apiGetOnion(page.request, `${base}${themePath}/assets/logo.svg`);
  const generated = await apiGetOnion(page.request, logoUrl);
  expect(served.ok(), "OpenCloud serves a theme logo").toBe(true);
  expect(generated.ok(), "the generated logo is published on the CDN").toBe(true);
  expect(await served.text(), "OpenCloud must serve the generated corporate logo").toBe(await generated.text());

  await page.setViewportSize({ width: 1440, height: 900 });
  const logo = page.locator("#oc-topbar .oc-logo-image");
  await expect.poll(() => logo.evaluate((image) => image.currentSrc)).toContain(`${themePath}/assets/logo.svg`);
  await expect.poll(() => logo.evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);
  const box = await logo.boundingBox();
  expect(box.width, "the top bar logo must be a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
  await assertToken(page, "#web", "background-color", "--design-frame", "the logo sits on the frame");
  await expect(page.locator('link[rel~="icon"]')).toHaveAttribute(
    "href",
    new RegExp(`${themePath.replace(/^\//, "")}/assets/favicon\\.svg$`),
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => logo.evaluate((image) => image.currentSrc))
    .toContain(`${themePath}/assets/logo-mobile.svg`);
  await expect.poll(() => logo.evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);
});

test("design: the administration shows the logo symbol in its round box", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(isServiceEnabled("sso"), "the account of the identity provider is no OpenCloud administrator");
  test.skip(!logoUrl, "the logo replacement is disabled for this role");
  await signIn(page);
  await open(page, "/admin-settings/general", 'img[alt="OpenCloud logo"]');
  const logo = page.locator('img[alt="OpenCloud logo"]');
  await expect
    .poll(() => logo.evaluate((image) => getComputedStyle(image).content))
    .toContain(`${themePath}/assets/logo-mobile.svg`);
  const symbol = await logo.evaluate((image) => getComputedStyle(image).content.replace(/^url\("?|"?\)$/g, ""));
  expect(new URL(symbol).origin, "the symbol must come from the origin the content policy allows").toBe(
    new URL(base).origin,
  );
  const served = await apiGetOnion(page.request, symbol);
  expect(served.status(), `${symbol} must be served`).toBe(200);
  expect(await served.text(), "the symbol must be the generated logo").toContain("<svg");
  const box = await logo.boundingBox();
  const frame = await logo.locator("xpath=..").boundingBox();
  expect(box.width, "the symbol must fit the round box").toBeLessThanOrEqual(frame.width);
  expect(box.height, "the symbol must fill most of the round box").toBeGreaterThan(frame.height / 2);
  await assertToken(page, ".bg-role-chrome:has(> img)", "background-color", "--design-frame", "administration logo box");
});

test("design: the built-in sign-in page takes the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(isServiceEnabled("sso"), "the identity provider renders the sign-in page when sso is enabled");
  await allowBrowser(page);
  await open(page, "/", "#oc-login-username");
  await assertDesignTokens(page, "opencloud sign-in");
  await eachMode(page, async (mode) => {
    await assertToken(page, ".oc-login-bg", "background-color", "--design-frame", `sign-in ${mode}`);
    await assertToken(page, ".oc-footer-message", "color", "--design-on-frame", `sign-in ${mode}`);
    await assertToken(page, ".oc-card", "background-color", "--design-surface-2", `sign-in ${mode}`);
    await assertToken(page, ".oc-button-primary", "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, ".oc-button-primary", "color", "--design-on-primary", `sign-in ${mode}`);
    await assertToken(page, "#oc-login-password", "border-top-color", "--design-border-strong", `sign-in ${mode}`);
  });
  await assertLightAndDark(page, ".oc-card h1", "opencloud sign-in");
  await assertReadable(
    page,
    [".oc-card h1", ".oc-label", "#oc-login-password", ".oc-button-primary", ".oc-footer-message"],
    "sign-in",
  );
  await expect(page.locator(".oc-login-bg-icon"), "the upstream emblem must not show on the frame").toBeHidden();
  if (logoUrl) {
    await expect
      .poll(() => page.locator(".oc-logo").evaluate((image) => new URL(image.currentSrc).pathname))
      .toBe(`${themePath}/assets/logo.svg`);
    await expect(page.locator('link[rel~="icon"]')).toHaveAttribute("href", `${themePath}/assets/favicon.svg`);
  }

  await page.locator("#oc-login-username").fill(SHOWCASE_FOLDER);
  await page.locator("#oc-login-password").fill(SHOWCASE_FOLDER);
  await page.locator("#oc-login-password").press("Enter");
  await expect(page.locator("#oc-login-error-message")).toBeVisible({ timeout: resolveTimeout(30_000) });
  await eachMode(page, async (mode) => {
    await assertToken(page, "#oc-login-error-message", "color", "--design-danger", `sign-in error ${mode}`);
    await assertToken(page, ".oc-input.error", "border-top-color", "--design-danger", `sign-in error ${mode}`);
  });
  await assertReadable(page, ["#oc-login-error-message"], "sign-in error");
});

test("design: gallery of sign-in, files, account and administration views", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(1_800_000));
  const failures = [];

  await allowBrowser(page);
  await captureDesignGallery(page, signedOutViews()).catch((error) => failures.push(error.message));

  await signIn(page);
  const folder = await seedShowcase(page);
  await startWithClosedSidebar(page);
  await captureDesignGallery(page, signedInViews(folder)).catch((error) => failures.push(error.message));
  expect(failures, failures.join("\n")).toEqual([]);
});
