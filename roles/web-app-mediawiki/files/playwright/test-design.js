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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.APP_BASE_URL || "").replace(/\/$/, "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const ssoEnabled = process.env.SSO_SERVICE_ENABLED === "true";
const iconUrl = decodeDotenvQuotedValue(process.env.DESIGN_ICON_URL || "");
const wordmarkUrl = decodeDotenvQuotedValue(process.env.DESIGN_WORDMARK_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const NO_SIGN_IN_PAGE = "with sso on PluggableAuth logs every visitor in through Keycloak and local login is off";
const NO_VISITOR = "with sso on PluggableAuth signs every visitor in, so no anonymous page exists";
const SHOWCASE = "Design_showcase";
const CONTENT = "#mw-content-text .mw-parser-output";
const HEADER = ".vector-header";
const PAGE = ".mw-page-container";
const PREFS_TARGET = ".oo-ui-fieldsetLayout:target > .oo-ui-fieldsetLayout-header > .oo-ui-labelElement-label";
const LOGIN_FORM = "#userloginForm";
const LOGIN_SUBMIT = "#wpLoginAttempt";
const READY = 10_000;
const page = (title_, query = "") => `${base}/index.php?title=${encodeURIComponent(title_)}${query}`;

const SHOWCASE_TEXT = [
  "This page was seeded for the corporate design review.",
  "== Overview ==",
  "A [[Main Page|wiki link]], a [[Missing design page|red link]] and an [https://www.mediawiki.org external link].",
  "== Lists ==",
  "* First item\n* Second item\n# Numbered\n# Steps",
  "== Table ==",
  '{| class="wikitable"\n! Name !! State\n|-\n| Alpha || ready\n|-\n| Beta || draft\n|}',
  "== Code ==",
  "<code>echo design</code>\n <pre>preformatted text</pre>",
  "== Quote ==",
  "<blockquote>Quoted text.</blockquote>",
].join("\n\n");

/**
 * Args:
 *   page_: Playwright page whose finite animations must have ended.
 */
async function animationsSettled(page_) {
  await expect
    .poll(
      () =>
        page_.evaluate(() =>
          document
            .getAnimations()
            .some(
              (animation) =>
                animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity,
            ),
        ),
      { message: "every finite animation of the page must have ended", timeout: resolveTimeout(READY) },
    )
    .toBe(false);
}

function shown(selector) {
  return async (page_) => {
    await expect(page_.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY) });
    await animationsSettled(page_);
  };
}

async function pageConfig(page_, key) {
  return page_.evaluate((name) => (window.RLCONF ? window.RLCONF[name] : null), key);
}

async function signedInName(page_) {
  return pageConfig(page_, "wgUserName");
}

/**
 * Args:
 *   page_: Playwright page that ends signed in as the administrator, through Keycloak when sso is on and through Special:UserLogin otherwise.
 */
async function signIn(page_) {
  if (ssoEnabled) {
    await gotoOnion(page_, `${base}/`);
    await performKeycloakLoginForm(page_, adminUsername, adminPassword);
    await gotoOnion(page_, page("Main_Page"));
  } else {
    await gotoOnion(page_, page("Special:UserLogin"));
    await expect(page_.locator("#wpName1")).toBeEditable({ timeout: resolveTimeout(READY) });
    await page_.locator("#wpName1").fill(adminUsername);
    await expect(page_.locator("#wpPassword1")).toBeEditable({ timeout: resolveTimeout(READY) });
    await page_.locator("#wpPassword1").fill(adminPassword);
    await page_.locator(LOGIN_SUBMIT).click();
    await page_.waitForURL((url) => !url.toString().includes("Special:UserLogin"), { timeout: resolveTimeout(READY) });
  }
  await expect.poll(() => signedInName(page_), { message: "the wiki must report a signed-in user", timeout: resolveTimeout(READY) }).toBeTruthy();
}

async function revisionCount(page_) {
  await gotoOnion(page_, page(SHOWCASE, "&action=history"));
  await shown("#mw-content-text")(page_);
  return page_.locator("#pagehistory li").count();
}

/**
 * Args:
 *   page_: signed-in Playwright page; the showcase page gets two revisions through the edit form when it has fewer.
 */
