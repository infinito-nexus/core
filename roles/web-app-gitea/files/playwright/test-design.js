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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion, performKeycloakLogin } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const SHOWCASE_REPO = "design-showcase";
const UNOFFERED_THEME = "gitea-dark";
const THEMES = {
  auto: decodeDotenvQuotedValue(process.env.GITEA_THEME_AUTO),
  dark: decodeDotenvQuotedValue(process.env.GITEA_THEME_DARK),
  light: decodeDotenvQuotedValue(process.env.GITEA_THEME_LIGHT),
};

function env(name) {
  return decodeDotenvQuotedValue(process.env[name]);
}

function baseUrl() {
  return env("APP_BASE_URL").replace(/\/$/, "");
}

async function signIn(page, base, username, password) {
  await gotoOnion(page, `${base}/user/login`);
  if (isServiceEnabled("sso") && (await page.locator("#kc-form-login").isVisible())) {
    await performKeycloakLogin(page, username, password, env("CANONICAL_DOMAIN"));
    await gotoOnion(page, `${base}/user/login`);
  }
  await page.locator("#user_name").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#password").press("Enter");
  await page.waitForURL((url) => !url.pathname.startsWith("/user/login"), {
    timeout: resolveTimeout(60_000),
  });
}

function basicAuth(username, password) {
  return { Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}` };
}

async function assertTheme(page, theme, label) {
  await expect(page.locator("html"), `${label}: Gitea must render its ${theme} theme`).toHaveAttribute(
    "data-theme",
    theme,
  );
  await expect
    .poll(
      () =>
        page.evaluate(
          (file) =>
            [...document.styleSheets].some((sheet) => {
              if (!(sheet.href || "").includes(file)) return false;
              try {
                return sheet.cssRules.length > 0;
              } catch {
                return false;
              }
            }),
          `/assets/css/theme-${theme}.`,
        ),
      { message: `${label}: the page must load the stylesheet of the ${theme} theme` },
    )
    .toBe(true);
}

async function pickTheme(page, theme) {
  await page.locator("#footer-theme-selector").click();
  await page.locator(`#footer-theme-selector .menu > .item[data-value="${theme}"]`).click();
  await assertTheme(page, theme, "gitea theme selector");
}

function offeredThemes() {
  return decodeDotenvQuotedValue(process.env.GITEA_OFFERED_THEMES).split(",");
}

async function assertTokensFollowTheme(page, lightSurface, label) {
  const dark = await page.evaluate(
    () => getComputedStyle(document.documentElement).getPropertyValue("--is-dark-theme").trim() === "true",
  );
  await expect
    .poll(async () => (await tokenValue(page, "--design-surface-1", "background-color")) !== lightSurface, {
      message: `${label}: the tokens must be dark exactly when the Gitea theme is dark`,
    })
    .toBe(dark);
}

