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
const { resolveTimeout } = require("./timeouts");

const platformUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const platformPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const kixUsername = decodeDotenvQuotedValue(process.env.KIX_ADMIN_USERNAME || "");
const kixPassword = decodeDotenvQuotedValue(process.env.KIX_ADMIN_PASSWORD || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const FOCUS_WALK_LIMIT = 40;
const SETUP_STEP_LIMIT = 12;
const SIGN_IN = ".login-dialog";
const SIGN_IN_HEADER = `${SIGN_IN} .dialog-header`;
const SIGN_IN_LOGO = `${SIGN_IN_HEADER} #kix-logo img`;
const USERNAME = `${SIGN_IN} input[name="username"]`;
const PASSWORD = `${SIGN_IN} input[name="password"]`;
const SUBMIT = `${SIGN_IN} .dialog-buttons button.special-button`;
const SIGN_IN_ERROR = `${SIGN_IN} .dialog-message-area .message-error`;
const HEADER = "#kix-header";
const HEADER_LOGO = `${HEADER} #logo`;
const FRAMES = `${HEADER}, .sidebar-widget > .widget-header, .lane-widget > .widget-header, .dialog-widget > .widget-header`;
const MENU_OPENER = `${HEADER} > .left .header-icon`;
const SHELL = ".app-wrapper";
const CONTENT = ".content-wrapper";
const TICKETS = `${CONTENT} .ticket-dashboard`;
const SETUP_STEPS = `${CONTENT} .setup-steps`;
const SETUP_OPEN_STEP = `${SETUP_STEPS} .step.active`;
const WIDGET_HEADER = `${CONTENT} .content-widget > .widget-header`;
const WIDGET_BODY = `${CONTENT} .content-widget > .widget-content`;
const TABLE = `${CONTENT} .table-container > .kix-table`;
const HEAD_CELL = `${TABLE} > thead th`;
const CELL = `${TABLE} > tbody tr:not(.toggle-row):not(.spacer-rows) > td`;
const FILTER = `${CONTENT} input[placeholder]`;
const CONSOLE_OUTPUT = `${CONTENT} .console textarea.console-output`;
const CALENDAR_HEAD = `${CONTENT} .calendar-container > div:first-of-type`;
const MENU = ".main-menu-container";
const MENU_ENTRY = `${MENU} ul.main-menu li`;
const MENU_SELECTED = `${MENU} li.active`;
const MOBILE_MENU = ".mobile-main-menu-container";
const LISTED = "/admin?moduleId=ticket-states";

test.use({ ignoreHTTPSErrors: true });

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Args:
 *   page: Playwright page whose finite animations and transitions must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          document
            .getAnimations()
            .some(
              (animation) =>
                animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity,
            ),
        ),
      { timeout: resolveTimeout(15_000), message: "every finite animation of the page must have ended" },
    )
    .toBe(false);
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    await animationsSettled(page);
  };
}

