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
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const LOCAL_ADMIN = "cmkadmin";
const SHOWCASE_HOST = "design-showcase";
const BUILTIN_LIGHT = "facelift";
const BUILTIN_DARK = "modern-dark";
const MODES = ["light", "dark"];
const MENU_TOGGLE = "#main_menu div.topic li input.button";
const OPEN_NAVIGATION_ENTRY = "#main_menu div.popup_trigger.active";
const TABLE_NOTICE = "h3+div.info, h3+div.success, h2+div.info, h2+div.success";

test.use({ ignoreHTTPSErrors: true });

function localAdminPassword() {
  return decodeDotenvQuotedValue(process.env.CHECKMK_ADMIN_PASSWORD || "");
}

function corporateTheme() {
  return decodeDotenvQuotedValue(process.env.CHECKMK_DESIGN_THEME || "");
}

function guiUrl() {
  return `${normalizeBaseUrl(process.env.CHECKMK_BASE_URL || "").replace(/\/$/, "")}/cmk/check_mk`;
}

function framed(path) {
  return `${guiUrl()}/index.py?start_url=${encodeURIComponent(path)}`;
}

function content(page) {
  return page.frameLocator('iframe[name="main"]');
}

async function contentReady(page) {
  await page.locator("#check_mk_navigation").waitFor({ timeout: resolveTimeout(60_000) });
  await content(page).locator("body").waitFor({ timeout: resolveTimeout(60_000) });
}

async function dashboardReady(page) {
  await contentReady(page);
  await content(page)
    .locator("div.dashlet.hoststats")
    .getByText("Total")
    .first()
    .waitFor({ timeout: resolveTimeout(30_000) })
    .catch(() => {});
}

async function openContent(page, path) {
  await gotoOnion(page, `${guiUrl()}/${path}`);
  await page.locator("body.main").waitFor({ timeout: resolveTimeout(60_000) });
}

async function signIn(page) {
  const gui = guiUrl();
  await gotoOnion(page, `${gui}/index.py`);
  if (isServiceEnabled("sso")) {
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the redirect to the identity provider" })
      .toContain("openid-connect/auth");
    await performKeycloakLoginForm(
      page,
      decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || ""),
      decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || ""),
    );
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: "expected the redirect back to Checkmk" })
      .toContain(new URL(gui).host);
    await gotoOnion(page, `${gui}/index.py`);
  } else {
    await page.locator("#input_user").fill(LOCAL_ADMIN);
    await page.locator("#input_pass").fill(localAdminPassword());
    await page.locator("#_login").click();
  }
  await contentReady(page);
}

async function servedTheme(page) {
  return page.evaluate(() => {
    const link = [...document.querySelectorAll('link[rel="stylesheet"]')]
      .map((element) => element.getAttribute("href") || "")
      .find((href) => /(^|\/)themes\/[^/]+\/theme\.css/.test(href));
    return link ? link.match(/themes\/([^/]+)\/theme\.css/)[1] : "";
  });
}

async function cycleTheme(page) {
  const before = await servedTheme(page);
  await Promise.all([
    page.waitForEvent("load", { timeout: resolveTimeout(90_000) }),
    page.evaluate(() => window.cmk.sidebar.toggle_user_attribute("ajax_ui_theme.py")),
  ]);
  await expect
    .poll(() => servedTheme(page).catch(() => before), {
      timeout: resolveTimeout(60_000),
      message: `the theme switch must leave ${before}`,
    })
    .not.toBe(before);
  await page.locator("#check_mk_navigation").waitFor({ timeout: resolveTimeout(60_000) });
  return servedTheme(page);
}

async function ensureCorporateTheme(page) {
  for (let attempt = 0; attempt < 3 && (await servedTheme(page)) !== corporateTheme(); attempt += 1) {
    await cycleTheme(page);
  }
  expect(await servedTheme(page), "Checkmk must serve the corporate theme").toBe(corporateTheme());
}

async function signInOnCorporateTheme(page) {
  await signIn(page);
  await ensureCorporateTheme(page);
}

