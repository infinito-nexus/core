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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const MENU_BAR = "[data-test='app-menu-bar']";
const MENU_BUTTON = `${MENU_BAR} button[data-label]`;
const USER_MENU = "[data-test='loggedin-username']";
const LOGO = ".AppMenuBar-logo";
const LOGIN_LOGO = ".BasePage-logo";
const LOGIN_CARD = ".BasePage-pageContent";
const LOGIN_BUTTON = "button[name='internal_button']";
const TREE = ".file-tree";
const ENTRY = ".file-entry";
const PANE = ".dock-layout .dock-tabpane-active";
const TAB = ".dock-layout .dock-tab";
const ACTIVE_TAB = ".dock-layout .dock-tab-active";
const OPEN_MENU = ".szh-menu--state-open";
const DIALOG = ".dock-panel.dock-style-dialogs, .MuiDialog-paper";
const SERVER_NAME = "Infinito Postgres";
const READY = 10_000;

const base = decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const ssoUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const db = {
  host: decodeDotenvQuotedValue(process.env.PGADMIN_DB_HOST),
  name: decodeDotenvQuotedValue(process.env.PGADMIN_DB_NAME),
  password: decodeDotenvQuotedValue(process.env.PGADMIN_DB_PASSWORD),
  port: decodeDotenvQuotedValue(process.env.PGADMIN_DB_PORT),
  user: decodeDotenvQuotedValue(process.env.PGADMIN_DB_USER),
};

/**
 * Args:
 *   page: Playwright page; opens /login, passing the identity provider first when sso gates the proxy.
 */
