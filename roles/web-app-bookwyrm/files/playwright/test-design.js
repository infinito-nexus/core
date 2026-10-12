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
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const THEME_FILE = "/css/themes/infinito";
const PROFILE_FORM = 'form[name="edit-profile"]';

test.use({ ignoreHTTPSErrors: true });

const ADMIN_USERNAME = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const ADMIN_PASSWORD = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const BASE = decodeDotenvQuotedValue(process.env.BOOKWYRM_BASE_URL || "").replace(/\/$/, "");
const DESIGN_TITLE = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

async function signIn(page) {
  if (isServiceEnabled("sso")) {
    await gotoOnion(page, `${BASE}/`);
    await performKeycloakLoginForm(page, ADMIN_USERNAME, ADMIN_PASSWORD);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(90_000) }).toContain(BASE);
    return;
  }
  await gotoOnion(page, `${BASE}/login`);
  const form = page.locator('form[name="login-confirm"]');
  await expect(form.locator('input[name="password"]')).toBeEditable({ timeout: resolveTimeout(10_000) });
  await form.locator('input[name="localname"]').fill(ADMIN_USERNAME);
  await form.locator('input[name="password"]').fill(ADMIN_PASSWORD);
  await form.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: resolveTimeout(30_000) });
}

async function openProfile(page) {
  await gotoOnion(page, `${BASE}/preferences/profile`);
  await expect(page.locator(PROFILE_FORM)).toBeVisible({ timeout: resolveTimeout(10_000) });
}

function galleryViews() {
  const ready = (selector, signedIn = true) => async (view) => {
    await view.waitForFunction(
      () => getComputedStyle(document.documentElement).backgroundColor !== "rgba(0, 0, 0, 0)",
      null,
      { timeout: resolveTimeout(10_000) },
    );
    await expect(view.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    if (signedIn) await expect(view).not.toHaveURL(/\/login/);
  };
  const visitor = isServiceEnabled("sso")
    ? []
    : [
        { name: "landing", url: `${BASE}/`, prepare: ready("main h1.title", false) },
        { name: "login", url: `${BASE}/login`, prepare: ready('form[name="login-confirm"]', false) },
        { name: "password-reset", url: `${BASE}/password-reset`, prepare: ready('main input[name="email"]', false) },
      ];
  const member = [
    { name: "feed-home", url: `${BASE}/`, prepare: ready("main .tabs") },
    { name: "discover", url: `${BASE}/discover`, prepare: ready("main h1.title") },
    { name: "lists", url: `${BASE}/list`, prepare: ready("main h1.title") },
    { name: "shelves", url: `${BASE}/user/${ADMIN_USERNAME}/books`, prepare: ready("main h1.title") },
    { name: "search", url: `${BASE}/search?q=design`, prepare: ready('main form[action="/search"]') },
    { name: "notifications", url: `${BASE}/notifications`, prepare: ready("main h1.title") },
    { name: "directory", url: `${BASE}/directory`, prepare: ready("main h1.title") },
    { name: "user-profile", url: `${BASE}/user/${ADMIN_USERNAME}`, prepare: ready("main h1") },
    { name: "about", url: `${BASE}/about`, prepare: ready("main .menu-label") },
    { name: "conduct", url: `${BASE}/conduct`, prepare: ready("main .menu-label") },
    { name: "privacy", url: `${BASE}/privacy`, prepare: ready("main .menu-label") },
    { name: "prefs-profile", url: `${BASE}/preferences/profile`, prepare: ready(PROFILE_FORM) },
    { name: "prefs-security", url: `${BASE}/preferences/security`, prepare: ready("main h1.title") },
    { name: "prefs-password", url: `${BASE}/preferences/password`, prepare: ready('main input[type="password"]') },
    { name: "import", url: `${BASE}/import`, prepare: ready("main h1.title") },
    { name: "admin-dashboard", url: `${BASE}/settings/dashboard`, prepare: ready("main h1.title") },
    { name: "admin-site", url: `${BASE}/settings/site-settings`, prepare: ready("#instance_info") },
    { name: "admin-themes", url: `${BASE}/settings/themes`, prepare: ready("main table") },
    { name: "admin-users", url: `${BASE}/settings/users`, prepare: ready("main table") },
    { name: "admin-federation", url: `${BASE}/settings/federation`, prepare: ready("main h1.title") },
    { name: "admin-invites", url: `${BASE}/settings/invites`, prepare: ready("main h1.title") },
    { name: "admin-announcements", url: `${BASE}/settings/announcements`, prepare: ready("main h1.title") },
    { name: "admin-reports", url: `${BASE}/settings/reports`, prepare: ready("main h1.title") },
    { name: "admin-link-domains", url: `${BASE}/setting/link-domains`, prepare: ready("main h1.title") },
  ];
  return { visitor, member };
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await openProfile(page);
  await assertDesignTokens(page, "bookwyrm");
});

