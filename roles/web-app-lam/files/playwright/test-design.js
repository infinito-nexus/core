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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const {
  ADMIN_USERNAME,
  LAM,
  LOGIN_BUTTON,
  LOGIN_PASSWORD,
  READY_MS,
  open,
  openSignedIn,
  ready,
  signIn,
} = require("./_shared");

const CONFIG_PASSWORD = decodeDotenvQuotedValue(requireDotenvValue(process.env.LAM_CONFIG_PASSWORD, "LAM_CONFIG_PASSWORD"));
const LOGO_URL = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const DESIGN_ENABLED = process.env.DESIGN_SERVICE_ENABLED === "true";
const INHOUSE_SHEET = 'link[href$="/style/900_infinito.css"]';

async function restMouse(page) {
  await page.mouse.move(1, page.viewportSize().height - 1);
}

async function configSignIn(page, loginPath, path, selector) {
  await open(page, path, "body");
  const password = page.locator('input[type="password"]').first();
  if ((await password.count()) === 0) {
    await ready(page, selector);
    return;
  }
  await open(page, loginPath, 'input[type="password"]');
  await expect(password).toBeEditable({ timeout: resolveTimeout(READY_MS) });
  await password.fill(CONFIG_PASSWORD);
  await password.press("Enter");
  await page.waitForLoadState("domcontentloaded");
  await gotoOnion(page, `${LAM}/${path}`);
  await ready(page, selector);
}