async function seedShowcase(page, base, username, password) {
  const headers = basicAuth(username, password);
  await page.request.post(`${base}/api/v1/user/repos`, {
    headers,
    data: { name: SHOWCASE_REPO, auto_init: true, readme: "Default", description: "Corporate design showcase" },
    failOnStatusCode: false,
  });
  const issues = await page.request.get(`${base}/api/v1/repos/${username}/${SHOWCASE_REPO}/issues?state=all`, {
    headers,
  });
  if ((await issues.json()).length === 0) {
    await page.request.post(`${base}/api/v1/repos/${username}/${SHOWCASE_REPO}/issues`, {
      headers,
      data: {
        title: "Review the corporate design",
        body: "- [ ] Light mode\n- [ ] Dark mode\n- [ ] Mobile layout",
      },
    });
  }
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${baseUrl()}/`);
    await assertDesignTokens(page, "gitea");
  });

  test("design: the corporate Gitea theme carries page, primary color and text", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = baseUrl();
    await gotoOnion(page, `${base}/explore/repos`);
    await assertTheme(page, THEMES.auto, "gitea visitor");
    await expect(
      page.locator('link[rel="stylesheet"][href*="/css/style.css"]'),
      "the palette lives in the Gitea theme, so no role stylesheet may be injected",
    ).toHaveCount(0);
    await expect(
      page.locator('link[href*="/_shared/css/bootstrap.css"]'),
      "the Bootstrap component mapping must stay off for a role that does not opt in",
    ).toHaveCount(0);
    const offered = await (await apiGetOnion(page.request, `${base}/-/web-theme/list`)).json();
    expect(
      offered.results.map((entry) => entry.value).sort(),
      "Gitea must offer exactly the corporate themes and its colour-blind-friendly ones",
    ).toEqual(offeredThemes().sort());

    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `gitea ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `gitea ${mode}`);
      expect(
        await tokenValue(page, "--color-primary", "color"),
        `gitea ${mode}: the primary color of the theme must be the palette link color`,
      ).toBe(await tokenValue(page, "--design-link", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "body", "gitea");
    await assertReadable(
      page,
      ["body", "#navbar a.item.active", 'input[name="q"]', ".ui.small.icon.button", ".page-footer a"],
      "gitea",
    );
  });

  test("design: the theme a visitor picks overrides the browser preference", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = baseUrl();

    await page.emulateMedia({ colorScheme: "light" });
    await gotoOnion(page, `${base}/explore/repos`);
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");

    await pickTheme(page, THEMES.dark);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    expect(
      await tokenValue(page, "--design-surface-1", "background-color"),
      "the corporate dark theme must switch the tokens while the browser prefers light",
    ).not.toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "gitea dark theme");

    await page.emulateMedia({ colorScheme: "dark" });
    await pickTheme(page, THEMES.light);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
    expect(
      await tokenValue(page, "--design-surface-1", "background-color"),
      "the corporate light theme must keep the light tokens while the browser prefers dark",
    ).toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "gitea light theme");

    for (const theme of offeredThemes().filter((name) => !Object.values(THEMES).includes(name))) {
      await pickTheme(page, theme);
      for (const mode of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: mode });
        await assertTokensFollowTheme(page, lightSurface, `gitea ${theme} in a ${mode} browser`);
      }
    }

    await page.context().addCookies([{ name: "gitea_theme", value: UNOFFERED_THEME, url: base }]);
    await gotoOnion(page, `${base}/explore/repos`);
    await assertTheme(page, THEMES.auto, "gitea visitor on a theme that is no longer offered");
  });

  test("design: an account follows its corporate theme and leaves an unoffered one", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = baseUrl();
    const username = env("ADMIN_USERNAME");
    const password = env("ADMIN_PASSWORD");
    const settings = { headers: basicAuth(username, password) };
    const storeTheme = async (theme) => {
      const response = await apiFetchOnion(page.request, `${base}/api/v1/user/settings`, {
        ...settings,
        method: "PATCH",
        data: { theme },
      });
      expect(response.ok(), `storing the theme ${theme} for the account through the API`).toBe(true);
      expect((await response.json()).theme, "the theme the account stores").toBe(theme);
    };

    await signIn(page, base, username, password);
    await page.emulateMedia({ colorScheme: "light" });
    try {
      await storeTheme(THEMES.auto);
      await gotoOnion(page, `${base}/user/settings/appearance`);
      const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");

      await storeTheme(THEMES.dark);
      await gotoOnion(page, `${base}/user/settings/appearance`);
      await assertTheme(page, THEMES.dark, "gitea account");
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
      expect(
        await tokenValue(page, "--design-surface-1", "background-color"),
        "the corporate dark theme of the account must switch the tokens while the browser prefers light",
      ).not.toBe(lightSurface);
      await assertToken(page, "body", "background-color", "--design-surface-1", "gitea account dark theme");
      await assertToken(page, ".ui.primary.button", "background-color", "--design-link", "gitea account dark theme");

      await storeTheme(UNOFFERED_THEME);
      await gotoOnion(page, `${base}/user/settings/appearance`);
      await assertTheme(page, THEMES.auto, "gitea account on a theme that is no longer offered");
    } finally {
      await apiFetchOnion(page.request, `${base}/api/v1/user/settings`, {
        ...settings,
        method: "PATCH",
        data: { theme: THEMES.auto },
      });
    }
  });

  test("design: Gitea serves the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    const base = baseUrl();

    if (logoUrl) {
      const served = await apiGetOnion(page.request, `${base}/assets/img/logo.svg`);
      const generated = await apiGetOnion(page.request, logoUrl);
      expect(served.ok(), "Gitea serves a logo").toBe(true);
      expect(generated.ok(), "the generated logo is published on the CDN").toBe(true);
      expect(await served.text(), "Gitea must serve the generated corporate logo").toBe(await generated.text());
    }
    if (title) {
      await gotoOnion(page, `${base}/`);
      await expect(page).toHaveTitle(title);
    }
  });

  test("design: every Gitea variable the corporate themes assign is declared by the built-in theme", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = baseUrl();
    await gotoOnion(page, `${base}/explore/repos`);
    for (const theme of [THEMES.light, THEMES.dark]) {
      const css = await page.evaluate(
        async (url) => (await fetch(url)).text(),
        `${base}/assets/css/theme-${theme}.css`,
      );
      const builtin = new Set();
      const mapped = new Set();
      for (const [, name, value] of css.matchAll(/(--color-[\w-]+)\s*:\s*([^;}]+)/g)) {
        (value.includes("--design-") ? mapped : builtin).add(name);
      }
      expect(mapped.size, `${theme}: the theme file must carry the corporate mapping`).toBeGreaterThan(0);
      expect(
        [...mapped].filter((name) => !builtin.has(name)),
        `${theme}: variables the mapping assigns although the built-in Gitea theme does not declare them`,
      ).toEqual([]);
    }
  });

  test("design: the CDN keeps no role stylesheet for a palette that lives in the Gitea theme", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${baseUrl()}/explore/repos`);
    const layer = await page.locator('link[href*="/_shared/css/layer.css"]').first().getAttribute("href");
    const stylesheet = new URL("/roles/web-app-gitea/latest/css/style.css", layer).href;
    const response = await apiGetOnion(page.request, stylesheet);
    expect(response.status(), `${stylesheet} must be gone once the role ships no stylesheet`).toBe(404);
  });

  test("design: gallery of public, user and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    const base = baseUrl();
    const username = env("ADMIN_USERNAME");
    const password = env("ADMIN_PASSWORD");

    await captureDesignGallery(page, [
      { name: "start", url: `${base}/` },
      { name: "login", url: `${base}/user/login` },
      { name: "explore-repos", url: `${base}/explore/repos` },
      { name: "explore-users", url: `${base}/explore/users` },
      {
        name: "theme-selector",
        url: `${base}/explore/repos`,
        prepare: async (view) => {
          await view.locator("#footer-theme-selector").click();
          await view.locator("#footer-theme-selector .menu > .item").first().waitFor();
        },
      },
    ]);

    await signIn(page, base, username, password);
    await seedShowcase(page, base, username, password);
    const repo = `${base}/${username}/${SHOWCASE_REPO}`;

    await captureDesignGallery(page, [
      { name: "dashboard", url: `${base}/` },
      { name: "repo-create", url: `${base}/repo/create` },
      { name: "org-create", url: `${base}/org/create` },
      { name: "repo-home", url: repo },
      { name: "repo-file", url: `${repo}/src/branch/main/README.md` },
      { name: "repo-commits", url: `${repo}/commits/branch/main` },
      { name: "repo-branches", url: `${repo}/branches` },
      { name: "repo-issues", url: `${repo}/issues` },
      { name: "issue-detail", url: `${repo}/issues/1` },
      { name: "issue-new", url: `${repo}/issues/new` },
      { name: "repo-pulls", url: `${repo}/pulls` },
      { name: "repo-labels", url: `${repo}/labels` },
      { name: "repo-milestones", url: `${repo}/milestones` },
      { name: "repo-wiki", url: `${repo}/wiki` },
      { name: "repo-settings", url: `${repo}/settings` },
      { name: "user-profile", url: `${base}/${username}` },
      { name: "settings-profile", url: `${base}/user/settings` },
      { name: "settings-account", url: `${base}/user/settings/account` },
      { name: "settings-appearance", url: `${base}/user/settings/appearance` },
      { name: "settings-security", url: `${base}/user/settings/security` },
      { name: "settings-keys", url: `${base}/user/settings/keys` },
      { name: "admin-dashboard", url: `${base}/-/admin` },
      { name: "admin-users", url: `${base}/-/admin/users` },
      { name: "admin-repos", url: `${base}/-/admin/repos` },
      { name: "admin-config", url: `${base}/-/admin/config` },
    ]);
  });
};