async function seedShowcase(page) {
  const api = `${guiUrl()}/api/1.0`;
  const headers = {
    Accept: "application/json",
    Authorization: `Bearer ${LOCAL_ADMIN} ${localAdminPassword()}`,
  };
  const existing = await apiGetOnion(page.request, `${api}/objects/host_config/${SHOWCASE_HOST}`, {
    headers,
    failOnStatusCode: false,
  });
  if (existing.status() === 200) return;
  await apiFetchOnion(page.request, `${api}/domain-types/host_config/collections/all`, {
    method: "POST",
    headers,
    data: { folder: "/", host_name: SHOWCASE_HOST, attributes: { ipaddress: "127.0.0.1" } },
    failOnStatusCode: false,
  });
  await apiFetchOnion(page.request, `${api}/domain-types/activation_run/actions/activate-changes/invoke`, {
    method: "POST",
    headers: { ...headers, "If-Match": "*" },
    data: { redirect: false, force_foreign_changes: true },
    failOnStatusCode: false,
  });
}

async function openMainMenu(page, name) {
  await page.locator("#check_mk_navigation").waitFor({ timeout: resolveTimeout(60_000) });
  const trigger = page.locator(`#popup_trigger_mega_menu_${name}`);
  const opened = () => trigger.evaluate((element) => element.classList.contains("active"));
  await trigger
    .locator("> a")
    .first()
    .evaluate((anchor) => {
      const call = anchor.getAttribute("onclick");
      const parameters = JSON.parse(`[${call.slice(call.indexOf("this,") + 5, call.lastIndexOf(")"))}]`);
      window.cmk.popup_menu.toggle_popup(new MouseEvent("click"), anchor, ...parameters);
    });
  await expect.poll(opened, { timeout: resolveTimeout(10_000), message: `the ${name} menu must open` }).toBe(true);
  const popup = page.locator(`#popup_menu_${name}`);
  await popup.waitFor({ timeout: resolveTimeout(10_000) });
  await expect
    .poll(
      () =>
        popup.evaluate(
          (element) => getComputedStyle(element).opacity === "1" && element.getAnimations().every((a) => a.playState !== "running"),
        ),
      { timeout: resolveTimeout(15_000), message: "the main menu must finish opening" },
    )
    .toBe(true);
}

async function metricBarsDrawn(page) {
  return expect
    .poll(
      async () => {
        await openContent(page, "view.py?view_name=allservices");
        return page.locator("td.perfometer div.title").count();
      },
      { timeout: resolveTimeout(150_000), intervals: [resolveTimeout(5_000)] },
    )
    .toBeGreaterThan(0)
    .then(
      () => true,
      () => false,
    );
}

