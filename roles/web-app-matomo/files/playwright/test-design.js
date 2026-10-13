const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
} = require("./design");
const { apiFetchOnion, apiGetOnion, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { appBaseUrl, loginAsAdmin, matomoApiToken } = require("./_shared");

const THEME = "InfinitoDesign";
const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const SCOPE = "idSite=1&period=day&date=today";
const ROW = "table.dataTable tbody tr";
const DASHBOARD = "#dashboardWidgetsArea .widget";
const BUSY = ".widgetLoading:visible, .loadingPiwik:visible, .sparklineLoadingSkeleton:visible";
const USER = "#login_form_login";
const SUBMIT = "#login_form_submit";
const SHOWCASE_VISITS = 20;

function base() {
  return appBaseUrl.replace(/\/$/, "");
}

function loginUrl() {
  return `${base()}/index.php?module=Login`;
}

function homeUrl() {
  return `${base()}/index.php?module=CoreHome&action=index&${SCOPE}`;
}

function reportUrl(category, subcategory) {
  const route = `${SCOPE}&category=${category}&subcategory=${subcategory}`;
  return `${base()}/index.php?module=CoreHome&action=index&${route}#?${route}`;
}

function adminUrl(module, action) {
  return `${base()}/index.php?module=${module}&action=${action}&${SCOPE}`;
}

async function shown(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the Matomo superuser the role provisions.
 */
async function signIn(page) {
  await page.context().clearCookies();
  await loginAsAdmin(page);
}

/**
 * Args:
 *   request: Playwright request context; records showcase visits for site 1 through the
 *            tracking API with documentation IPs once per day.
 */
async function seedVisits(request) {
  const api = await apiFetchOnion(request, `${base()}/index.php`, {
    method: "POST",
    form: {
      module: "API",
      method: "VisitsSummary.getVisits",
      format: "json",
      token_auth: matomoApiToken,
      ...Object.fromEntries(new URLSearchParams(SCOPE)),
    },
  });
  expect(api.status(), "VisitsSummary.getVisits must answer").toBe(200);
  const body = await api.json();
  if (Number(body.value) >= SHOWCASE_VISITS) return;
  for (let n = 1; n <= SHOWCASE_VISITS; n += 1) {
    const hit = await apiFetchOnion(request, `${base()}/matomo.php`, {
      method: "POST",
      form: {
        idsite: "1",
        rec: "1",
        url: `${base()}/showcase/page-${n % 5}`,
        action_name: `Showcase page ${n % 5}`,
        cip: `203.0.113.${n}`,
        _id: n.toString(16).padStart(16, "0"),
        token_auth: matomoApiToken,
      },
    });
    expect(hit.status(), "a showcase tracking hit must be accepted").toBeLessThan(400);
  }
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, loginUrl());
  await shown(page, USER);
  await assertDesignTokens(page, "matomo");
});