async function seedShowcase(page_) {
  for (let index = await revisionCount(page_); index < 2; index += 1) {
    await gotoOnion(page_, page(SHOWCASE, "&action=edit"));
    await expect(page_.locator("#wpTextbox1")).toBeEditable({ timeout: resolveTimeout(READY) });
    await page_.locator("#wpTextbox1").fill(index === 0 ? SHOWCASE_TEXT : `${SHOWCASE_TEXT}\n\nSecond revision.`);
    await page_.locator("#wpSave").click();
    await expect(page_.locator(`${CONTENT} table.wikitable`)).toBeVisible({ timeout: resolveTimeout(READY) });
  }
  expect(await revisionCount(page_), "the showcase page must have two revisions").toBeGreaterThanOrEqual(2);
}

/**
 * Args:
 *   page_: signed-in Playwright page whose account gets the stored Vector theme.
 *   theme: "day" or "night" to store, null to reset the option to the site default.
 */
async function storeTheme(page_, theme) {
  const api = `${base}/api.php`;
  const tokens = await apiGetOnion(page_.request, `${api}?action=query&meta=tokens&format=json`);
  const token = (await tokens.json()).query.tokens.csrftoken;
  const change = theme ? `vector-theme=${theme}` : "vector-theme";
  const response = await apiFetchOnion(page_.request, api, { method: "POST", form: { action: "options", change, token, format: "json" } });
  expect(await response.json(), `storing vector-theme ${theme}`).toMatchObject({ options: "success" });
}

async function openMainPage(page_) {
  await gotoOnion(page_, page("Main_Page"));
  await shown(CONTENT)(page_);
}

function signInViews() {
  return [
    { name: "sign-in", url: page("Special:UserLogin"), prepare: shown(LOGIN_SUBMIT) },
    {
      name: "sign-in-focus",
      url: page("Special:UserLogin"),
      prepare: async (page_) => {
        await shown("#wpName1")(page_);
        await page_.locator("#wpName1").focus();
      },
    },
    { name: "create-account", url: page("Special:CreateAccount"), prepare: shown("#wpCreateaccount") },
  ];
}

function signedInViews() {
  const view = (name, url, selector) => ({ name, url, prepare: shown(selector) });
  const admin = encodeURIComponent(adminUsername);
  const views = [
    view("main-page", page("Main_Page"), CONTENT),
    view("article", page(SHOWCASE), `${CONTENT} table.wikitable`),
    view("article-edit", page(SHOWCASE, "&action=edit"), "#wpTextbox1"),
    view("article-history", page(SHOWCASE, "&action=history"), "#pagehistory"),
    view("article-diff", page(SHOWCASE, "&diff=cur&oldid=prev"), "table.diff"),
    view("article-info", page(SHOWCASE, "&action=info"), "#mw-content-text table"),
    view("missing-page", page("Missing_design_page"), "#mw-content-text"),
    view("recent-changes", page("Special:RecentChanges"), ".mw-changeslist"),
    view("all-pages", page("Special:AllPages"), ".mw-allpages-body, .mw-allpages-chunk"),
    view("special-pages", page("Special:SpecialPages"), "#mw-content-text .mw-specialpages-list"),
    view("search-results", page("Special:Search", "&search=design&fulltext=1"), ".mw-search-results, .mw-search-nonefound"),
    view("preferences", page("Special:Preferences"), "#mw-prefs-form"),
    view("watchlist", page("Special:Watchlist"), "#mw-content-text"),
    view("contributions", page(`Special:Contributions/${admin}`), "#mw-content-text"),
    view("list-users", page("Special:ListUsers"), "#mw-content-text"),
    view("version", page("Special:Version"), "#mw-version-license"),
    {
      name: "user-menu",
      url: page("Main_Page"),
      prepare: async (page_) => {
        await shown(CONTENT)(page_);
        await page_.locator("#vector-user-links-dropdown-checkbox").click();
        await shown("#vector-user-links-dropdown .vector-dropdown-content")(page_);
      },
    },
    view("new-pages", page("Special:NewPages"), "#mw-content-text"),
    view("preferences-appearance", `${page("Special:Preferences")}#mw-prefsection-rendering`, "#mw-prefsection-rendering"),
    view("log", page("Special:Log"), "#mw-content-text"),
  ];
  if (!ssoEnabled) {
    views.push(
      view("user-rights", page(`Special:UserRights/${admin}`), "#mw-content-text form"),
      view("block", page("Special:Block"), "#mw-content-text form"),
      view("protect", page(SHOWCASE, "&action=protect"), "#mw-Protect-Form"),
      view("delete", page(SHOWCASE, "&action=delete"), "#mw-content-text form"),
      view("move", page(`Special:MovePage/${SHOWCASE}`), "#mw-content-text form"),
    );
  }
  return views;
}

