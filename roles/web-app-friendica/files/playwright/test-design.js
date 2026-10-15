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
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };
const VISITOR_PAGE = "/friendica";
const TOPBAR = "#topbar-first";
const VISITOR_NAV = "nav.navbar";
const CONTENT = "section > .generic-page-wrapper";
const USERNAME = "#login-form input[name='username']";
const SIGN_IN_SUBMIT = "#login-submit-button";
const REGISTER = "#register-link";
const SETTINGS_SUBMIT = "#content button.btn-primary[name='password-submit']";
const ADMIN = ".adminpage";
const ROW_CELL = "table.table > tbody > tr > td";
const SCHEME_PANEL = "#theme-settings-content";
const UPLOAD_PANEL = "#admin-settings-upload-collapse";
const IMAGE_SIZE = "#id_maximagesize";
const ACCOUNT_MENU = "#offcanvasUsermenu";
const LIGHTBOX = ".fancybox-container.fancybox-is-open";
const LIGHTBOX_CAPTION = "Infinito design showcase image";
const SHOWCASE = "Infinito design showcase post";
const CHART_FILLS = [
  "--design-primary",
  "--design-info",
  "--design-success",
  "--design-warning",
  "--design-danger",
  "--design-primary-300",
  "--design-primary-700",
  "--design-neutral-500",
];

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Args:
 *   shared: the role's _shared.js module.
 *   page: Playwright page that ends signed in as the administrator, through Keycloak first when sso is on.
 */
async function signIn(shared, page) {
  await shared.pickLoginPath()(page, shared.env.adminUsername, shared.env.adminPassword);
}

/**
 * Args:
 *   page: page whose `selector` element finished an opening transition or animation.
 *   selector: the panel to wait for.
 */
async function settled(page, selector) {
  const panel = page.locator(selector).first();
  await expect(panel).toBeVisible({ timeout: resolveTimeout(10_000) });
  await expect
    .poll(() => panel.evaluate((element) => element.getAnimations({ subtree: true }).length + (getComputedStyle(element).opacity === "1" ? 0 : 1)), {
      timeout: resolveTimeout(10_000),
    })
    .toBe(0);
}

/**
 * Args:
 *   page: page with a Bootstrap accordion; opens `panel` and waits until its collapse ended.
 *   panel: selector of the `.collapse` element.
 */
async function openPanel(page, panel) {
  await page.evaluate((selector) => window.jQuery(selector).collapse("show"), panel);
  await expect(page.locator(panel)).toHaveClass(/\bin\b/, { timeout: resolveTimeout(10_000) });
  await expect(page.locator(`${panel}.collapsing`)).toHaveCount(0, { timeout: resolveTimeout(10_000) });
}

/**
 * Args:
 *   page: page on /settings/display; opens the theme accordion and waits until its collapse ended.
 */
async function openSchemePanel(page) {
  await shown("#settings-form")(page);
  await openPanel(page, SCHEME_PANEL);
}

/**
 * Args:
 *   page: signed-in page on /settings/display with the theme accordion open; posts the form with frio_scheme as the only frio field.
 */
async function postDisplaySettings(page) {
  await page
    .locator("#settings-form")
    .evaluate((form) => form.querySelectorAll("[name^='frio_']:not([name='frio_scheme'])").forEach((field) => field.remove()));
  await Promise.all([
    page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/settings/display"), {
      timeout: resolveTimeout(10_000),
    }),
    page.locator("button[name='frio-settings-submit']").first().click({ timeout: resolveTimeout(10_000) }),
  ]);
}

/**
 * Args:
 *   page: signed-in page.
 *   url: absolute URL of /settings/display.
 *   scheme: value of the frio scheme select the account ends with.
 */
async function saveScheme(page, url, scheme) {
  // Friendica stores no frio field while the posted theme differs from the account's stored one (src/Module/Settings/Display.php:194); a fresh account stores none, so a first post pins the theme.
  await gotoOnion(page, url);
  await openSchemePanel(page);
  await postDisplaySettings(page);
  await gotoOnion(page, url);
  await openSchemePanel(page);
  await page.locator("#id_frio_scheme").selectOption(scheme);
  await postDisplaySettings(page);
  await gotoOnion(page, url);
  await openSchemePanel(page);
  await expect(page.locator("#id_frio_scheme"), `the account stores the ${scheme} scheme`).toHaveValue(scheme, { timeout: resolveTimeout(10_000) });
}