function galleryViews() {
  const visitor = (name, path, selector, extra) => ({
    name,
    url: `${LAM}/${path}`,
    prepare: async (p) => {
      await ready(p, selector);
      await restMouse(p);
      if (extra) await extra(p);
    },
  });
  const config = (name, loginPath, path, selector) => ({
    name,
    url: `${LAM}/${path}`,
    prepare: async (p) => {
      await configSignIn(p, loginPath, path, selector);
      await restMouse(p);
    },
  });
  const signedIn = (name, path, selector, extra) => ({
    name,
    url: `${LAM}/${path}`,
    prepare: async (p) => {
      await openSignedIn(p, path, selector);
      await restMouse(p);
      if (extra) await extra(p);
    },
  });
  return [
    visitor("login", "login.php", LOGIN_BUTTON),
    visitor("login-error", "login.php", LOGIN_BUTTON, async (p) => {
      const password = p.locator(LOGIN_PASSWORD);
      await expect(password).toBeEditable({ timeout: resolveTimeout(READY_MS) });
      await password.fill(`wrong-${Date.now()}-${Math.random().toString(36).slice(2)}`);
      await p.locator(LOGIN_BUTTON).click();
      await ready(p, "div.statusError");
      await restMouse(p);
    }),
    visitor("config-start", "config/index.php", "body"),
    visitor("config-main-login", "config/mainlogin.php", 'input[type="password"]'),
    visitor("config-profile-login", "config/conflogin.php", 'input[type="password"]'),
    config("config-main-settings", "config/mainlogin.php", "config/mainmanage.php", "form"),
    config("config-profiles-manage", "config/mainlogin.php", "config/profmanage.php", "form"),
    config("config-profile-general", "config/conflogin.php", "config/confmain.php", "form"),
    config("config-profile-types", "config/conflogin.php", "config/conftypes.php", "form"),
    config("config-profile-modules", "config/conflogin.php", "config/confmodules.php", "form"),
    config("config-profile-module-settings", "config/conflogin.php", "config/moduleSettings.php", "form"),
    signedIn("users-list", "lists/list.php?type=user", "table.accountlist tbody tr"),
    signedIn("accounts-menu", "lists/list.php?type=user", "table.accountlist tbody tr", async (p) => {
      if (await p.locator("button.lam-menu-icon").isVisible()) {
        await p.locator("button.lam-menu-icon").click();
        await ready(p, ".lam-header.lam-header-open a.lam-menu-entry.icon");
      } else {
        await p.locator("a.lam-menu-entry", { hasText: "Accounts" }).click();
        await expect
          .poll(
            () =>
              p
                .locator("#lam-navigation-types")
                .evaluate((el) => el.getAnimations().length === 0 && el.offsetHeight > 0 && el.offsetHeight === el.firstElementChild.offsetHeight),
            { timeout: resolveTimeout(READY_MS) },
          )
          .toBe(true);
      }
    }),
    signedIn("help-tooltip", "account/edit.php?type=user", "img[onmouseenter]", async (p) => {
      await p.locator("img[onmouseenter]").first().hover();
      await ready(p, "div.lam-help:not(.hidden)");
    }),
    signedIn("user-edit", "lists/list.php?type=user", "table.accountlist tbody tr", async (p) => {
      await p.locator('table.accountlist tbody a:has(img[src$="/edit.svg"])').first().click();
      await ready(p, "li.lam-vertical-tabs-selected");
      await restMouse(p);
    }),
    signedIn("user-edit-unix", "lists/list.php?type=user", "table.accountlist tbody tr", async (p) => {
      await p.locator('table.accountlist tbody a:has(img[src$="/edit.svg"])').first().click();
      await ready(p, "li.lam-vertical-tabs-selected");
      await p.locator("li.lam-vertical-tabs:not(.lam-vertical-tabs-selected) button.lam-account-type").first().click();
      await ready(p, "li.lam-vertical-tabs-selected");
      await restMouse(p);
    }),
    signedIn("user-new", "account/edit.php?type=user", "button.lam-account-type"),
    signedIn("groups-list", "lists/list.php?type=group", "table.accountlist, div.statusInfo"),
    signedIn("group-new", "account/edit.php?type=group", "button.lam-account-type"),
    signedIn("tree-view", "tools/treeView.php", "div.wunderbaum"),
    signedIn("tree-entry", "tools/treeView.php", "div.wunderbaum", async (p) => {
      await p.locator("div.wunderbaum span.wb-title", { hasText: /^ou=users$/ }).click();
      await ready(p, ".tree-right-area input, .tree-right-area table");
      await restMouse(p);
    }),
    signedIn("server-info", "tools/serverInfo.php", "div.smallPaddingContent div.row"),
    signedIn("schema-browser", "schema/schema.php", "select"),
    signedIn("tests", "tests/schemaTest.php", "div.smallPaddingContent div.row"),
    signedIn("ou-editor", "tools/ou_edit.php", "form"),
    signedIn("profile-editor", "profedit/profilemain.php", "form"),
    signedIn("pdf-editor", "pdfedit/pdfmain.php", "form"),
    signedIn("file-upload", "upload/masscreate.php", "form"),
    signedIn("multi-edit", "tools/multiEdit.php", "form"),
    signedIn("import-export", "tools/importexport.php", "form"),
  ];
}