exports.register = function (shared) {
  const base = shared.env.appBaseUrl;

  /**
   * Args:
   *   page: Playwright page that ends on the sign-in page the app renders itself, behind the identity provider when SSO fronts the app.
   */
  async function openSignIn(page) {
    await gotoOnion(page, `${base}/auth`);
    if (shared.env.ssoEnabled) {
      await expect
        .poll(() => page.url(), { timeout: resolveTimeout(30_000), message: "SSO must gate the sign-in page" })
        .toContain(`${shared.env.oidcIssuerUrl}/protocol/openid-connect/auth`);
      await performKeycloakLoginForm(page, platformUsername, platformPassword);
      await expect
        .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "SSO must hand back to the app" })
        .toContain(shared.env.canonicalDomain);
      await gotoOnion(page, `${base}/auth`);
    }
    await expect(page.locator(USERNAME)).toBeVisible({ timeout: resolveTimeout(60_000) });
  }

  /**
   * Args:
   *   page: signed-in Playwright page; ends with every step of the setup assistant skipped, so the app opens the view a URL names.
   */
  async function skipSetupAssistant(page) {
    await gotoOnion(page, `${base}/tickets`);
    await expect(page.locator(`${SETUP_STEPS}, ${TICKETS}`).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    if (await page.locator(SETUP_STEPS).isVisible()) {
      await expect(page.locator(SETUP_OPEN_STEP)).toBeVisible({ timeout: resolveTimeout(30_000) });
    }
    for (let step = 0; step < SETUP_STEP_LIMIT && (await page.locator(SETUP_OPEN_STEP).isVisible()); step += 1) {
      const open = await page.locator(SETUP_OPEN_STEP).innerText();
      await page.locator(`${CONTENT} button.kix-button.form-button`, { hasText: /skip/i }).click();
      await expect
        .poll(
          async () =>
            !(await page.locator(SETUP_OPEN_STEP).isVisible()) || (await page.locator(SETUP_OPEN_STEP).innerText()) !== open,
          { timeout: resolveTimeout(30_000), message: `the setup step ${open} must close after it was skipped` },
        )
        .toBe(true);
    }
  }

  /**
   * Args:
   *   page: Playwright page that ends signed in as the administrator of the app itself, past the setup assistant.
   */
  async function signIn(page) {
    await openSignIn(page);
    await page.locator(USERNAME).fill(kixUsername);
    await page.locator(PASSWORD).fill(kixPassword);
    await page.locator(SUBMIT).click();
    await expect(page.locator(HEADER)).toBeVisible({ timeout: resolveTimeout(90_000) });
    await skipSetupAssistant(page);
  }

  /**
   * Args:
   *   page: Playwright page that ends on one view of the signed-in interface.
   *   path: route of the view below the base URL.
   *   ready: selector that is visible once the view rendered.
   */
  async function openView(page, path, ready) {
    await gotoOnion(page, `${base}${path}`);
    await shown(ready)(page);
  }

  /**
   * Args:
   *   page: Playwright page whose focused element is inspected.
   *
   * Returns:
   *   The name of the focused element, whether a frame element holds it, the color of the surface it sits on and the color of its outline, empty when none is drawn.
   */
  async function focusStop(page) {
    return page.evaluate((frames) => {
      const element = document.activeElement;
      const own = getComputedStyle(element);
      let surface = "";
      const start = element.matches("input, textarea, select") ? element : element.parentElement;
      for (let current = start; current && !surface; current = current.parentElement) {
        const background = getComputedStyle(current).backgroundColor;
        if (!/^rgba\(.*, 0\)$|^transparent$/.test(background)) surface = background;
      }
      return {
        name: [element.tagName.toLowerCase(), ...element.classList].join("."),
        framed: Boolean(element.closest(frames)),
        surface,
        color: own.outlineStyle === "none" || parseFloat(own.outlineWidth) === 0 ? "" : own.outlineColor,
      };
    }, FRAMES);
  }

  function signInViews() {
    const url = `${base}/auth`;
    return [
      { name: "sign-in", url, prepare: shown(USERNAME) },
      {
        name: "sign-in-focus",
        url,
        prepare: async (page) => {
          await shown(USERNAME)(page);
          await page.locator(USERNAME).focus();
        },
      },
      { name: "sign-in-error", url: `${url}?error=true`, prepare: shown(SIGN_IN_ERROR) },
    ];
  }

  function signedInViews() {
    const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
    return [
      view("home", "/home", `${CONTENT} .dashboard.home .widget-header`),
      view("tickets", "/tickets", `${TICKETS} .kix-table`),
      view("ticket-new", "/tickets?new", `${CONTENT} .form-control`),
      view("organisations", "/organisations", `${CONTENT} .customer-dashboard .kix-table`),
      view("organisation-details", "/organisations/1", `${CONTENT} .details-container`),
      view("contact-new", "/contacts?new", `${CONTENT} .form-control`),
      view("assets", "/configitems", `${CONTENT} .cmdb-dashboard`),
      view("faq", "/faqarticles", `${CONTENT} .widget-container`),
      view("faq-new", "/faqarticles?new", `${CONTENT} .object-dialog`),
      view("reporting", "/reporting", `${CONTENT} .reporting-dashboard`),
      view("calendar", "/calendar", `${CONTENT} .widget-container`),
      view("kanban", "/kanban", `${CONTENT} .widget-container`),
      view("admin", "/admin", `${CONTENT} .admin-content`),
      view("admin-users", "/admin?moduleId=users", `${CONTENT} .admin-content .kix-table tbody td`),
      view("admin-roles", "/admin?moduleId=roles", `${CONTENT} .admin-content .kix-table tbody td`),
      view("admin-sysconfig", "/admin?moduleId=sysconfig", `${CONTENT} .admin-content .kix-table`),
      view("admin-queues", "/admin?moduleId=queues", `${CONTENT} .admin-content .kix-table tbody td`),
      view("admin-ticket-states", LISTED, `${CONTENT} .admin-content .kix-table tbody td`),
      view("admin-console", "/admin?moduleId=console", `${CONTENT} .admin-content .console`),
      view("admin-logs", "/admin?moduleId=logs", `${CONTENT} .admin-content .kix-table`),
      view("admin-setup-assistant", "/admin?moduleId=setup-assistant", SETUP_STEPS),
      {
        name: "main-menu",
        url: `${base}/home`,
        prepare: async (page) => {
          await shown(`${CONTENT} .dashboard.home .widget-header`)(page);
          if (await page.locator(MENU_OPENER).first().isVisible()) {
            await page.locator(MENU_OPENER).first().click();
            await shown(MOBILE_MENU)(page);
          } else {
            await page.locator(MENU_ENTRY).nth(1).hover();
            await animationsSettled(page);
          }
        },
      },
    ];
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await openSignIn(page);
    await assertDesignTokens(page, "kix");
  });

  test("design: the sign-in page takes surfaces, frame, primary action and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await openSignIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".login-wrapper", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await expect(page.locator(".login-wrapper"), `sign-in image ${mode}`).toHaveCSS("background-image", "none");
      await assertToken(page, SIGN_IN, "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, SIGN_IN_HEADER, "background-color", "--design-frame", `sign-in ${mode}`);
      await assertToken(page, `${SIGN_IN_HEADER} h1`, "color", "--design-on-frame", `sign-in ${mode}`);
      await assertToken(page, `${SIGN_IN_HEADER} #kix-logo`, "background-color", "--design-surface-2", `logo pill ${mode}`);
      await assertToken(page, `${SIGN_IN} .dialog-content label span`, "color", "--design-text-muted", `sign-in ${mode}`);
      await assertToken(page, PASSWORD, "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, PASSWORD, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await page.locator(SUBMIT).hover();
      await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
      await page.locator(`${SIGN_IN_HEADER} h1`).hover();
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, `${SIGN_IN} .dialog-content`, "kix sign-in");
    await assertReadable(
      page,
      [`${SIGN_IN_HEADER} h1`, `${SIGN_IN} .dialog-content label span`, USERNAME, SUBMIT],
      "kix sign-in",
    );
  });

  test("design: a requested view is not replaced by the setup assistant or the release page", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const [path, ready] of [
      ["/tickets", TICKETS],
      ["/home", `${CONTENT} .dashboard.home`],
    ]) {
      await openView(page, path, ready);
      expect(new URL(page.url()).pathname, `${path} must stay the open view`).toBe(path);
    }
  });

  test("design: the signed-in interface takes frame, surfaces, dividers and text from the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openView(page, LISTED, CELL);
      await assertToken(page, SHELL, "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, HEADER, "background-color", "--design-frame", `frame ${mode}`);
      await assertToken(page, HEADER, "color", "--design-on-frame", `frame ${mode}`);
      await assertToken(page, HEADER, "border-bottom-color", "--design-primary", `frame accent ${mode}`);
      await assertToken(page, WIDGET_BODY, "background-color", "--design-surface-2", `panel ${mode}`);
      await assertToken(page, WIDGET_HEADER, "background-color", "--design-surface-active", `panel head ${mode}`);
      await assertToken(page, HEAD_CELL, "background-color", "--design-surface-3", `table head ${mode}`);
      await assertToken(page, CELL, "color", "--design-text", `table ${mode}`);
      await assertToken(page, CELL, "border-right-color", "--design-border", `cell divider ${mode}`);
      await assertToken(page, HEAD_CELL, "border-right-color", "--design-border", `head divider ${mode}`);
      expect(
        await page
          .locator(FILTER)
          .first()
          .evaluate((element) => getComputedStyle(element, "::placeholder").color),
        `the placeholder of a filter field ${mode} must take the muted text tone`,
      ).toBe(await tokenValue(page, "--design-text-muted", "color"));
      await assertToken(page, MENU, "background-color", "--design-surface-3", `menu ${mode}`);
      await assertToken(page, MENU_SELECTED, "background-color", "--design-primary", `selected entry ${mode}`);
      await assertToken(page, `${MENU_SELECTED} a`, "color", "--design-on-primary", `selected entry ${mode}`);
      await page.locator(CELL).first().hover();
      await assertToken(page, `${TABLE} > tbody tr:hover`, "background-color", "--design-surface-hover", `row ${mode}`);
      const frame = await tokenValue(page, "--design-frame", "background-color");
      const onFrame = await tokenValue(page, "--design-on-frame", "color");
      const link = await tokenValue(page, "--design-link", "color");
      const stops = { frame: 0, hosted: 0 };
      await openView(page, LISTED, CELL);
      for (let step = 0; step < FOCUS_WALK_LIMIT; step += 1) {
        await page.keyboard.press("Tab");
        const stop = await focusStop(page);
        if (!stop.framed) continue;
        const kind = stop.surface === frame ? "frame" : "hosted";
        stops[kind] += 1;
        expect(
          stop.color,
          `keyboard stop ${stop.name} ${mode} sits on ${stop.surface}, so it must draw ${kind === "frame" ? "--design-on-frame" : "--design-link"}`,
        ).toBe(kind === "frame" ? onFrame : link);
      }
      expect(stops.hosted, `the keyboard walk must find the search field the header hosts ${mode}`).toBeGreaterThan(0);
    }
    await page.emulateMedia({ colorScheme: null });
    await openView(page, LISTED, CELL);
    await assertLightAndDark(page, CELL, "kix shell");
    await assertReadable(
      page,
      [CELL, HEAD_CELL, WIDGET_HEADER, `${MENU_SELECTED} a`, `${MENU_ENTRY}:not(.active) a`, ".footer-wrapper"],
      "kix shell",
    );
  });

  test("design: the opened mobile menu keeps its entries on the frame with readable text", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await signIn(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await openView(page, "/home", `${CONTENT} .dashboard.home .widget-header`);
    await page.locator(MENU_OPENER).first().click();
    await shown(MOBILE_MENU)(page);
    const selected = `${MOBILE_MENU} ul.main-menu li.active`;
    const entry = `${MOBILE_MENU} ul.main-menu li:not(.active)`;
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, entry, "background-color", "--design-frame", `menu entry ${mode}`);
      await assertToken(page, `${entry} > a`, "color", "--design-on-frame", `menu entry ${mode}`);
      await assertToken(page, selected, "background-color", "--design-frame-active", `selected menu entry ${mode}`);
      await assertToken(page, `${selected} > a`, "color", "--design-on-frame", `selected menu entry ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${selected} > a`, `${entry} > a`], "kix mobile menu");
  });

  test("design: editor, calendar head and read-only fields follow the palette", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    await signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openView(page, "/admin?moduleId=console", CONSOLE_OUTPUT);
      await assertToken(page, CONSOLE_OUTPUT, "background-color", "--design-surface-1", `read-only field ${mode}`);
      await assertToken(page, CONSOLE_OUTPUT, "color", "--design-text", `read-only field ${mode}`);
      for (const [variable, property, token] of [
        ["--ck-color-base-background", "background-color", "--design-surface-2"],
        ["--ck-color-base-foreground", "background-color", "--design-surface-3"],
        ["--ck-color-base-text", "color", "--design-text"],
        ["--ck-color-base-border", "border-top-color", "--design-border-strong"],
      ]) {
        expect(await tokenValue(page, variable, property), `editor variable ${variable} ${mode} must be ${token}`).toBe(
          await tokenValue(page, token, property),
        );
      }
      await openView(page, "/calendar", CALENDAR_HEAD);
      await assertToken(page, CALENDAR_HEAD, "background-color", "--design-frame", `calendar head ${mode}`);
      await assertToken(page, CALENDAR_HEAD, "color", "--design-on-frame", `calendar head ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [CALENDAR_HEAD], "kix calendar head");
  });

  test("design: sign-in page and header show the generated logo, every page the configured title", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

    const published = async (url) => {
      const response = await apiGetOnion(page.request, url, { timeout: resolveTimeout(30_000) });
      expect(response.ok(), `the generated image ${url} must be served`).toBe(true);
      return (await response.body()).toString("base64");
    };
    const inlined = async (selector, attribute) =>
      ((await page.locator(selector).first().getAttribute(attribute)) || "").split(";base64,").pop().replace(/\s+/g, "");

    await openSignIn(page);
    if (title) await expect(page).toHaveTitle(title);
    if (logoUrl) {
      expect(await inlined(SIGN_IN_LOGO, "src"), "the sign-in page must show the generated lockup").toBe(await published(logoUrl));
      expect(await inlined("link[rel~='icon']", "href"), "the favicon must be the generated one").toBe(
        await published(faviconUrl),
      );
      const pill = await page.locator(`${SIGN_IN_HEADER} #kix-logo`).boundingBox();
      expect(pill.width, "the sign-in logo box holds a lockup, so it must be wider than high").toBeGreaterThan(pill.height);
    }

    await signIn(page);
    await openView(page, "/home", `${CONTENT} .dashboard.home`);
    if (title) await expect(page).toHaveTitle(new RegExp(` · ${escapeRegExp(title)}$`));
    if (logoUrl) {
      await expect
        .poll(() => page.locator(HEADER_LOGO).evaluate((image) => getComputedStyle(image).content), {
          timeout: resolveTimeout(30_000),
          message: "the header must show the generated lockup",
        })
        .toContain(logoUrl);
      await expect
        .poll(async () => (await page.locator(HEADER_LOGO).boundingBox()).width, {
          timeout: resolveTimeout(30_000),
          message: "the header logo box holds a loaded lockup, so it must be wider than high",
        })
        .toBeGreaterThan((await page.locator(HEADER_LOGO).boundingBox()).height);
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        await assertToken(page, HEADER_LOGO, "background-color", "--design-surface-2", `logo pill ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
    }
  });

  test("design: gallery of sign-in, dashboards, forms, details and administration", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.skip(shared.env.ssoEnabled, "the gallery signs in with the local administrator of an SSO-less deployment");
    test.setTimeout(resolveTimeout(2_400_000));

    await signIn(page);
    await captureDesignGallery(page, [...signedInViews(), ...signInViews()]);
  });
};