async function metricBarContrast(page) {
  return page.evaluate(() => {
    const title = document.querySelector("td.perfometer div.title");
    const cells = [...title.closest("td.perfometer").querySelectorAll("td.inner")];
    const bar = cells.sort((a, b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width)[0];
    const luminance = (value) => {
      const [r, g, b] = value
        .match(/[\d.]+/g)
        .slice(0, 3)
        .map((channel) => {
          const share = Number(channel) / 255;
          return share <= 0.04045 ? share / 12.92 : ((share + 0.055) / 1.055) ** 2.4;
        });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const [text, fill] = [luminance(getComputedStyle(title).color), luminance(getComputedStyle(bar).backgroundColor)];
    return (Math.max(text, fill) + 0.05) / (Math.min(text, fill) + 0.05);
  });
}

async function assertDarkSheetRules(page) {
  await gotoOnion(page, `${guiUrl()}/index.py`);
  await contentReady(page);
  await openMainMenu(page, "user");
  await page.emulateMedia({ colorScheme: "light" });
  await expect
    .poll(() => page.locator(OPEN_NAVIGATION_ENTRY).first().evaluate((element) => getComputedStyle(element).backgroundColor), {
      message: "checkmk light: the light upstream sheet gives the open navigation entry no fill, so the theme must add none",
    })
    .toBe("rgba(0, 0, 0, 0)");
  await page.emulateMedia({ colorScheme: "dark" });
  await assertToken(
    page,
    OPEN_NAVIGATION_ENTRY,
    "background-color",
    "--design-surface-active",
    "checkmk dark: open navigation entry",
  );

  await openContent(page, "edit_views.py");
  await assertToken(page, TABLE_NOTICE, "background-color", "--design-surface-3", "checkmk dark: notice under a table heading");
  await page.emulateMedia({ colorScheme: null });
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signInOnCorporateTheme(page);
    await assertDesignTokens(page, "checkmk");
  });

  test("design: the corporate Checkmk theme carries frame, page, primary action and text", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signInOnCorporateTheme(page);
    await expect(
      page.locator('link[rel="stylesheet"][href*="/css/style.css"]'),
      "the palette lives in the Checkmk theme, so no role stylesheet may be injected",
    ).toHaveCount(0);
    await expect(page.locator("html"), "the design script must mark the corporate theme").toHaveAttribute(
      "data-design-palette",
      "",
    );
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(
        page.locator("body"),
        `checkmk ${mode}: the scoped variables of the built-in ${mode} theme must apply`,
      ).toHaveAttribute("data-theme", mode === "dark" ? BUILTIN_DARK : BUILTIN_LIGHT);
      await assertToken(page, "body", "background-color", "--design-surface-3", `checkmk frame ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `checkmk frame ${mode}`);
      await assertToken(
        page,
        "div.snapin div.content",
        "border-bottom-color",
        "--design-border",
        `checkmk sidebar divider ${mode}`,
      );
      await assertToken(page, MENU_TOGGLE, "background-color", "--design-primary", `checkmk menu toggle ${mode}`);
      await assertToken(page, MENU_TOGGLE, "color", "--design-on-primary", `checkmk menu toggle ${mode}`);
    }

    await openContent(page, "dashboard.py");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body.main", "background-color", "--design-surface-1", `checkmk page ${mode}`);
      await assertToken(page, "body.main", "color", "--design-text", `checkmk page ${mode}`);
      await assertToken(page, "div.dashlet_inner", "background-color", "--design-surface-2", `checkmk panel ${mode}`);
      await assertToken(page, "div.dashlet>div.title", "background-color", "--design-surface-3", `checkmk panel head ${mode}`);
      await assertToken(page, "div.cmk_figure g.title rect", "fill", "--design-surface-3", `checkmk figure head ${mode}`);
      await assertToken(page, "input.button.hot", "background-color", "--design-primary", `checkmk primary action ${mode}`);
      await assertToken(page, "input.button.hot", "color", "--design-on-primary", `checkmk primary action ${mode}`);
      await assertToken(
        page,
        "table#page_menu_bar td.menues div.menucontainer",
        "border-bottom-color",
        "--design-border",
        `checkmk page menu divider ${mode}`,
      );
      expect(
        await tokenValue(page, "--ux-theme-0", "background-color"),
        `checkmk ${mode}: the page variable of the Vue components must be the palette page surface`,
      ).toBe(await tokenValue(page, "--design-surface-1", "background-color"));
      expect(
        await tokenValue(page, "--font-color", "color"),
        `checkmk ${mode}: the text variable of the Vue components must be the palette text`,
      ).toBe(await tokenValue(page, "--design-text", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "body.main", "checkmk");
    await assertReadable(
      page,
      ["body.main", "div#top_heading div.titlebar a", "div.dashlet>div.title", "table#page_menu_bar td.menues div.menucontainer"],
      "checkmk",
    );
  });

  test("design: metric bars the app paints itself keep readable text", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(300_000));
    await signInOnCorporateTheme(page);
    await seedShowcase(page);
    const drawn = await metricBarsDrawn(page);
    test.skip(!drawn, "the monitoring core has not drawn a metric bar yet");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openContent(page, "view.py?view_name=allservices");
      expect(
        await metricBarContrast(page),
        `checkmk ${mode}: the value on a metric bar must be readable against the bar the app paints`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  test("design: rules only the dark upstream sheet states follow the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signInOnCorporateTheme(page);
    await assertDarkSheetRules(page);
  });

  test("design: dark mode swaps the navigation icons for their dark variants", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signInOnCorporateTheme(page);
    const icon = page.locator("#popup_trigger_mega_menu_monitoring img:not(.active)").first();
    const rendered = () => icon.evaluate((element) => getComputedStyle(element).content);
    await page.emulateMedia({ colorScheme: "light" });
    await expect.poll(rendered, { message: "light mode must keep the icon the page names" }).toBe("normal");
    await page.emulateMedia({ colorScheme: "dark" });
    await expect
      .poll(rendered, { message: "dark mode must render the dark variant of the navigation icon" })
      .toContain(`themes/${BUILTIN_DARK}/images/`);
    const variant = (await rendered()).match(/url\("([^"]+)"\)/)[1];
    const response = await apiGetOnion(page.request, variant);
    expect(response.status(), `${variant} must be served`).toBe(200);
  });

  test("design: a built-in theme a user picks keeps its own colors and pins the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(360_000));
    await signInOnCorporateTheme(page);
    await page.emulateMedia({ colorScheme: "light" });
    const lightSurface = await tokenValue(page, "--design-surface-3", "background-color");
    const frameSurface = () => page.locator("body").evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(await frameSurface(), "the corporate theme must paint the frame with the palette").toBe(lightSurface);
    try {
      await page.emulateMedia({ colorScheme: "dark" });
      expect(await cycleTheme(page), "the theme switch must offer the built-in light theme next").toBe(BUILTIN_LIGHT);
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
      expect(
        await page.locator("html").getAttribute("data-design-palette"),
        "a built-in theme must not carry the corporate palette mark",
      ).toBeNull();
      expect(
        await tokenValue(page, "--design-surface-3", "background-color"),
        "the built-in light theme must pin the light tokens while the browser prefers dark",
      ).toBe(lightSurface);
      expect(await frameSurface(), "the built-in light theme must keep its own colors").not.toBe(lightSurface);

      await page.emulateMedia({ colorScheme: "light" });
      expect(await cycleTheme(page), "the theme switch must offer the built-in dark theme next").toBe(BUILTIN_DARK);
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
      expect(
        await tokenValue(page, "--design-surface-3", "background-color"),
        "the built-in dark theme must pin the dark tokens while the browser prefers light",
      ).not.toBe(lightSurface);
    } finally {
      await ensureCorporateTheme(page);
    }
    await page.emulateMedia({ colorScheme: "light" });
    await expect(page.locator("html")).toHaveAttribute("data-design-palette", "");
    expect(await frameSurface(), "back on the corporate theme the frame must follow the palette again").toBe(lightSurface);
  });

  test("design: Checkmk shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const iconUrl = decodeDotenvQuotedValue(process.env.DESIGN_ICON_URL || "");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
    test.skip(!iconUrl && !title, "logo and title replacement are disabled for this role");
    const themeUrl = `${guiUrl()}/themes/${corporateTheme()}`;
    await signInOnCorporateTheme(page);

    if (title) {
      await expect(page, "the frame names the configured title before the page it shows").toHaveTitle(
        new RegExp(`^${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}( - |$)`),
      );
    }
    if (iconUrl) {
      const logo = page.locator("#side_header img").first();
      await expect(logo).toHaveAttribute("src", `themes/${corporateTheme()}/images/icon_checkmk_logo.svg`);
      await expect
        .poll(() => logo.evaluate((element) => element.naturalWidth), { message: "the navigation logo must load" })
        .toBeGreaterThan(0);
      const box = await logo.boundingBox();
      expect(Math.abs(box.width - box.height), "the navigation gives its logo a square box").toBeLessThanOrEqual(1);
      for (const [file, source] of [
        ["icon_checkmk_logo.svg", iconUrl],
        ["icon_checkmk_logo_min.svg", iconUrl],
        ["checkmk_logo.svg", logoUrl],
      ]) {
        const served = await apiGetOnion(page.request, `${themeUrl}/images/${file}`);
        const generated = await apiGetOnion(page.request, source);
        expect(served.status(), `Checkmk serves ${file}`).toBe(200);
        expect(generated.status(), `${source} is published on the CDN`).toBe(200);
        expect(await served.text(), `${file} must be the generated corporate logo`).toBe(await generated.text());
      }
      const favicon = await page.locator('link[rel="shortcut icon"]').first().getAttribute("href");
      expect(favicon, "the favicon must come from the corporate theme").toBe(`themes/${corporateTheme()}/images/favicon.ico`);
      const icon = await apiGetOnion(page.request, `${guiUrl()}/${favicon}`);
      expect(icon.status(), "Checkmk serves the corporate favicon").toBe(200);
    }
  });

  test("design: the local sign-in page carries the palette, the wide logo and the title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(isServiceEnabled("sso"), "the identity provider replaces the local sign-in page");
    await gotoOnion(page, `${guiUrl()}/login.py`);
    await page.locator("#input_user").waitFor({ timeout: resolveTimeout(60_000) });
    expect(await servedTheme(page), "a visitor must get the corporate theme").toBe(corporateTheme());
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `checkmk sign-in ${mode}`);
      await assertToken(page, "#login_window", "background-color", "--design-surface-3", `checkmk sign-in ${mode}`);
      await assertToken(page, "#_login", "background-color", "--design-primary", `checkmk sign-in ${mode}`);
      await assertToken(page, "#_login", "color", "--design-on-primary", `checkmk sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["#label_user", "#input_user", "#_login", "#foot"], "checkmk sign-in");
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
    if (title) {
      await expect(page).toHaveTitle(title);
    }
    if (decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "")) {
      const logo = page.locator("#logo");
      await expect(logo).toHaveAttribute("src", `themes/${corporateTheme()}/images/checkmk_logo.svg`);
      await expect
        .poll(() => logo.evaluate((element) => element.naturalWidth), { message: "the sign-in logo must load" })
        .toBeGreaterThan(0);
      const box = await logo.boundingBox();
      expect(box.width, "the sign-in logo box holds a lockup, so it must be wider than high").toBeGreaterThan(box.height * 1.5);
    }
  });

  test("design: the CDN keeps no role stylesheet for a palette that lives in the Checkmk theme", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    const layer = await page.locator('link[href*="/_shared/css/layer.css"]').first().getAttribute("href");
    const stylesheet = new URL("/roles/web-app-checkmk/latest/css/style.css", layer).href;
    const response = await apiGetOnion(page.request, stylesheet);
    expect(response.status(), `${stylesheet} must be absent while the role ships no stylesheet`).toBe(404);
  });

  test("design: gallery of monitoring and setup views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.skip(isServiceEnabled("sso"), "the gallery signs in with the local administrator of an SSO-less deployment");
    test.setTimeout(resolveTimeout(1_800_000));
    const gui = guiUrl();

    await signInOnCorporateTheme(page);
    await seedShowcase(page);
    const ready = async (view) => contentReady(view);

    await captureDesignGallery(page, [
      { name: "start", url: `${gui}/index.py`, prepare: dashboardReady },
      { name: "dashboard-problems", url: framed("dashboard.py?name=simple_problems"), prepare: ready },
      { name: "hosts", url: framed("view.py?view_name=allhosts"), prepare: ready },
      { name: "services", url: framed("view.py?view_name=allservices"), prepare: ready },
      { name: "host-detail", url: framed(`view.py?view_name=host&host=${SHOWCASE_HOST}`), prepare: ready },
      { name: "host-status", url: framed(`view.py?view_name=hoststatus&host=${SHOWCASE_HOST}`), prepare: ready },
      { name: "service-problems", url: framed("view.py?view_name=svcproblems"), prepare: ready },
      { name: "events", url: framed("view.py?view_name=events"), prepare: ready },
      { name: "setup-hosts", url: framed("wato.py?mode=folder"), prepare: ready },
      { name: "setup-host-new", url: framed("wato.py?mode=newhost&folder="), prepare: ready },
      { name: "setup-global-settings", url: framed("wato.py?mode=globalvars"), prepare: ready },
      { name: "setup-users", url: framed("wato.py?mode=users"), prepare: ready },
      { name: "setup-user-edit", url: framed(`wato.py?mode=edit_user&edit=${LOCAL_ADMIN}`), prepare: ready },
      { name: "setup-roles", url: framed("wato.py?mode=roles"), prepare: ready },
      { name: "setup-host-groups", url: framed("wato.py?mode=host_groups"), prepare: ready },
      { name: "setup-time-periods", url: framed("wato.py?mode=timeperiods"), prepare: ready },
      { name: "setup-tags", url: framed("wato.py?mode=tags"), prepare: ready },
      { name: "setup-notifications", url: framed("wato.py?mode=notifications"), prepare: ready },
      { name: "setup-activate-changes", url: framed("wato.py?mode=changelog"), prepare: ready },
      { name: "setup-audit-log", url: framed("wato.py?mode=auditlog"), prepare: ready },
      { name: "user-profile", url: framed("user_profile.py"), prepare: ready },
      { name: "views-list", url: framed("edit_views.py"), prepare: ready },
      { name: "sidebar-elements", url: framed("sidebar_add_snapin.py"), prepare: ready },
      {
        name: "menu-setup",
        url: `${gui}/index.py`,
        prepare: async (view) => {
          await dashboardReady(view);
          await openMainMenu(view, "setup");
        },
      },
      {
        name: "menu-user",
        url: `${gui}/index.py`,
        prepare: async (view) => {
          await dashboardReady(view);
          await openMainMenu(view, "user");
        },
      },
    ]);
  });

  test("design: gallery of the sign-in page", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.skip(isServiceEnabled("sso"), "the identity provider replaces the local sign-in page");
    test.setTimeout(resolveTimeout(300_000));
    await captureDesignGallery(page, [
      {
        name: "login",
        url: `${guiUrl()}/login.py`,
        prepare: async (view) => {
          await view.locator("#input_user").waitFor({ timeout: resolveTimeout(60_000) });
        },
      },
    ]);
  });
};