exports.register = function () {
  test("LAM: the administrator signs in with the directory login and reaches the account list", async ({ page }) => {
    await signIn(page);
    await expect(page).not.toHaveURL(/login\.php/);
    await openSignedIn(page, "lists/list.php?type=user", "table.accountlist tbody tr");
    await expect(page.locator("table.accountlist tbody")).toContainText(ADMIN_USERNAME);
    await expect(page.locator('button[name="new"]')).toBeVisible();
  });

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    expect(DESIGN_ENABLED).toBe(true);
    await open(page, "login.php", LOGIN_BUTTON);
    await assertDesignTokens(page, "lam");
  });

  test("design: the in-house stylesheet is linked after LAM's own and maps the login page", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, "login.php", LOGIN_BUTTON);
    await expect(page.locator(INHOUSE_SHEET)).toHaveCount(1);
    const sheets = await page
      .locator('link[rel="stylesheet"][href*="/style/"]')
      .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
    expect(sheets.at(-1), "900_infinito.css must be the last of LAM's own stylesheets").toMatch(/\/style\/900_infinito\.css$/);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `lam body ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `lam text ${mode}`);
      await assertToken(page, ".roundedShadowBox", "background-color", "--design-surface-2", `lam login box ${mode}`);
      await assertToken(page, LOGIN_BUTTON, "background-color", "--design-primary", `lam login button ${mode}`);
      await assertToken(page, LOGIN_BUTTON, "color", "--design-on-primary", `lam login label ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".roundedShadowBox", "lam login box");
    await assertReadable(page, ["body", ".roundedShadowBox label"], "lam login");
  });

  test("design: the header shows the corporate logo from the CDN", async ({ page, request }) => {
    skipUnlessServiceEnabled("design");
    expect(LOGO_URL, "DESIGN_LOGO_URL must name the generated logo").toBeTruthy();
    await open(page, "login.php", "div.lam-header-left img");
    const logo = page.locator("div.lam-header-left img").first();
    expect(await logo.evaluate((el) => getComputedStyle(el).content), "the header logo is the configured one").toContain(LOGO_URL);
    const box = await logo.boundingBox();
    expect([box.width, box.height], "the logo keeps LAM's square 24 px box").toEqual([24, 24]);
    const response = await apiGetOnion(request, LOGO_URL, { timeout: resolveTimeout(30_000) });
    expect(response.status(), `${LOGO_URL} must be served`).toBe(200);
    expect(response.headers()["content-type"] || "").toContain("svg");
  });

  test("design: LAM's pages and header carry the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
    test.skip(!title, "the title replacement is disabled for this role");
    const lead = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "login.php", LOGIN_BUTTON);
    await expect(page).toHaveTitle(title);
    await expect(page.locator("div.lam-header-left > a > span.hide-on-mobile")).toHaveText(new RegExp(`^${lead} - \\S+$`));
    await openSignedIn(page, "lists/list.php?type=user", "table.accountlist tbody tr");
    await expect(page).toHaveTitle(new RegExp(`^${lead} \\(.+\\)$`));
    const version = page.locator("div.lam-header-left > a > span.hide-on-mobile-and-tablet");
    await expect(version).toBeVisible();
    await expect(version).toHaveText(new RegExp(`^${lead} - \\S+$`));
    await configSignIn(page, "config/conflogin.php", "config/confmain.php", "form");
    await expect(page).toHaveTitle(new RegExp(`^${lead}( |$)`));
  });

  test("design: signed-in list rows, dividers and controls follow the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignedIn(page, "lists/list.php?type=user", "table.accountlist tbody tr");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "table.accountlist", "border-top-color", "--design-border", `lam list border ${mode}`);
      await assertToken(page, 'button[name="new"]', "background-color", "--design-primary", `lam new ${mode}`);
      await assertToken(page, 'button[name="new"]', "color", "--design-on-primary", `lam new label ${mode}`);
      const link = await page.locator("table.accountlist tbody a").first().evaluate((el) => getComputedStyle(el).color);
      expect(link, `lam list link ${mode}`).toBe(await tokenValue(page, "--design-link", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "table.accountlist", "lam list");
    await assertReadable(page, ["table.accountlist tbody td"], "lam list");
  });

  test("design: the server profile editor carries the tokens although LAM never closes its head", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await configSignIn(page, "config/conflogin.php", "config/confmain.php", "form");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      expect(await tokenValue(page, "--design-surface-1", "background-color"), `lam confmain token ${mode}`).not.toBe("rgba(0, 0, 0, 0)");
      await assertToken(page, "body", "background-color", "--design-surface-1", `lam confmain ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `lam confmain text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "body", "lam confmain");
  });

  test("design: monochrome action icons follow the mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignedIn(page, "lists/list.php?type=user", 'table.accountlist img[src$="/edit.svg"]');
    const icon = page.locator('table.accountlist img[src$="/edit.svg"]').first();
    for (const [mode, expected] of [
      ["light", "invert(0) hue-rotate(0deg)"],
      ["dark", "invert(1) hue-rotate(180deg)"],
    ]) {
      await page.emulateMedia({ colorScheme: mode });
      expect(await icon.evaluate((el) => getComputedStyle(el).filter), `lam icon ${mode}`).toBe(expected);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: gallery", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "gallery runs only with INFINITO_PLAYWRIGHT_KEEP=true");
    test.setTimeout(resolveTimeout(900_000));
    await captureDesignGallery(page, galleryViews());
  });
};
