const crypto = require("node:crypto");

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
const {
  apiFetchOnion,
  apiGetOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { isSplitRealmOidc, resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "").replace(/\/$/, "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const ssoEnabled = process.env.SSO_SERVICE_ENABLED === "true";
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const symbolUrl = decodeDotenvQuotedValue(process.env.DESIGN_SYMBOL_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const SIGN_IN_FORM = ".auth__wrapper form";
const EMAIL = `${SIGN_IN_FORM} input[type=email]`;
const PASSWORD = `${SIGN_IN_FORM} input[type=password]`;
const SUBMIT = `${SIGN_IN_FORM} .auth__action .button`;
const SIDEBAR = ".sidebar";
const TREE_LINK = ".tree__link";
const HEADER = ".header";
const GRID_ROW = ".grid-view__left .grid-view__row";
const GRID_HEAD = ".grid-view__head";
const OPEN_CONTEXT = ".context:not(.visibility-hidden):visible";
const SHOWCASE = { workspace: "Design showcase", database: "Showcase", table: "Projects" };
const NO_SSO = "with SSO the sign-in form sits behind the identity provider";

test.use({ ignoreHTTPSErrors: true });

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   page: Playwright page on a server-rendered Baserow document; resolves once Vue mounted the app, so a form submit reaches its handler.
 */
async function hydrated(page) {
  await page.waitForFunction(() => [...document.querySelectorAll("body > div")].some((element) => element.__vue_app__), null, {
    timeout: resolveTimeout(30_000),
  });
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the platform administrator, through Keycloak when SSO is on and through the native form with the e-mail address otherwise.
 */
async function signIn(page) {
  if (ssoEnabled) {
    test.skip(isSplitRealmOidc(), "the administrator lives in another realm than the one this app trusts");
    await gotoOnion(page, `${base}/`);
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await gotoOnion(page, `${base}/dashboard`);
  } else {
    await gotoOnion(page, `${base}/login`);
    await hydrated(page);
    const form = await page
      .locator(EMAIL)
      .waitFor({ state: "visible", timeout: resolveTimeout(30_000) })
      .then(() => true)
      .catch(() => false);
    const heading = form ? "" : await page.locator("h1, h2").first().innerText().catch(() => "");
    expect(form, `the sign-in form is missing at ${page.url()} (heading: ${heading})`).toBe(true);
    await expect(page.locator(EMAIL)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(EMAIL).fill(adminEmail);
    await expect(page.locator(PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(PASSWORD).fill(adminPassword);
    await page.locator(SUBMIT).click();
  }
  await expect(page.locator(SIDEBAR)).toBeVisible({ timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   page: signed-in Playwright page.
 *
 * Returns:
 *   The `Authorization` header of a Baserow access token for the administrator.
 */
async function apiHeaders(page) {
  const response = ssoEnabled
    ? await apiGetOnion(page.request, `${base}/api/infinito/sso/token/`, { timeout: resolveTimeout(30_000) })
    : await apiFetchOnion(page.request, `${base}/api/user/token-auth/`, {
        method: "POST",
        data: { email: adminEmail, password: adminPassword },
        timeout: resolveTimeout(30_000),
      });
  expect(response.status(), "the administrator must obtain a Baserow access token").toBe(200);
  return { Authorization: `JWT ${(await response.json()).access_token}` };
}

/**
 * Args:
 *   page: signed-in Playwright page.
 *
 * Returns:
 *   Ids of the showcase workspace, database, table, its grid view and first row, created when missing.
 */
async function seedShowcase(page) {
  const headers = await apiHeaders(page);
  const call = async (method, path, data) => {
    const response = await apiFetchOnion(page.request, `${base}${path}`, {
      method,
      headers,
      data,
      timeout: resolveTimeout(30_000),
    });
    expect(response.ok(), `${method} ${path} answers ${response.status()}`).toBe(true);
    return response.json();
  };
  const workspaces = await call("GET", "/api/workspaces/");
  const workspace =
    workspaces.find((entry) => entry.name === SHOWCASE.workspace) ||
    (await call("POST", "/api/workspaces/", { name: SHOWCASE.workspace }));
  const applications = await call("GET", `/api/applications/workspace/${workspace.id}/`);
  const database =
    applications.find((entry) => entry.name === SHOWCASE.database) ||
    (await call("POST", `/api/applications/workspace/${workspace.id}/`, { type: "database", name: SHOWCASE.database }));
  const tables = await call("GET", `/api/database/tables/database/${database.id}/`);
  const table =
    tables.find((entry) => entry.name === SHOWCASE.table) ||
    (await call("POST", `/api/database/tables/database/${database.id}/`, {
      name: SHOWCASE.table,
      data: [
        ["Name", "Owner", "Status"],
        ["Website relaunch", "Marketing", "Active"],
        ["Annual report", "Finance", "Done"],
        ["Onboarding guide", "People", "Planned"],
        ["Data migration", "IT", "Active"],
        ["Customer survey", "Sales", "Planned"],
      ],
      first_row_header: true,
    }));
  const views = await call("GET", `/api/database/views/table/${table.id}/`);
  const rows = await call("GET", `/api/database/rows/table/${table.id}/?size=1`);
  return { workspace: workspace.id, database: database.id, table: table.id, view: views[0].id, row: rows.results[0].id };
}

/**
 * Args:
 *   page: signed-in Playwright page on a view that may start one of Baserow's guided tours.
 */
async function closeGuidedTours(page) {
  const next = page.locator(".guided-tour-step__foot .button");
  for (let step = 0; step < 20; step += 1) {
    const open = await next
      .first()
      .waitFor({ state: "visible", timeout: resolveTimeout(step === 0 ? 3_000 : 1_500) })
      .then(() => true)
      .catch(() => false);
    if (!open) break;
    await next.first().click();
  }
  await expect(page.locator(".guided-tour-step__container")).toHaveCount(0, { timeout: resolveTimeout(10_000) });
}

/**
 * Args:
 *   page: signed-in Playwright page.
 *
 * Returns:
 *   The seeded showcase ids, after every guided tour on the dashboard and the table view was completed.
 */
async function prepareWorkspace(page) {
  const ids = await seedShowcase(page);
  await gotoOnion(page, `${base}/workspace/${ids.workspace}`);
  await shown(".dashboard__header")(page);
  await closeGuidedTours(page);
  await gotoOnion(page, `${base}/database/${ids.database}/table/${ids.table}`);
  await shown(GRID_ROW)(page);
  await closeGuidedTours(page);
  return ids;
}

function loaded(selector) {
  return async (page) => {
    await shown(selector)(page);
    await expect(page.locator(".skeleton-loading:visible, .skeleton-block:visible, [class*='--skeleton']:visible")).toHaveCount(0, {
      timeout: resolveTimeout(10_000),
    });
  };
}

function opened(selector, trigger) {
  return async (page) => {
    await shown(selector)(page);
    await hydrated(page);
    await page.locator(trigger).first().click();
    await shown(OPEN_CONTEXT)(page);
  };
}

function signInViews() {
  return [
    { name: "sign-in", url: `${base}/login`, prepare: shown(PASSWORD) },
    {
      name: "sign-in-focus",
      url: `${base}/login`,
      prepare: async (page) => {
        await shown(EMAIL)(page);
        await page.locator(EMAIL).focus();
      },
    },
    {
      name: "sign-in-error",
      url: `${base}/login`,
      prepare: async (page) => {
        await hydrated(page);
        await expect(page.locator(EMAIL)).toBeEditable({ timeout: resolveTimeout(10_000) });
        await page.locator(EMAIL).fill(`nobody-${crypto.randomUUID()}@${new URL(base).hostname}`);
        await expect(page.locator(PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
        await page.locator(PASSWORD).fill(crypto.randomUUID());
        await page.locator(SUBMIT).click();
        await shown(".auth__wrapper .alert")(page);
      },
    },
    { name: "forgot-password", url: `${base}/forgot-password`, prepare: shown(SIGN_IN_FORM) },
    { name: "signup", url: `${base}/signup`, prepare: shown(SIGN_IN_FORM) },
  ];
}

function signedInViews(ids) {
  const table = `${base}/database/${ids.database}/table/${ids.table}`;
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: loaded(selector) });
  return [
    view("all-workspaces", "/all-workspaces", ".all-workspaces"),
    view("workspace-dashboard", `/workspace/${ids.workspace}`, ".dashboard__header"),
    view("recently-viewed", "/recently-viewed", ".recently-viewed-page"),
    { name: "grid-view", url: table, prepare: shown(GRID_ROW) },
    {
      name: "grid-cell-selected",
      url: table,
      prepare: async (page) => {
        await shown(GRID_ROW)(page);
        await hydrated(page);
        await page.locator(".grid-view__right .grid-view__row .grid-view__cell").first().click();
        await shown(".grid-view__cell.active")(page);
      },
    },
    {
      name: "field-context",
      url: table,
      prepare: async (page) => {
        await shown(GRID_ROW)(page);
        await hydrated(page);
        await page.locator(".grid-view__right .grid-view__head .grid-view__description").first().hover();
        await page.locator(".grid-view__right .grid-view__head .grid-view__description-icon-trigger").first().click();
        await shown(OPEN_CONTEXT)(page);
      },
    },
    { name: "view-filter", url: table, prepare: opened(GRID_ROW, ".header__filter-link:has-text('Filter')") },
    {
      name: "sidebar-hover",
      url: table,
      prepare: async (page) => {
        await shown(TREE_LINK)(page);
        await page.locator(TREE_LINK).last().hover();
      },
    },
    { name: "workspace-menu", url: table, prepare: opened(GRID_ROW, ".sidebar__workspaces-selector") },
    { name: "create-new", url: `${base}/workspace/${ids.workspace}`, prepare: opened(".dashboard__header", ".sidebar__new") },
    { name: "row-expanded", url: `${table}/${ids.view}/row/${ids.row}`, prepare: shown(".modal__box") },
    view("workspace-members", `/workspace/${ids.workspace}/settings/members`, ".data-table__table"),
    view("admin-dashboard", "/admin/dashboard", ".admin-dashboard__box"),
    view("admin-users", "/admin/users", ".data-table__table"),
    view("admin-workspaces", "/admin/workspaces", ".data-table__table"),
    view("admin-settings", "/admin/settings", ".admin-settings__item"),
    view("admin-health", "/admin/health", ".admin-health__group"),
    view("api-docs", `/api-docs/database/${ids.database}`, ".api-docs__body"),
    view("style-guide", "/style-guide", ".style-guide"),
  ];
}

test("sign-in: a visitor gets the password form instead of the first-administrator signup", async ({ page }) => {
  test.skip(ssoEnabled, NO_SSO);
  await gotoOnion(page, `${base}/login`);
  await shown(PASSWORD)(page);
  expect(new URL(page.url()).pathname, "the sign-in page must not hand a visitor the first-administrator signup").toBe("/login");
});

test("sign-in: the instance settings no longer offer the first-administrator signup", async ({ page }) => {
  await signIn(page);
  const response = await apiGetOnion(page.request, `${base}/api/settings/`, { timeout: resolveTimeout(30_000) });
  expect(response.status()).toBe(200);
  expect((await response.json()).show_admin_signup_page, "the bootstrap must clear show_admin_signup_page").toBe(false);
});

test("sign-in: the administrator signs in with the e-mail address", async ({ page }) => {
  test.skip(ssoEnabled, NO_SSO);
  await signIn(page);
  expect(await apiHeaders(page)).toHaveProperty("Authorization");
});

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "baserow");
});

test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(ssoEnabled, NO_SSO);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/login`);
    await expect(page.locator(PASSWORD), `sign-in form at ${page.url()}`).toBeVisible({ timeout: resolveTimeout(30_000) });
    await assertToken(page, ".auth__body", "background-color", "--design-surface-1", `sign-in ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} .form-input`, "background-color", "--design-surface-2", `sign-in ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} .form-input`, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
    await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
    await page.locator(SUBMIT).hover();
    await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
    await assertToken(page, SUBMIT, "color", "--design-on-primary", `hovered sign-in ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ".auth__body", "baserow sign-in");
  await assertReadable(page, [".auth__head-title", SUBMIT, { selector: ".auth__head-text", optional: true }], "baserow sign-in");
});

test("design: the signed-in interface takes surfaces, dividers, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const ids = await prepareWorkspace(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/database/${ids.database}/table/${ids.table}`);
    await shown(GRID_ROW)(page);
    await assertToken(page, SIDEBAR, "background-color", "--design-surface-3", `sidebar ${mode}`);
    await assertToken(page, SIDEBAR, "border-right-color", "--design-border", `sidebar divider ${mode}`);
    await assertToken(page, HEADER, "background-color", "--design-surface-2", `header ${mode}`);
    await assertToken(page, HEADER, "border-bottom-color", "--design-border", `header divider ${mode}`);
    await assertToken(page, GRID_HEAD, "border-bottom-color", "--design-border", `grid head divider ${mode}`);
    await assertToken(page, ".grid-view__right .grid-view__row .grid-view__column", "border-bottom-color", "--design-border", `grid row divider ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `body text ${mode}`);
    await assertToken(page, TREE_LINK, "color", "--design-text-muted", `navigation ${mode}`);
    await gotoOnion(page, `${base}/workspace/${ids.workspace}/settings/members`);
    await shown(".data-table__table")(page);
    const primary = `.layout__col-2 .button:not(.button--secondary):not(.button--ghost):not([disabled])`;
    await assertToken(page, primary, "background-color", "--design-primary", `primary control ${mode}`);
    await assertToken(page, primary, "color", "--design-on-primary", `primary control ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await gotoOnion(page, `${base}/database/${ids.database}/table/${ids.table}`);
  await shown(GRID_ROW)(page);
  await assertLightAndDark(page, ".grid-view__right .grid-view__row .grid-view__cell", "baserow grid");
  await assertReadable(page, [TREE_LINK, ".sidebar__workspaces-selector", ".grid-view__right .grid-view__row .grid-view__cell"], "baserow shell");
});

test("design: the API documentation keeps its example column readable", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const ids = await seedShowcase(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/api-docs/database/${ids.database}`);
    await shown(".api-docs__example-title")(page);
    const column = await page.locator(".api-docs").first().evaluate((element) => getComputedStyle(element, "::after").backgroundColor);
    expect(column, `the example column ${mode}`).toBe(await tokenValue(page, "--design-surface-3", "background-color"));
    await assertToken(page, ".api-docs__example-title", "color", "--design-text", `example title ${mode}`);
    await assertToken(page, ".api-docs__example", "background-color", "--design-surface-2", `example box ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: sign-in page and sidebar show the generated logo and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl, "logo replacement is disabled for this role");
  if (!ssoEnabled) {
    await gotoOnion(page, `${base}/login`);
    await shown(PASSWORD)(page);
    await expect(page.locator(".auth__logo .logo > img")).toHaveCSS("content", `url("${logoUrl}")`);
    const box = await page.locator(".auth__logo .logo > img").boundingBox();
    expect(box.width, "the sign-in logo keeps a wide lockup").toBeGreaterThan(box.height * 3);
  }
  await signIn(page);
  await gotoOnion(page, `${base}/all-workspaces`);
  await shown(".all-workspaces")(page);
  await expect(page).toHaveTitle(new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  const sidebarLogo = page.locator(".sidebar__logo .logo > img");
  await expect(sidebarLogo).toHaveCSS("content", `url("${logoUrl}")`);
  const box = await sidebarLogo.boundingBox();
  expect(box.width, "the sidebar logo keeps a wide lockup").toBeGreaterThan(box.height * 3);
  await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
  for (const target of [logoUrl, symbolUrl, faviconUrl]) {
    const served = await apiGetOnion(page.request, target, { timeout: resolveTimeout(30_000) });
    expect(`${served.status()} ${served.headers()["content-type"]}`, `${target} must be served as an image`).toMatch(/^200 image\//);
  }
});

test("design: the collapsed sidebar shows the generated symbol", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!symbolUrl, "logo replacement is disabled for this role");
  await signIn(page);
  await gotoOnion(page, `${base}/all-workspaces`);
  const toggle = ".sidebar__foot-link:has(.baserow-icon-sidebar)";
  await shown(toggle)(page);
  await hydrated(page);
  await page.locator(toggle).first().click();
  const symbol = page.locator(".sidebar--collapsed .sidebar__logo .logo > img");
  await expect(symbol).toHaveCSS("content", `url("${symbolUrl}")`, { timeout: resolveTimeout(10_000) });
  const box = await symbol.boundingBox();
  expect(Math.round(box.width), "the collapsed symbol is square").toBe(Math.round(box.height));
});

test("design: gallery of sign-in, workspace, database, settings and administration", async ({ page, browser }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  const failures = [];
  if (!ssoEnabled) {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    await captureDesignGallery(await context.newPage(), signInViews()).catch((error) => failures.push(error.message));
    await context.close();
  }
  await signIn(page);
  const ids = await prepareWorkspace(page);
  await captureDesignGallery(page, signedInViews(ids)).catch((error) => failures.push(error.message));
  expect(failures, failures.join("\n")).toEqual([]);
});