test("design: the login page takes surface, panel, primary and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await gotoOnion(page, loginUrl());
  await shown(page, USER);
  const panel = page.locator(".loginLayout__secondary");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-surface-2", `login ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `login text ${mode}`);
    if (await panel.isVisible()) {
      await assertToken(page, ".loginLayout__secondary", "background-color", "--design-frame", `login panel ${mode}`);
      await expect(panel, `login panel ${mode}: the upstream gradient is gone`).toHaveCSS("background-image", "none");
    }
    await assertToken(page, SUBMIT, "background-color", "--design-primary", `login button ${mode}`);
    await assertToken(page, SUBMIT, "color", "--design-on-primary", `login button text ${mode}`);
    await assertToken(page, "#login_form_password", "border-bottom-color", "--design-border-strong", `login field underline ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ".loginSection", "matomo login card");
  await page.locator(USER).focus();
  await assertReadable(
    page,
    [SUBMIT, "label[for='login_form_password']", "label[for='login_form_login']", ".loginSection label:not([for])", "#login_form_nav"],
    "matomo login",
  );
});

test("design: the login page and the administrator follow the browser color scheme", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, loginUrl());
  await shown(page, USER);
  await expect(page.locator("html"), "the anonymous login page must follow the browser").toHaveAttribute("data-theme-mode", "auto");
  await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
  await signIn(page);
  await gotoOnion(page, homeUrl());
  await expect(page.locator("html"), "the administrator must follow the browser").toHaveAttribute("data-theme-mode", "auto");
  await page.evaluate(() => document.documentElement.setAttribute("data-theme-mode", "dark"));
  await expect(page.locator("html"), "a dark Matomo theme mode must reach the design tokens").toHaveAttribute("data-design-theme", "dark");
  await page.evaluate(() => document.documentElement.setAttribute("data-theme-mode", "auto"));
  await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
});

test("design: reports take surfaces, dividers and text from the palette", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await seedVisits(request);
  await signIn(page);
  await gotoOnion(page, reportUrl("General_Actions", "General_Pages"));
  await shown(page, ROW);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, `${ROW} td`, "border-bottom-color", "--design-border", `row divider ${mode}`);
    await assertToken(page, "body", "background-color", "--design-surface-1", `report page ${mode}`);
    await assertToken(page, ".card", "background-color", "--design-surface-2", `report card ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ".card", "matomo pages report");
  await assertReadable(
    page,
    [
      "table.dataTable thead th",
      { selector: `${ROW} td.label`, optional: true },
      { selector: "#secondNavBar a", optional: true },
      { selector: ".system.notification .notification-body", optional: true },
      { selector: ".system.notification .close", optional: true },
    ],
    "matomo pages report",
  );
});

