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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { isServiceEnabled, skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const base = shared.env.appBaseUrl;
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const MODES = ["light", "dark"];
const HEADER = ".euiHeader.primaryHeader";
const MARK = ".header__homeLoaderNavButton img";
const SUBMIT = "[data-test-subj='submit']";
const PANEL = ".euiPanel:has(.euiTableRow)";
const DEPLOY = "a.euiButton:has-text('Deploy new agent')";
const LOADING = ".euiLoadingContent, .euiProgress, .euiLoadingSpinner--large, .euiLoadingSpinner--xLarge";

async function settled(page) {
  await page
    .waitForFunction((selector) => !document.querySelector(selector), LOADING, { timeout: resolveTimeout(10_000) })
    .catch(() => {});
}

async function openLogin(page) {
  await gotoOnion(page, `${base}/app/login`);
  await expect(page.locator(SUBMIT)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function signIn(page) {
  if (isServiceEnabled("sso")) {
    await shared.wazuhLoginViaOidc(page, base, adminUsername, adminPassword);
    return;
  }
  await openLogin(page);
  const user = page.locator("[data-test-subj='user-name']");
  const password = page.locator("[data-test-subj='password']");
  await expect(user).toBeEditable({ timeout: resolveTimeout(10_000) });
  await user.fill(adminUsername);
  await expect(password).toBeEditable({ timeout: resolveTimeout(10_000) });
  await password.fill(adminPassword);
  await page.locator(SUBMIT).click();
  await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).not.toContain("/app/login");
}

async function open(page, path, ready) {
  await gotoOnion(page, `${base}${path}`);
  await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  await settled(page);
}

function target(page, ready) {
  return ready.startsWith("text=") ? page.getByText(ready.slice(5)) : page.locator(ready);
}

function shown(ready) {
  return async (page) => {
    await expect(target(page, ready).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    await settled(page);
  };
}

function opened(ready, trigger, panel) {
  return async (page) => {
    await shown(ready)(page);
    if (!(await page.locator(panel).first().isVisible())) await page.locator(trigger).first().click();
    await expect(page.locator(panel).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(page.locator(panel).first()).toHaveCSS("opacity", "1", { timeout: resolveTimeout(10_000) });
    await settled(page);
  };
}

function loginViews() {
  return [
    { name: "login", url: `${base}/app/login`, prepare: shown(SUBMIT) },
    {
      name: "login-error",
      url: `${base}/app/login`,
      prepare: async (page) => {
        await shown(SUBMIT)(page);
        await page.locator("[data-test-subj='user-name']").fill("design-gallery");
        await page.locator("[data-test-subj='password']").fill("design-gallery");
        await page.locator(SUBMIT).click();
        await shown("text=Invalid username or password")(page);
      },
    },
  ];
}

function appViews() {
  const app = (name, path, ready) => ({ name, url: `${base}${path}`, prepare: shown(ready) });
  return [
    app("home", "/app/home#/", "text=Manage your data"),
    { name: "navigation", url: `${base}/app/home?view=navigation#/`, prepare: opened("text=Manage your data", "[data-test-subj='toggleNavButton']", ".euiCollapsibleNav") },
    { name: "user-menu", url: `${base}/app/home?view=user-menu#/`, prepare: opened("text=Manage your data", `${HEADER} .euiAvatar--user`, ".euiPopover__panel") },
    { name: "help-menu", url: `${base}/app/home?view=help-menu#/`, prepare: opened("text=Manage your data", "[data-test-subj='helpMenuButton']", ".euiPopover__panel") },
    app("endpoints", "/app/endpoints-summary", DEPLOY),
    app("overview", "/app/wz-home", DEPLOY),
    app("endpoint-groups", "/app/endpoint-groups", ".euiTableRow:has-text('default')"),
    app("rules", "/app/rules", "text=Rules (4,"),
    app("decoders", "/app/decoders", "text=Decoders (1,"),
    app("cdb-lists", "/app/cdb-lists", ".euiTableRow:has-text('audit-keys')"),
    app("server-status", "/app/server-status", "text=wazuh-analysisd"),
    app("statistics", "/app/statistics", "text=Listener Engine"),
    app("threat-hunting", "/app/threat-hunting", "text=Generate report"),
    app("mitre-attack", "/app/mitre-attack", "text=Framework"),
    app("vulnerability-detection", "/app/vulnerability-detection", "text=Inventory"),
    app("ruleset-test", "/app/ruleset-test", "text=Clear session"),
    app("wazuh-security", "/app/security", ".euiTableRow:has-text('wazuh-wui') .euiBadge"),
    app("app-settings", "/app/app-settings", "text=App current settings"),
    app("about", "/app/about", "text=App version"),
    app("discover", "/app/discover#/", "text=Available fields"),
    app("dashboards", "/app/dashboards#/list", "text=Create your first dashboard"),
    app("alerting", "/app/alerting", "text=Alerts by triggers"),
    app("notifications", "/app/notifications-dashboards", "text=Channels (0)"),
    app("reporting", "/app/reports-dashboards", "text=Reports (0)"),
    app("index-management", "/app/opensearch_index_management_dashboards#/indices", ".euiTableRow:has-text('wazuh-alerts')"),
    app("security-users", "/app/security-dashboards-plugin#/users", ".euiTableRow:has-text('kibanaserver')"),
    app("security-roles", "/app/security-dashboards-plugin#/roles", ".euiTableRow:has-text('all_access')"),
    app("advanced-settings", "/app/management/opensearch-dashboards/settings", ".euiFormRow"),
    app("dev-tools", "/app/dev_tools#/console", ".ace_editor"),
  ];
}

function hex(rgb) {
  return `#${rgb
    .match(/\d+/g)
    .slice(0, 3)
    .map((channel) => Number(channel).toString(16).padStart(2, "0"))
    .join("")}`;
}

async function setDarkMode(page, value) {
  const response = await apiFetchOnion(page.request, `${base}/api/opensearch-dashboards/settings`, {
    method: "POST",
    headers: { "osd-xsrf": "true", "Content-Type": "application/json" },
    data: { changes: { "theme:darkMode": value } },
  });
  expect(response.ok(), `theme:darkMode=${value} answers ${response.status()}`).toBe(true);
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await open(page, "/app/home#/", HEADER);
    await assertDesignTokens(page, "wazuh");
  });

  test("design: page, header, panel, primary action and table take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await open(page, "/app/security-dashboards-plugin#/users", ".euiTableRow");
    const create = `${PANEL} .euiButton--primary.euiButton--fill`;
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await page.mouse.move(0, 0);
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, HEADER, "background-color", "--design-surface-2", `header ${mode}`);
      await assertToken(page, PANEL, "background-color", "--design-surface-2", `panel ${mode}`);
      await assertToken(page, ".euiTableRowCell", "color", "--design-text", `cell text ${mode}`);
      await assertToken(page, ".euiTableRowCell", "border-bottom-color", "--design-border", `row divider ${mode}`);
      await assertToken(page, ".euiTableRowCellCheckbox", "border-bottom-color", "--design-border", `checkbox divider ${mode}`);
      await assertToken(page, create, "background-color", "--design-primary", `create user ${mode}`);
      await assertToken(page, create, "color", "--design-on-primary", `create user ${mode}`);
      await page.locator(create).first().hover();
      await assertToken(page, create, "background-color", "--design-primary-hover", `hovered create user ${mode}`);
      await assertToken(page, create, "color", "--design-on-primary", `hovered create user ${mode}`);
      await assertToken(page, ".euiBreadcrumbWrapper--last", "color", "--design-text", `current breadcrumb ${mode}`);
    }
    await page.mouse.move(0, 0);
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, PANEL, "wazuh users panel");
    await assertReadable(
      page,
      [".euiTableRowCell", create, ".euiBreadcrumbWrapper--last .euiBreadcrumb", ".euiBreadcrumbWrapper--first .euiBreadcrumb", ".euiSideNavItemButton"],
      "wazuh users page",
    );
  });

  test("design: badges and the avatar leave the inline upstream colors behind", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    if (!isServiceEnabled("sso")) {
      await open(page, "/app/security-dashboards-plugin#/users", ".euiTableRow .euiBadge");
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        await assertToken(page, ".euiTableRow .euiBadge", "background-color", "--design-surface-active", `current badge ${mode}`);
        await assertToken(page, ".euiTableRow .euiBadge", "color", "--design-text", `current badge ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
      await assertReadable(page, [".euiTableRow .euiBadge"], "wazuh current-user badge");
    }
    await open(page, "/app/security", ".euiTableRow .euiBadge");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".euiTableRow .euiBadge", "background-color", "--design-success", `api role badge ${mode}`);
      await assertToken(page, ".euiTableRow .euiBadge", "color", "--design-on-success", `api role badge ${mode}`);
      await assertToken(page, `${HEADER} .euiAvatar--user`, "background-color", "--design-primary", `avatar ${mode}`);
      await assertToken(page, `${HEADER} .euiAvatar--user`, "color", "--design-on-primary", `avatar ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [".euiTableRow .euiBadge", `${HEADER} .euiAvatar--user`], "wazuh api role badges");
  });

  test("design: the sign-in page sits on the frame with the generated lockup", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    skipUnlessServiceDisabled("sso");
    const loginUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGIN_URL);
    test.skip(!loginUrl, "logo replacement is disabled for this role");
    await openLogin(page);
    await expect(page.locator(".login-wrapper .euiImage__img")).toHaveAttribute("src", loginUrl);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".wz-login", "background-color", "--design-frame", `sign-in backdrop ${mode}`);
      await expect(page.locator(".wz-login")).toHaveCSS("background-image", "none");
      await assertToken(page, SUBMIT, "background-color", "--design-primary", `log in ${mode}`);
      await assertToken(page, SUBMIT, "color", "--design-on-primary", `log in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(
      page,
      [SUBMIT, "[data-test-subj='user-name']", ".euiFormControlLayoutCustomIcon"],
      "wazuh sign-in form",
      3,
    );
    const svg = await (await apiGetOnion(page.request, loginUrl)).text();
    const onFrame = hex(await tokenValue(page, "--design-on-frame", "color"));
    expect(svg.toLowerCase(), "the lockup text takes the frame text color").toContain(`fill="${onFrame}"`);
  });

  test("design: header mark, loading logo, favicon and title come from the branding config", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const markUrl = decodeDotenvQuotedValue(process.env.DESIGN_MARK_URL);
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!markUrl && !title, "logo and title replacement are disabled for this role");
    await signIn(page);
    await open(page, "/app/home#/", MARK);
    if (title) await expect(page).toHaveTitle(new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
    if (markUrl) {
      await expect(page.locator(MARK)).toHaveAttribute("src", markUrl);
      for (const icon of await page.locator("link[rel~='icon']").all()) {
        await expect(icon).toHaveAttribute("href", faviconUrl);
      }
      const html = await (await apiGetOnion(page.request, `${base}/app/home`)).text();
      expect(html, "the loading screen shows the generated mark").toContain(`src="${markUrl}"`);
      for (const url of [markUrl, faviconUrl, decodeDotenvQuotedValue(process.env.DESIGN_LOGIN_URL)]) {
        expect((await apiGetOnion(page.request, url)).ok(), `${url} is published on the CDN`).toBe(true);
      }
    }
  });

  test("design: the native dark mode switch drives the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await signIn(page);
    await open(page, "/app/home#/", HEADER);
    const html = page.locator("html");
    expect(await html.getAttribute("data-design-theme"), "the browser preference decides while dark mode is off").toBeNull();
    const light = await tokenValue(page, "--design-surface-1", "color");
    try {
      await setDarkMode(page, true);
      await gotoOnion(page, "about:blank");
      await open(page, "/app/home#/", HEADER);
      await expect(html).toHaveAttribute("data-design-theme", "dark");
      expect(await tokenValue(page, "--design-surface-1", "color"), "the surface token follows dark mode").not.toBe(light);
      await assertToken(page, "body", "background-color", "--design-surface-1", "page in dark mode");
      await assertToken(page, HEADER, "background-color", "--design-surface-2", "header in dark mode");
      await assertReadable(page, [".euiBreadcrumbWrapper--last .euiBreadcrumb", "main .euiTitle"], "wazuh home in dark mode");
    } finally {
      await setDarkMode(page, null);
    }
    await gotoOnion(page, "about:blank");
    await open(page, "/app/home#/", HEADER);
    await expect.poll(() => html.getAttribute("data-design-theme"), { message: "dark mode off hands the choice back to the browser" }).toBeNull();
  });

  test("design: the sign-in page raises no legacy browser warning", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    skipUnlessServiceDisabled("sso");
    await openLogin(page);
    await page.waitForTimeout(resolveTimeout(3_000));
    await expect(page.getByText("Your browser does not meet the security requirements")).toHaveCount(0);
  });

  test("design: the platform administrator signs in with basic auth while sso is off", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    skipUnlessServiceDisabled("sso");
    await signIn(page);
    await open(page, "/app/security-dashboards-plugin#/users", ".euiTableRow");
    await expect(page.locator(".euiTableRow", { hasText: adminUsername }).locator(".euiBadge")).toHaveText("Current");
  });

  test("design: the platform administrator holds the Wazuh API administrator role", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await open(page, "/app/server-status", ".euiBreadcrumbWrapper--last");
    await expect(page.getByText(/You have no permissions|wazuh-modulesd|wazuh-analysisd/).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    await expect(page.getByText("You have no permissions")).toHaveCount(0);
  });

  test("design: gallery of sign-in, wazuh modules, indexer and dashboard management", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(3_600_000));
    const failures = [];
    try {
      await captureDesignGallery(page, loginViews());
    } catch (error) {
      failures.push(error.message);
    }
    await signIn(page);
    try {
      await captureDesignGallery(page, appViews());
    } catch (error) {
      failures.push(error.message);
    }
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