test("design: the corporate theme carries page, primary action, selection and text", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  const blocked = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && msg.text().includes("Content Security Policy")) blocked.push(msg.text().slice(0, 160));
  });
  await signIn(page);
  await openProfile(page);
  expect(blocked, "BookWyrm's own stylesheet, scripts and fonts must pass the CSP").toEqual([]);
  await expect(
    page.locator(`link[rel="stylesheet"][href*="${THEME_FILE}"]`),
    "the site default theme must be the corporate theme",
  ).toHaveCount(1);
  const primary = `${PROFILE_FORM} .button.is-primary`;
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "html", "background-color", "--design-surface-1", `bookwyrm page ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `bookwyrm text ${mode}`);
    await assertToken(page, `${PROFILE_FORM} .box`, "background-color", "--design-surface-2", `bookwyrm panel ${mode}`);
    await assertToken(page, primary, "background-color", "--design-primary", `bookwyrm primary ${mode}`);
    await assertToken(page, primary, "color", "--design-on-primary", `bookwyrm on-primary ${mode}`);
    await assertToken(page, ".menu-list a.is-active", "background-color", "--design-primary", `bookwyrm selected ${mode}`);
    await assertToken(page, ".menu-list a.is-active", "color", "--design-on-primary", `bookwyrm selected text ${mode}`);
    const muted = await tokenValue(page, "--design-text-muted", "color");
    await expect
      .poll(() => page.locator("#tour-search").evaluate((input) => getComputedStyle(input, "::placeholder").color), {
        message: `bookwyrm search placeholder ${mode} must equal --design-text-muted`,
      })
      .toBe(muted);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, `${PROFILE_FORM} .box`, "bookwyrm panel");
  await assertReadable(
    page,
    ["body", `${PROFILE_FORM} .label`, ".menu-list a:not(.is-active)", ".menu-list a.is-active", primary, { selector: "footer a", optional: true }],
    "bookwyrm",
  );
});

test("design: a content divider uses the border token in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${BASE}/settings/users`);
  await expect(page.locator("main table td").first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "main table td", "border-bottom-color", "--design-border", `bookwyrm divider ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: the role closes the setup wizard after it provisioned the administrator", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(isServiceEnabled("sso"), "the oauth2 proxy gates every path when SSO is on");
  const wizard = await apiGetOnion(page.request, `${BASE}/setup/admin`, { maxRedirects: 0 });
  expect(wizard.status(), "a visitor must not be able to create the first administrator").toBe(403);
  const landing = await apiGetOnion(page.request, `${BASE}/`, { maxRedirects: 0 });
  expect(landing.headers().location || "", "the landing page must not send visitors to the setup wizard").not.toContain(
    "/setup",
  );
});

test("design: an upstream theme a user picks stays upstream and the tokens follow it", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const select = page.locator(`${PROFILE_FORM} select[name="theme"]`);
  const save = page.locator(`${PROFILE_FORM} button[type="submit"]`).last();
  await openProfile(page);
  const original = await select.inputValue();
  try {
    await select.selectOption({ label: "BookWyrm Dark" });
    await save.click();
    await openProfile(page);
    await expect(page.locator('link[rel="stylesheet"][href*="/css/themes/bookwyrm-dark"]')).toHaveCount(1);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
  } finally {
    await openProfile(page);
    await select.selectOption(original);
    await save.click();
  }
  await openProfile(page);
  await expect(page.locator(`link[rel="stylesheet"][href*="${THEME_FILE}"]`)).toHaveCount(1);
  await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
});

test("design: BookWyrm shows the configured title and the corporate logo", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await openProfile(page);
  await expect(page).toHaveTitle(new RegExp(` - ${DESIGN_TITLE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  const logo = page.locator(".navbar-brand img.logo");
  await expect(logo).toBeVisible({ timeout: resolveTimeout(10_000) });
  expect(await logo.getAttribute("src"), "the navbar logo must be the uploaded corporate logo").toContain(
    "/logos/infinito-logo-small-",
  );
  await expect.poll(() => logo.evaluate((img) => img.naturalWidth), { message: "the navbar logo must load" }).toBeGreaterThan(0);
  const favicon = page.locator('link[rel="shortcut icon"]');
  expect(await favicon.getAttribute("href"), "the favicon must be the uploaded corporate favicon").toContain(
    "/logos/infinito-favicon-",
  );
});

test("design: gallery of visitor, member and administration views", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(900_000));
  const { visitor, member } = galleryViews();
  const failures = [];
  for (const [signedIn, views] of [
    [false, visitor],
    [true, member],
  ]) {
    if (views.length === 0) continue;
    if (signedIn) await signIn(page);
    try {
      await captureDesignGallery(page, views);
    } catch (error) {
      failures.push(error.message);
    }
  }
  expect(failures).toEqual([]);
});