test("design: the platform administrator signs in with the platform password and holds sysop and bureaucrat", async ({ page: page_ }) => {
  test.skip(ssoEnabled, NO_SIGN_IN_PAGE);
  await signIn(page_);
  expect(await signedInName(page_)).toBe(adminUsername.charAt(0).toUpperCase() + adminUsername.slice(1));
  const groups = await pageConfig(page_, "wgUserGroups");
  expect(groups, "the administrator must be a sysop").toContain("sysop");
  expect(groups, "the administrator must be a bureaucrat").toContain("bureaucrat");
});

test("design: corporate tokens apply in light and dark mode", async ({ page: page_ }) => {
  skipUnlessServiceEnabled("design");
  if (ssoEnabled) await signIn(page_);
  await openMainPage(page_);
  await assertDesignTokens(page_, "MediaWiki");
});

test("design: a new visitor follows the browser preference", async ({ page: page_ }) => {
  skipUnlessServiceEnabled("design");
  test.skip(ssoEnabled, NO_VISITOR);
  await gotoOnion(page_, page("Main_Page"));
  await shown(CONTENT)(page_);
  await expect(page_.locator("html")).toHaveClass(/skin-theme-clientpref-os/);
  await expect(page_.locator("html")).not.toHaveAttribute("data-design-theme");
});

test("design: articles take surfaces, links, dividers and text from the palette", async ({ page: page_ }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page_);
  await seedShowcase(page_);
  for (const mode of MODES) {
    await page_.emulateMedia({ colorScheme: mode });
    await gotoOnion(page_, page(SHOWCASE));
    await shown(`${CONTENT} table.wikitable`)(page_);
    await assertToken(page_, PAGE, "background-color", "--design-surface-1", `article ${mode}`);
    await assertToken(page_, CONTENT, "color", "--design-text", `article ${mode}`);
    await assertToken(page_, `${CONTENT} a[href*='Main_Page']`, "color", "--design-link", `article link ${mode}`);
    await assertToken(page_, `${CONTENT} .mw-heading2`, "border-bottom-color", "--design-border", `heading divider ${mode}`);
    await assertToken(page_, `${CONTENT} table.wikitable th`, "background-color", "--design-surface-3", `table head ${mode}`);
    await assertToken(page_, `${CONTENT} table.wikitable td`, "border-top-color", "--design-border", `table divider ${mode}`);
  }
  for (const mode of MODES) {
    await page_.emulateMedia({ colorScheme: mode });
    await gotoOnion(page_, page("Special:RecentChanges"));
    await shown("fieldset.rcoptions")(page_);
    await assertToken(page_, "fieldset.rcoptions", "border-top-color", "--design-border", `options box ${mode}`);
    await gotoOnion(page_, `${page("Special:Preferences")}#mw-prefsection-rendering`);
    await shown(PREFS_TARGET)(page_);
    await assertToken(page_, PREFS_TARGET, "outline-color", "--design-primary-50", `preferences section target ${mode}`);
  }
  await gotoOnion(page_, page(SHOWCASE));
  await shown(`${CONTENT} table.wikitable`)(page_);
  await page_.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page_, CONTENT, "MediaWiki article");
  await assertReadable(page_, [CONTENT, `${CONTENT} h2`, `${CONTENT} table.wikitable td`, `${CONTENT} a[href*='Main_Page']`, { selector: `${CONTENT} a.new`, optional: true }], "MediaWiki article");
});