async function openLogin(page) {
  await gotoOnion(page, `${base}/login`);
  if (page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(page, ssoUsername, adminPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
    await gotoOnion(page, `${base}/login`);
  }
}

/**
 * Args:
 *   page: Playwright page; ends signed in on /browser/ with the menu bar and the tree rendered.
 */
async function signIn(page) {
  await openLogin(page);
  if (page.url().includes("/login")) {
    const email = page.locator("input[name='email']");
    await expect(email).toBeEditable({ timeout: resolveTimeout(READY) });
    await email.fill(adminEmail);
    const password = page.locator("input[name='password']");
    await expect(password).toBeEditable({ timeout: resolveTimeout(READY) });
    await password.fill(adminPassword);
    await page.locator(LOGIN_BUTTON).click();
  }
  await expect(page.locator(MENU_BAR)).toBeVisible({ timeout: resolveTimeout(60_000) });
  await expect(page.locator(TREE).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function onBrowser(page) {
  if (page.url().includes("/login") || page.url().includes("openid-connect")) await signIn(page);
  await expect(page.locator(TREE).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function openMenu(page, menu, item) {
  await page.locator(`${MENU_BAR} button[data-label='${menu}']`).click({ timeout: resolveTimeout(READY) });
  const panel = page.locator(OPEN_MENU).first();
  await expect(panel).toBeVisible({ timeout: resolveTimeout(READY) });
  if (item) await panel.getByRole("menuitem", { name: item }).first().click({ timeout: resolveTimeout(READY) });
}

async function openSubMenu(page, menu, group, item) {
  await openMenu(page, menu);
  await page.locator(OPEN_MENU).getByRole("menuitem", { name: group }).first().hover({ timeout: resolveTimeout(READY) });
  await page.locator(OPEN_MENU).getByRole("menuitem", { name: item }).first().click({ timeout: resolveTimeout(READY) });
}

function entry(page, text) {
  return page.locator(ENTRY).filter({ has: page.locator(".file-name", { hasText: new RegExp(`^${text}$`) }) }).first();
}

async function selectEntry(page, text) {
  const node = entry(page, text);
  await node.click({ timeout: resolveTimeout(READY) });
  await expect(node).toHaveClass(/active/, { timeout: resolveTimeout(READY) });
}

async function openTab(page, title) {
  await page.locator(`${TAB}:visible`, { hasText: title }).first().click({ timeout: resolveTimeout(READY) });
  await expect(page.locator(ACTIVE_TAB, { hasText: title }).first()).toBeVisible({ timeout: resolveTimeout(READY) });
}

async function openDialog(page) {
  const dialog = page.locator(DIALOG).last();
  await expect(dialog).toBeVisible({ timeout: resolveTimeout(READY) });
  return dialog;
}

/**
 * Args:
 *   page: signed-in Playwright page on /browser/; registers the role's own database with the role's database user once.
 */
async function ensureServer(page) {
  await selectEntry(page, "Servers");
  const server = entry(page, SERVER_NAME);
  if (await server.count()) return;
  await page.keyboard.press("ArrowRight");
  const listed = await server.waitFor({ state: "visible", timeout: resolveTimeout(5_000) }).then(() => true, () => false);
  if (listed) return;
  await openSubMenu(page, "Object", /^Register/, "Server...");
  const dialog = await openDialog(page);
  await expect(dialog.locator("input[name='name']")).toBeEditable({ timeout: resolveTimeout(READY) });
  await dialog.locator("input[name='name']").fill(SERVER_NAME);
  await dialog.locator("[data-test='Connection']").click();
  await dialog.locator("input[name='host']").fill(db.host);
  await dialog.locator("input[name='port']").fill(db.port);
  await dialog.locator("input[name='db']").fill(db.name);
  await dialog.locator("input[name='username']").fill(db.user);
  const secret = dialog.locator("input[name='password']");
  await expect(secret).toBeEditable({ timeout: resolveTimeout(READY) });
  await secret.fill(db.password);
  await dialog.locator("input[name='save_password']").check({ force: true });
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(server).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function onServers(page, tab) {
  await onBrowser(page);
  await selectEntry(page, "Servers");
  if (tab) await openTab(page, tab);
}

async function registerDialog(page, tab) {
  await onServers(page);
  await openSubMenu(page, "Object", /^Register/, "Server...");
  const dialog = await openDialog(page);
  if (tab) await dialog.getByRole("tab", { name: tab, exact: true }).click({ timeout: resolveTimeout(READY) });
  return dialog;
}

async function userMenu(page, item) {
  await onBrowser(page);
  await page.locator(USER_MENU).click({ timeout: resolveTimeout(READY) });
  const panel = page.locator(OPEN_MENU).first();
  await expect(panel).toBeVisible({ timeout: resolveTimeout(READY) });
  if (item) await panel.getByRole("menuitem", { name: item }).click({ timeout: resolveTimeout(READY) });
}

async function signedOut(page) {
  await page.context().clearCookies();
  await gotoOnion(page, `${base}/login`);
  await expect(page.locator(LOGIN_CARD)).toBeVisible({ timeout: resolveTimeout(READY) });
}

function views() {
  const browser = `${base}/browser/`;
  return [
    { name: "login", url: `${base}/login`, prepare: signedOut },
    {
      name: "forgot-password",
      url: `${base}/login`,
      prepare: async (page) => {
        await signedOut(page);
        await page.getByRole("link", { name: /Forgotten your password/ }).click();
        await expect(page.locator("input[name='email']")).toBeVisible({ timeout: resolveTimeout(READY) });
      },
    },
    { name: "welcome", url: browser, prepare: onBrowser },
    { name: "servers-dashboard", url: browser, prepare: (page) => onServers(page, "Dashboard") },
    { name: "servers-properties", url: browser, prepare: (page) => onServers(page, "Properties") },
    { name: "servers-sql", url: browser, prepare: (page) => onServers(page, "SQL") },
    { name: "servers-statistics", url: browser, prepare: (page) => onServers(page, "Statistics") },
    { name: "processes", url: browser, prepare: (page) => onServers(page, "Processes") },
    { name: "register-server", url: browser, prepare: (page) => registerDialog(page) },
    { name: "register-server-connection", url: browser, prepare: async (page) => { const dialog = await registerDialog(page, "Connection"); await dialog.locator("input[name='host']").focus(); } },
    { name: "register-server-ssh", url: browser, prepare: (page) => registerDialog(page, "SSH Tunnel") },
    { name: "register-server-advanced", url: browser, prepare: (page) => registerDialog(page, "Advanced") },
    { name: "create-server-group", url: browser, prepare: async (page) => { await onServers(page); await openSubMenu(page, "Object", /^Create/, "Server Group..."); await openDialog(page); } },
    { name: "preferences", url: browser, prepare: async (page) => { await onBrowser(page); await openMenu(page, "File", "Preferences"); await expect(page.locator(ACTIVE_TAB, { hasText: "Preferences" }).first()).toBeVisible({ timeout: resolveTimeout(READY) }); } },
    { name: "about", url: browser, prepare: async (page) => { await onBrowser(page); await openMenu(page, "Help", /About/); await openDialog(page); } },
    { name: "user-management", url: browser, prepare: async (page) => { await userMenu(page, /User Management/); await expect(page.locator(ACTIVE_TAB, { hasText: "User Management" }).first()).toBeVisible({ timeout: resolveTimeout(READY) }); } },
    { name: "change-password", url: browser, prepare: async (page) => { await userMenu(page, /Change Password/); await openDialog(page); } },
    { name: "user-menu", url: browser, prepare: (page) => userMenu(page) },
    { name: "file-menu", url: browser, prepare: async (page) => { await onBrowser(page); await openMenu(page, "File"); } },
    { name: "tools-menu", url: browser, prepare: async (page) => { await onBrowser(page); await openMenu(page, "Tools"); } },
    { name: "help-menu", url: browser, prepare: async (page) => { await onBrowser(page); await openMenu(page, "Help"); } },
    { name: "object-menu", url: browser, prepare: async (page) => { await onServers(page); await openMenu(page, "Object"); await page.locator(OPEN_MENU).getByRole("menuitem", { name: /^Register/ }).first().hover({ timeout: resolveTimeout(READY) }); } },
    { name: "context-menu", url: browser, prepare: async (page) => { await onServers(page); await entry(page, "Servers").click({ button: "right", timeout: resolveTimeout(READY) }); await expect(page.locator(OPEN_MENU).first()).toBeVisible({ timeout: resolveTimeout(READY) }); } },
  ];
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await assertDesignTokens(page, "pgadmin");
  });

  test("design: the administrator signs in with the users password and holds admin rights", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await expect(page.locator(USER_MENU)).toContainText(adminEmail);
    await page.locator(USER_MENU).click();
    await expect(page.locator(OPEN_MENU).getByRole("menuitem", { name: /User Management/ })).toBeVisible({ timeout: resolveTimeout(READY) });
  });

  test("design: page, panes, tree and tabs take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, PANE, "background-color", "--design-surface-1", `pane ${mode}`);
      await assertToken(page, TREE, "color", "--design-text", `tree text ${mode}`);
      await assertToken(page, ACTIVE_TAB, "color", "--design-link", `active tab ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, PANE, "pgadmin pane");
    await assertReadable(page, [`${ENTRY} .file-name`, TAB, ACTIVE_TAB], "pgadmin browser");
  });

  test("design: the menu bar is the frame and keeps its focus indicator", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, MENU_BAR, "background-color", "--design-frame", `menu bar ${mode}`);
      await assertToken(page, MENU_BUTTON, "color", "--design-on-frame", `menu entry ${mode}`);
      const ring = await tokenValue(page, "--design-on-frame", "outline-color");
      const count = await page.locator(MENU_BUTTON).count();
      await page.locator(MENU_BUTTON).nth(1).focus();
      await page.keyboard.press("Shift+Tab");
      for (let stop = 0; stop < count; stop += 1) {
        const drawn = await page.evaluate(() => {
          const style = getComputedStyle(document.activeElement);
          return { label: document.activeElement.dataset.label, color: style.outlineColor, width: style.outlineWidth, line: style.outlineStyle };
        });
        expect(drawn.line, `focus on ${drawn.label} ${mode}`).not.toBe("none");
        expect(drawn.color, `focus on ${drawn.label} ${mode}`).toBe(ring);
        await page.keyboard.press("Tab");
      }
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [MENU_BUTTON, USER_MENU], "pgadmin menu bar");
  });

  test("design: primary actions carry the on-primary text", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLogin(page);
    const email = page.locator("input[name='email']");
    await expect(email).toBeEditable({ timeout: resolveTimeout(READY) });
    await email.fill(adminEmail);
    const password = page.locator("input[name='password']");
    await expect(password).toBeEditable({ timeout: resolveTimeout(READY) });
    await password.fill(`probe-${Date.now()}`);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, LOGIN_BUTTON, "background-color", "--design-primary", `login button ${mode}`);
      await assertToken(page, LOGIN_BUTTON, "color", "--design-on-primary", `login button text ${mode}`);
      await assertToken(page, LOGIN_CARD, "color", "--design-on-frame", `login card text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [LOGIN_BUTTON], "pgadmin login");
  });

  test("design: the native theme switch drives the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    const html = page.locator("html");
    expect(await page.evaluate(() => window.theme), "a fresh account follows the browser").toBe("system");
    await expect(html).not.toHaveAttribute("data-design-theme", /./);
    await page.emulateMedia({ colorScheme: "dark" });
    const dark = await tokenValue(page, "--design-surface-1", "background-color");
    await page.emulateMedia({ colorScheme: "light" });
    const pick = (value) => page.evaluate((theme) => {
      const channel = new BroadcastChannel("preference-change");
      channel.postMessage({ data: [{ module: "misc", name: "theme", value: theme }], version: Date.now() });
      channel.close();
    }, value);
    await pick("dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    await assertToken(page, PANE, "background-color", "--design-surface-1", "pane after picking dark");
    expect(await tokenValue(page, "--design-surface-1", "background-color"), "picking dark switches the tokens").toBe(dark);
    await pick("high_contrast");
    await expect(html).toHaveAttribute("data-pgadmin-theme", "high_contrast");
    await expect(html).not.toHaveAttribute("data-design-theme", /./);
    await pick("system");
    await expect(html).not.toHaveAttribute("data-pgadmin-theme", /./);
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: logo, favicon and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const loginLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGIN_LOGO_URL);
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await openLogin(page);
    if (title) await expect(page).toHaveTitle(title);
    if (loginLogoUrl) await expect(page.locator(LOGIN_LOGO)).toHaveCSS("background-image", `url("${loginLogoUrl}")`);
    await signIn(page);
    if (title) await expect(page).toHaveTitle(title);
    if (!logoUrl) return;
    await expect(page.locator(LOGO)).toHaveCSS("background-image", `url("${logoUrl}")`);
    const box = await page.locator(LOGO).boundingBox();
    expect(box.width, "the lockup in the menu bar is wider than high").toBeGreaterThan(box.height * 1.5);
    for (const icon of await page.locator("link[rel~='icon']").all()) {
      await expect(icon).toHaveAttribute("href", faviconUrl);
    }
    for (const url of [logoUrl, loginLogoUrl, faviconUrl]) {
      expect((await apiGetOnion(page.request, url)).ok(), `${url} is published on the CDN`).toBe(true);
    }
    const channels = (await tokenValue(page, "--design-on-frame", "color")).match(/\d+/g).slice(0, 3);
    const onFrame = `#${channels.map((channel) => Number(channel).toString(16).padStart(2, "0")).join("")}`;
    for (const url of [logoUrl, loginLogoUrl]) {
      const svg = (await (await apiGetOnion(page.request, url)).text()).toLowerCase();
      expect(svg, `${url} renders its text in the frame text color ${onFrame}`).toContain(`fill="${onFrame}"`);
    }
  });

  test("design: gallery of login, object explorer, panels, dialogs, query tool and settings", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    await signIn(page);
    await ensureServer(page);
    await captureDesignGallery(page, views());
  });};