/**
 * Args:
 *   shared: the role's _shared.js module.
 *   page: signed-in page; posts one public showcase status on the administrator's wall when none exists.
 */
async function seedShowcase(shared, page) {
  const base = shared.trimmedBaseUrl();
  const wall = `${base}/profile/${shared.env.adminUsername}/conversations`;
  await gotoOnion(page, wall);
  await shown("#content")(page);
  if ((await page.getByText(SHOWCASE).count()) > 0) return;
  await gotoOnion(page, `${base}/compose`);
  const body = page.locator("textarea[name='body']").first();
  await expect(body).toBeEditable({ timeout: resolveTimeout(10_000) });
  await body.fill(SHOWCASE);
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator("form.comment-edit-form button[type='submit'][name='submit']").first().click({ timeout: resolveTimeout(10_000) }),
  ]);
  await gotoOnion(page, wall);
  await expect(page.getByText(SHOWCASE).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
}

/**
 * Args:
 *   page: signed-in frio page; adds a post image link in the markup of view/templates/content/image/single.tpl
 *     pointing at Friendica's own touch icon, clicks it and waits until fancybox settled with its controls shown.
 *   base: Friendica base URL without a trailing slash.
 */
async function openLightbox(page, base) {
  await shown("#content")(page);
  await page.evaluate(
    ([href, caption]) => {
      const link = document.createElement("a");
      link.id = "design-lightbox-probe";
      link.dataset.fancybox = "design-lightbox-probe";
      link.href = href;
      const image = document.createElement("img");
      image.src = href;
      image.alt = caption;
      image.title = caption;
      image.className = "has-alt-description";
      image.width = 48;
      link.appendChild(image);
      document.querySelector("#content").prepend(link);
    },
    [`${base}/images/friendica-192.png`, LIGHTBOX_CAPTION],
  );
  await page.locator("#design-lightbox-probe").click({ timeout: resolveTimeout(10_000) });
  await expect(page.locator(`${LIGHTBOX} .fancybox-image`)).toBeVisible({ timeout: resolveTimeout(10_000) });
  await page.mouse.move(8, 8);
  await page.mouse.move(16, 16);
  await expect(page.locator(".fancybox-caption")).toHaveCSS("opacity", "1", { timeout: resolveTimeout(10_000) });
  await settled(page, LIGHTBOX);
}

/**
 * Args:
 *   page: signed-in frio page at a phone viewport; opens the off-canvas account menu and waits until it slid in.
 */
async function openAccountMenu(page) {
  await shown(TOPBAR)(page);
  await page.locator(".offcanvas-right-toggle").first().click({ timeout: resolveTimeout(10_000) });
  await expect(page.locator("body")).toHaveClass(/\boffcanvas-right-active\b/, { timeout: resolveTimeout(10_000) });
  await settled(page, ACCOUNT_MENU);
}

/**
 * Args:
 *   page: page on /admin/federation; returns the colors of every federation chart the page built.
 */
function chartColors(page) {
  return page.evaluate(() => {
    const charts = Object.values((window.Chart && window.Chart.instances) || {}).filter(
      (chart) => chart.canvas.id === "FederationChart" || chart.canvas.classList.contains("federation-network-graph"),
    );
    const flat = (key) => [...new Set(charts.flatMap((chart) => [].concat(chart.data.datasets[0][key])))];
    return { charts: charts.length, fills: flat("backgroundColor"), hovers: flat("hoverBackgroundColor"), borders: flat("borderColor") };
  });
}

/**
 * Args:
 *   page: page on /admin/federation; fills the first slot when no platform has servers, then returns the
 *     canvas pixel in the middle of the first drawn segment and the fill the chart holds for it.
 */