test("design: the primary action takes its fill and text from the palette", async ({ page: page_ }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page_);
  await seedShowcase(page_);
  for (const mode of MODES) {
    await page_.emulateMedia({ colorScheme: mode });
    await gotoOnion(page_, page(SHOWCASE, "&action=edit"));
    await shown("#wpSave")(page_);
    await assertToken(page_, "#wpSave", "background-color", "--design-primary", `save ${mode}`);
    await assertToken(page_, "#wpSave", "color", "--design-on-primary", `save ${mode}`);
    await assertToken(page_, "#wpTextbox1", "border-top-color", "--design-border-strong", `editor ${mode}`);
    await page_.locator("#wpSave").hover();
    await assertToken(page_, "#wpSave", "background-color", "--design-primary-hover", `hovered save ${mode}`);
  }
  await page_.emulateMedia({ colorScheme: null });
});

test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page: page_ }) => {
  skipUnlessServiceEnabled("design");
  test.skip(ssoEnabled, NO_SIGN_IN_PAGE);
  for (const mode of MODES) {
    await page_.emulateMedia({ colorScheme: mode });
    await gotoOnion(page_, page("Special:UserLogin"));
    await shown(LOGIN_SUBMIT)(page_);
    await assertToken(page_, PAGE, "background-color", "--design-surface-1", `sign-in ${mode}`);
    await assertToken(page_, LOGIN_SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page_, LOGIN_SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
    await assertToken(page_, "#wpPassword1", "border-top-color", "--design-border-strong", `sign-in ${mode}`);
  }
  await page_.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page_, LOGIN_FORM, "MediaWiki sign-in");
  await assertReadable(page_, [`${LOGIN_FORM} label`, "#firstHeading"], "MediaWiki sign-in");
});

test("design: a Vector theme stored for the account is respected and mirrored", async ({ page: page_ }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page_);
  const html = page_.locator("html");
  const surface = () => tokenValue(page_, "--design-surface-1", "background-color");
  try {
    await page_.emulateMedia({ colorScheme: "light" });
    await openMainPage(page_);
    await expect(html, "an account without an own choice follows the browser").toHaveClass(/skin-theme-clientpref-os/);
    await expect(html).not.toHaveAttribute("data-design-theme");
    const light = await surface();
    await storeTheme(page_, "night");
    await openMainPage(page_);
    await expect(html).toHaveClass(/skin-theme-clientpref-night/);
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(await surface(), "night stored in Vector must switch the tokens while the browser prefers light").not.toBe(light);
    await assertToken(page_, PAGE, "background-color", "--design-surface-1", "night stored in Vector");
    await page_.emulateMedia({ colorScheme: "dark" });
    await storeTheme(page_, "day");
    await openMainPage(page_);
    await expect(html).toHaveAttribute("data-design-theme", "light");
    expect(await surface(), "day stored in Vector must keep the light tokens while the browser prefers dark").toBe(light);
  } finally {
    await storeTheme(page_, null);
    await page_.emulateMedia({ colorScheme: null });
  }
});

test("design: the header shows the generated logo and wordmark and the configured title", async ({ page: page_ }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!iconUrl && !title, "logo and title replacement are disabled for this role");
  if (ssoEnabled) await signIn(page_);
  await gotoOnion(page_, page("Main_Page"));
  await shown(HEADER)(page_);
  if (title) await expect.poll(() => page_.title()).toContain(title);
  if (iconUrl) {
    await expect(page_.locator(".mw-logo-icon")).toHaveAttribute("src", iconUrl);
    await expect(page_.locator("img.mw-logo-wordmark")).toHaveAttribute("src", wordmarkUrl);
    const box = await page_.locator("img.mw-logo-wordmark").boundingBox();
    expect(box.width, "the wordmark must be wider than high").toBeGreaterThan(box.height);
    await expect(page_.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
  }
});

test("design: gallery of articles, editing, special pages, preferences, administration and menus", async ({ page: page_ }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  let signInFailure = null;
  if (!ssoEnabled) {
    await captureDesignGallery(page_, signInViews()).catch((error) => {
      signInFailure = error;
    });
  }
  await signIn(page_);
  await seedShowcase(page_);
  await captureDesignGallery(page_, signedInViews());
  if (signInFailure) throw signInFailure;
});