test("design: evolution badges, trends and native selects take status and surface tokens", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await seedVisits(request);
  await signIn(page);
  await gotoOnion(page, reportUrl("General_Visitors", "General_Overview"));
  await shown(page, ".evolutionBadge");
  const positive = page.locator(".evolutionBadge--positive");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    if ((await positive.count()) > 0) {
      await assertToken(page, ".evolutionBadge--positive", "color", "--design-success", `positive badge ${mode}`);
      await assertToken(page, ".evolutionBadge--positive", "background-color", "--design-success-subtle", `positive badge ${mode}`);
    }
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(
    page,
    [
      { selector: ".evolutionBadge--positive", optional: true },
      { selector: ".evolutionBadge--negative", optional: true },
      { selector: ".evolutionBadge--neutral", optional: true },
    ],
    "matomo evolution badges",
  );
  await gotoOnion(page, adminUrl("MultiSites", "index"));
  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(15_000) });
  await expect(page.locator("#multisitesAllWebsitesDashboard .matomo-loader:visible")).toHaveCount(0, {
    timeout: resolveTimeout(10_000),
  });
  await shown(page, "#multisitesAllWebsitesDashboard .kpiCardEvolutionTrend");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "#multisitesAllWebsitesDashboard select", "background-color", "--design-surface-2", `evolution select ${mode}`);
    await assertToken(page, "#multisitesAllWebsitesDashboard select", "color", "--design-text", `evolution select text ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(
    page,
    [
      { selector: ".kpiTrendPositive", optional: true },
      { selector: ".kpiTrendNegative", optional: true },
      { selector: ".evolutionTrendPositive", optional: true },
      { selector: ".evolutionTrendNegative", optional: true },
    ],
    "matomo all websites trends",
  );
});

test("design: the theme ships the configured logo and favicon", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, homeUrl());
  const logo = page.locator("#root #logo img").first();
  await expect(logo).toHaveAttribute("src", new RegExp(`plugins/${THEME}/images/logo\\.svg`));
  await expect(logo).toHaveCSS("filter", "none");
  const box = await logo.boundingBox();
  expect(box && box.width > box.height, "the header logo is a wide lockup").toBe(true);
  const svg = await apiGetOnion(request, `${base()}/plugins/${THEME}/images/logo.svg`);
  expect(svg.status(), "the theme logo must be served").toBe(200);
  expect(await svg.text(), "the lockup carries the title next to the logo").toContain("<text");
  const icons = page.locator("link[rel~='icon']");
  expect(await icons.count(), "Matomo renders its favicon links").toBeGreaterThan(0);
  for (const href of await icons.evaluateAll((links) => links.map((link) => link.getAttribute("href")))) {
    expect(href, "every favicon link points into the theme").toContain(`plugins/${THEME}/images/`);
  }
  const favicon = await apiGetOnion(request, `${base()}/plugins/${THEME}/images/favicon.png`);
  expect(favicon.status(), "the theme favicon must be served").toBe(200);
});

/**
 * Args:
 *   name: gallery view name.
 *   url: document URL of the view.
 *   ready: selector that is visible once the view rendered.
 *   busy: optional selector of loading indicators the capture waits up to ten seconds to vanish.
 */
function view(name, url, ready, busy) {
  return {
    name,
    url,
    prepare: async (current) => {
      if (current.url().includes("module=Login") || (await current.locator(USER).count()) > 0) {
        await signIn(current);
        await gotoOnion(current, url);
      }
      await shown(current, ready);
      if (busy) {
        await expect(current.locator(busy)).toHaveCount(0, { timeout: resolveTimeout(10_000) }).catch(() => {});
      }
    },
  };
}

/**
 * Args:
 *   name: gallery view name.
 *   host: view whose page hosts the panel.
 *   trigger: control that opens the panel.
 *   panel: selector of the opened panel.
 */
function opened(name, host, trigger, panel) {
  return {
    name,
    url: host.url,
    prepare: async (current) => {
      await host.prepare(current);
      await current.locator(trigger).first().click({ timeout: resolveTimeout(10_000) });
      await shown(current, panel);
    },
  };
}

function galleryViews() {
  const dashboard = view("dashboard", homeUrl(), DASHBOARD, BUSY);
  return [
    dashboard,
    view(
      "all-websites",
      adminUrl("MultiSites", "index"),
      "#multisitesAllWebsitesDashboard .kpiCardEvolutionTrend",
      `${BUSY}, #multisitesAllWebsitesDashboard .matomo-loader:visible`,
    ),
    view("visitors-overview", reportUrl("General_Visitors", "General_Overview"), ".reporting-page .card", BUSY),
    view("visits-log", reportUrl("General_Visitors", "Live_VisitorLog"), ".dataTableVizVisitorLog, #visitorLogTable", BUSY),
    view("pages", reportUrl("General_Actions", "General_Pages"), ROW, BUSY),
    view("acquisition", reportUrl("Referrers_Referrers", "General_Overview"), ".reporting-page .card", BUSY),
    view("goals-overview", reportUrl("Goals_Goals", "General_Overview"), ".reporting-page .card", BUSY),
    opened("period-selector", dashboard, "#periodString .title", "#periodMore"),
    opened("site-selector", dashboard, ".siteSelector .title", ".siteSelector .dropdown"),
    view("admin-home", adminUrl("CoreAdminHome", "home"), ".card", BUSY),
    view("websites", adminUrl("SitesManager", "index"), ".sitesManagerList .site.card"),
    view("users", adminUrl("UsersManager", "index"), "table tbody tr"),
    view("personal-settings", adminUrl("UsersManager", "userSettings"), ".card"),
    view("general-settings", adminUrl("CoreAdminHome", "generalSettings"), ".card"),
    view("privacy-anonymize", adminUrl("PrivacyManager", "privacySettings"), ".card"),
    view("gdpr-tools", adminUrl("PrivacyManager", "gdprTools"), ".card"),
    view("tracking-code", adminUrl("CoreAdminHome", "trackingCodeGenerator"), ".card"),
    view("system-check", adminUrl("Installation", "systemCheckPage"), "table"),
    view("plugins", adminUrl("CorePluginsAdmin", "plugins"), "table"),
    view("themes", adminUrl("CorePluginsAdmin", "themes"), ".card"),
    view("email-reports", adminUrl("ScheduledReports", "index"), ".card"),
    view("websites-settings", adminUrl("SitesManager", "globalSettings"), ".card"),
    {
      name: "login",
      url: loginUrl(),
      prepare: async (current) => {
        await current.context().clearCookies();
        await gotoOnion(current, loginUrl());
        await shown(current, USER);
      },
    },
  ];
}

test("design: gallery of login, reports and administration", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(900_000));
  await seedVisits(request);
  await signIn(page);
  await captureDesignGallery(page, galleryViews());
});