function chartPixel(page) {
  return page.evaluate(() => {
    const chart = Object.values(window.Chart.instances).find((candidate) => candidate.canvas.id === "FederationChart");
    const dataset = chart.data.datasets[0];
    if (!dataset.data.some((value) => value > 0)) {
      dataset.data[0] = 1;
      chart.update(0);
    }
    const index = dataset.data.findIndex((value) => value > 0);
    const arc = chart.getDatasetMeta(0).data[index]._model;
    const angle = (arc.startAngle + arc.endAngle) / 2;
    const radius = (arc.innerRadius + arc.outerRadius) / 2;
    const ratio = chart.currentDevicePixelRatio || 1;
    const x = Math.round((arc.x + radius * Math.cos(angle)) * ratio);
    const y = Math.round((arc.y + radius * Math.sin(angle)) * ratio);
    const [r, g, b] = chart.canvas.getContext("2d").getImageData(x, y, 1, 1).data;
    return { pixel: `rgb(${r}, ${g}, ${b})`, fill: dataset.backgroundColor[index] };
  });
}

exports.register = function (shared) {
  const base = () => shared.trimmedBaseUrl();

  test("design: the administrator signs in with the password the role provisions", async ({ page }) => {
    await signIn(shared, page);
    await expect(page.locator(TOPBAR)).toBeVisible({ timeout: resolveTimeout(10_000) });
    await gotoOnion(page, `${base()}/admin`);
    await expect(page.locator(ADMIN), "the provisioned administrator holds admin rights").toBeVisible({ timeout: resolveTimeout(10_000) });
  });

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base()}${VISITOR_PAGE}`);
    await shown(VISITOR_NAV)(page);
    await assertDesignTokens(page, "friendica");
  });

  test("design: the sign-in page takes frame, surface, primary action and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(shared.isServiceEnabled("sso"), "oauth2-proxy gates /login; the signed-in tests cover the palette");
    await gotoOnion(page, `${base()}/login`);
    await shown(SIGN_IN_SUBMIT)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in page ${mode}`);
      await expect(page.locator("body"), `the backdrop image and gradient are dropped in ${mode} mode`).toHaveCSS("background-image", "none");
      await assertToken(page, VISITOR_NAV, "background-color", "--design-frame", `visitor navbar ${mode}`);
      await assertToken(page, USERNAME, "background-color", "--design-surface-2", `username field ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary", `sign-in button ${mode}`);
      await assertToken(page, SIGN_IN_SUBMIT, "color", "--design-on-primary", `sign-in button text ${mode}`);
      await page.locator(SIGN_IN_SUBMIT).hover();
      await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in button ${mode}`);
      await page.mouse.move(0, 0);
      if (await page.locator(REGISTER).isVisible()) {
        await assertToken(page, REGISTER, "background-color", "--design-success", `create-account button ${mode}`);
        await assertToken(page, REGISTER, "color", "--design-on-success", `create-account button text ${mode}`);
      }
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, USERNAME, "friendica sign-in");
    await assertReadable(page, [SIGN_IN_SUBMIT, "#login-form label", { selector: "#lost-password-link", optional: true }], "friendica sign-in");
  });

  test("design: the signed-in shell takes frame, surfaces, dividers and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/moderation/users`);
    await shown(ROW_CELL)(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, TOPBAR, "background-color", "--design-frame", `top bar ${mode}`);
      await assertToken(page, `${TOPBAR} .nav > li > a`, "color", "--design-on-frame", `top bar icon ${mode}`);
      await assertToken(page, "#topbar-second", "background-color", "--design-surface-2", `second bar ${mode}`);
      await assertToken(page, ADMIN, "background-color", "--design-surface-2", `content panel ${mode}`);
      await assertToken(page, ROW_CELL, "border-top-color", "--design-border", `row divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ADMIN, "friendica moderation list");
    await assertReadable(page, [`${ADMIN} h1`, ROW_CELL, { selector: "aside .widget li a", optional: true }], "friendica shell");
  });

  test("design: the administration summary, site settings and addon list take panels, fields and actions from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/admin`);
    await shown("#adminpage-summary")(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#adminpage-summary", "background-color", "--design-surface-2", `summary panel ${mode}`);
      await assertToken(page, "#admin-summary-queues td", "border-top-color", "--design-border", `summary divider ${mode}`);
      await assertToken(page, "#adminpage-summary a.btn.btn-primary", "background-color", "--design-primary", `summary action ${mode}`);
      await assertToken(page, "#adminpage-summary a.btn.btn-primary", "color", "--design-on-primary", `summary action text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#adminpage-summary", "friendica administration summary");
    await assertReadable(page, ["#adminpage-summary h1", "#admin-summary-queues td", { selector: "#admin-warning-message-wrapper", optional: true }], "friendica administration summary");

    await gotoOnion(page, `${base()}/admin/site`);
    await shown(`${ADMIN} form`)(page);
    await openPanel(page, UPLOAD_PANEL);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, `${UPLOAD_PANEL} .form-control:not(${IMAGE_SIZE})`, "background-color", "--design-surface-2", `site field ${mode}`);
      await assertToken(page, `${UPLOAD_PANEL} .form-control:not(${IMAGE_SIZE})`, "border-top-color", "--design-border-strong", `site field border ${mode}`);
      await assertToken(page, IMAGE_SIZE, "background-color", "--design-success-subtle", `valid image size field ${mode}`);
      await assertToken(page, `${UPLOAD_PANEL} input.btn.btn-primary[name='page_site']`, "background-color", "--design-primary", `site save ${mode}`);
      await assertToken(page, `${UPLOAD_PANEL} input.btn.btn-primary[name='page_site']`, "color", "--design-on-primary", `site save text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["#admin-settings .accordion-toggle", `${UPLOAD_PANEL} label`, IMAGE_SIZE], "friendica site settings");

    await gotoOnion(page, `${base()}/admin/addons`);
    await shown("#addonslist")(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#adminpage", "background-color", "--design-surface-2", `addon page ${mode}`);
      await assertToken(page, "#adminpage a.btn.btn-primary", "background-color", "--design-primary", `addon reload ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["#addonslist li.addon .name", "#addonslist li.addon .desc"], "friendica addon list");
  });

  test("design: the federation charts draw their segments in palette fills", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/admin/federation`);
    await shown("#FederationChart")(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const fills = [];
      for (const token of CHART_FILLS) fills.push(await tokenValue(page, token, "color"));
      const expected = {
        hovers: [await tokenValue(page, "--design-primary-active", "color")],
        borders: [await tokenValue(page, "--design-surface-2", "color")],
        stray: [],
      };
      await expect
        .poll(
          async () => {
            const seen = await chartColors(page);
            if (seen.charts === 0) return { charts: 0 };
            return { hovers: seen.hovers, borders: seen.borders, stray: seen.fills.filter((color) => !fills.includes(color)) };
          },
          { timeout: resolveTimeout(10_000), message: `federation chart colors in ${mode} mode` },
        )
        .toEqual(expected);
      const sample = await chartPixel(page);
      expect(fills, `the chart fill in ${mode} mode is a palette fill`).toContain(sample.fill);
      expect(sample.pixel, `the drawn segment in ${mode} mode`).toBe(sample.fill);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the image lightbox takes its backdrop, controls and caption from the frame tokens", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/network`);
    await openLightbox(page, base());
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".fancybox-bg", "background-color", "--design-frame", `lightbox backdrop ${mode}`);
      await assertToken(page, ".fancybox-close-small", "color", "--design-on-frame", `lightbox close control ${mode}`);
      await assertToken(page, ".fancybox-toolbar .fancybox-button:not([disabled])", "color", "--design-on-frame", `lightbox toolbar control ${mode}`);      await assertToken(page, ".fancybox-caption", "color", "--design-on-frame", `lightbox caption ${mode}`);
      const frame = (await tokenValue(page, "--design-frame", "color")).replace(/^rgb\((.*)\)$/, "$1");
      await expect(page.locator(".fancybox-caption"), `the caption shade derives from the frame in ${mode} mode`).toHaveCSS(
        "background-image",
        new RegExp(`^linear-gradient\\((0deg|to top), rgba\\(${escapeRegExp(frame)}, 0\\.85\\) 0(px|%)`),
      );
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the mobile account menu is one frame panel with frame dividers", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(MOBILE);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/network`);
    await openAccountMenu(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ACCOUNT_MENU, "background-color", "--design-frame", `account menu panel ${mode}`);
      await assertToken(page, `${ACCOUNT_MENU} li.divider`, "background-color", "--design-frame-active", `account menu divider ${mode}`);
      await assertToken(page, `${ACCOUNT_MENU} li.list-group-item a`, "color", "--design-on-frame", `account menu entry ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${ACCOUNT_MENU} li.list-group-item a`, `${ACCOUNT_MENU} li.list-group-item`], "friendica account menu");
  });

  test("design: the calendar marks today with a palette surface in light and dark mode", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/calendar`);
    await shown(".fc-unthemed td.fc-today")(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".fc-unthemed td.fc-today", "background-color", "--design-surface-active", `today cell ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: frio carries the provisioned light palette as its site default", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/network`);
    await shown(TOPBAR)(page);
    await page.emulateMedia({ colorScheme: "light" });
    const meta = await page.locator("meta[name='theme-color']").first().getAttribute("content");
    const asColor = await page.evaluate((value) => {
      const probe = document.createElement("span");
      probe.style.color = value;
      document.body.appendChild(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    }, meta);
    expect(asColor, "frio.nav_bg must hold the light frame color").toBe(await tokenValue(page, "--design-frame", "color"));
    await expect(page.locator("html"), "the site default scheme leaves the mode to the browser").not.toHaveAttribute("data-design-theme", /.+/);
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: every focus stop in the top bar draws its indicator in the frame text color", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/network`);
    await shown(TOPBAR)(page);
    const expected = await tokenValue(page, "--design-on-frame", "outline-color");
    await page.locator(`${TOPBAR} a, ${TOPBAR} button`).first().focus();
    const seen = [];
    for (let step = 0; step < 30 && seen.length < 6; step += 1) {
      const stop = await page.evaluate((bar) => {
        const element = document.activeElement;
        if (!element || !element.closest(bar) || element.closest(".dropdown-menu")) return null;
        const style = getComputedStyle(element);
        return { style: style.outlineStyle, color: style.outlineColor, name: element.id || element.className };
      }, TOPBAR);
      if (stop) seen.push(stop);
      await page.keyboard.press("Tab");
    }
    expect(seen.length, "the top bar must hold keyboard focus stops").toBeGreaterThan(0);
    for (const stop of seen) {
      expect(stop.style, `focus indicator style of ${stop.name}`).not.toBe("none");
      expect(stop.color, `focus indicator of ${stop.name}`).toBe(expected);
    }
  });

  test("design: navigation shows the generated logos and favicon", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
    const brandUrl = decodeDotenvQuotedValue(process.env.DESIGN_BRAND_URL || "");
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
    test.skip(!logoUrl, "logo replacement is disabled for this role");
    await page.setViewportSize(DESKTOP);
    await gotoOnion(page, `${base()}${VISITOR_PAGE}`);
    await shown(VISITOR_NAV)(page);
    const brand = page.locator(".navbar-brand #logo-img").first();
    await expect(brand).toHaveCSS("background-image", `url("${brandUrl}")`);
    await expect(page.locator("#navbar-brand-text").first()).toBeHidden();
    const box = await brand.boundingBox();
    expect(box, "the visitor brand box renders").not.toBeNull();
    expect(box.width, "the visitor brand box carries a wide lockup").toBeGreaterThan(box.height * 1.5);
    await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    await signIn(shared, page);
    await gotoOnion(page, `${base()}/network`);
    await shown(TOPBAR)(page);
    await expect(page.locator("header #banner #logo-img").first()).toHaveCSS("background-image", `url("${logoUrl}")`);
  });

  test("design: the page title ends with the configured design title", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
    test.skip(!title, "the role configures no design title");
    await gotoOnion(page, `${base()}${VISITOR_PAGE}`);
    await shown(VISITOR_NAV)(page);
    await expect(page).toHaveTitle(new RegExp(`\\| ${escapeRegExp(title)}$`));
  });

  test("design: picking the dark frio scheme keeps the palette and switches to dark tokens", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await page.setViewportSize(DESKTOP);
    await signIn(shared, page);
    const display = `${base()}/settings/display`;
    await gotoOnion(page, display);
    await openSchemePanel(page);
    const original = await page.locator("#id_frio_scheme").inputValue();
    try {
      await saveScheme(page, display, "dark");
      await gotoOnion(page, `${base()}/network`);
      await shown(TOPBAR)(page);
      await page.emulateMedia({ colorScheme: "light" });
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark", { timeout: resolveTimeout(10_000) });
      await assertToken(page, "body", "background-color", "--design-surface-1", "dark scheme under a light browser");
      await assertToken(page, TOPBAR, "background-color", "--design-frame", "top bar of the dark scheme");
    } finally {
      await page.emulateMedia({ colorScheme: null });
      await saveScheme(page, display, original);
    }
  });

  function visitorViews() {
    return [
      { name: "home-sign-in", url: `${base()}/`, prepare: shown(SIGN_IN_SUBMIT) },
      { name: "sign-in", url: `${base()}/login`, prepare: shown(SIGN_IN_SUBMIT) },
      {
        name: "sign-in-focus",
        url: `${base()}/login`,
        prepare: async (page) => {
          await shown(USERNAME)(page);
          await page.locator(USERNAME).focus();
        },
      },
      { name: "lost-password", url: `${base()}/lostpass`, prepare: shown("#content form") },
      { name: "about", url: `${base()}/about`, prepare: shown("#content") },
    ];
  }

  function signedInViews() {
    const nick = shared.env.adminUsername;
    const view = (name, path, selector) => ({ name, url: `${base()}${path}`, prepare: shown(selector) });
    return [
      view("network", "/network", "#content"),
      view("own-wall", `/profile/${nick}/conversations`, "#content"),
      view("own-profile", `/profile/${nick}/profile`, "#content"),
      view("photos", `/profile/${nick}/photos`, "#content"),
      view("compose", "/compose", "textarea[name='body']"),
      view("contacts", "/contact", "#content"),
      view("circle-new", "/circle/new", "#content"),
      view("calendar", "/calendar", "#content"),
      view("event-new", "/calendar/event/new", "#content form"),
      view("notes", "/notes", "#content"),
      view("notifications", "/notifications/system", "#content"),
      view("search", "/search?q=infinito", "#content"),
      view("settings-account", "/settings", SETTINGS_SUBMIT),
      { name: "settings-theme", url: `${base()}/settings/display`, prepare: openSchemePanel },
      view("settings-profile", "/settings/profile", "#profile-edit-form"),
      view("settings-features", "/settings/features", CONTENT),
      view("admin-summary", "/admin", ADMIN),
      view("admin-site", "/admin/site", `${ADMIN} form`),
      {
        name: "admin-site-upload",
        url: `${base()}/admin/site`,
        prepare: async (page) => {
          await shown(`${ADMIN} form`)(page);
          await openPanel(page, UPLOAD_PANEL);
        },
      },
      view("admin-addons", "/admin/addons", "#content h1"),
      view("admin-theme-frio", "/admin/themes/frio", "#content h1"),
      view("admin-federation", "/admin/federation", "#FederationChart"),
      view("moderation-users", "/moderation/users", ROW_CELL),
      {
        name: "lightbox-open",
        url: `${base()}/network`,
        prepare: (page) => openLightbox(page, base()),
      },
      {
        name: "user-menu-open",
        url: `${base()}/network`,
        afterOnly: true,
        prepare: async (page) => {
          await shown(TOPBAR)(page);
          if (await page.locator("#main-menu").isVisible()) {
            await page.locator("#main-menu").first().click({ timeout: resolveTimeout(10_000) });
            await settled(page, "#nav-user-menu");
            return;
          }
          await openAccountMenu(page);
        },
      },
    ];
  }

  test("design: gallery of sign-in, stream, profile, settings, administration and moderation", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_500_000));
    const failures = [];
    await captureDesignGallery(page, visitorViews()).catch((error) => failures.push(error.message));
    await signIn(shared, page);
    await seedShowcase(shared, page);
    await captureDesignGallery(page, signedInViews()).catch((error) => failures.push(error.message));
    expect(failures, "design gallery captures").toEqual([]);
  });
};
