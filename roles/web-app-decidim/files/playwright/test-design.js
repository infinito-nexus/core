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
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = decodeDotenvQuotedValue(process.env.DECIDIM_BASE_URL || process.env.APP_BASE_URL);
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const logoEnabled = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_ENABLED || "") === "true";

const MODES = ["light", "dark"];
const MARK = "infinito-design-";
const HEADER = "#sticky-header-container";
const MAIN_BAR = "#main-bar";
const MENU_BAR = "#menu-bar";
const MENU_BAR_ENTRY = `${MENU_BAR} a`;
const FOOTER = "footer .main-footer";
const FOOTER_LINK = `${FOOTER} a`;
const CONSENT = "#dc-dialog-wrapper";
const CONSENT_ACCEPT = "#dc-dialog-accept";
const SIGN_IN_FORM = "#session_new_user";
const SIGN_IN_EMAIL = `${SIGN_IN_FORM} input[type='email']`;
const SIGN_IN_PASSWORD = `${SIGN_IN_FORM} input[type='password']`;
const SIGN_IN_SUBMIT = `${SIGN_IN_FORM} button[type='submit']`;
const SIGN_IN_LABEL = `${SIGN_IN_FORM} label`;
const SIGN_IN_LINK = ".login__info a";
const HEADING = "main h1";
const HERO = ".hero__container, .home__section-image";
const SEARCH_ICON = "#form-search_topbar button svg";
const FLASH = ".flash.alert:not(.flex-col)";
const FLASH_MESSAGE = `${FLASH} .flash__message`;
const PUBLIC_LOGO = ".main-bar__logo-desktop a img";
const MOBILE_LOGO = ".main-bar__logo-mobile a img";
const MAIN_MENU = [
  { trigger: "#main-dropdown-summary", panel: "#main-dropdown-menu" },
  { trigger: "#main-dropdown-summary-mobile", panel: "#dropdown-menu-main-mobile" },
];
const ACCOUNT_MENU = [
  { trigger: "#trigger-dropdown-account", panel: "#dropdown-menu-account" },
  { trigger: "#dropdown-trigger-links-mobile", panel: "#dropdown-menu-account-mobile" },
];
const ADMIN_USER_MENU = [
  { trigger: "#admin-dropdown-menu-login-trigger", panel: "#admin-dropdown-menu-login" },
  { trigger: "#admin-dropdown-menu-login-trigger-responsive", panel: "#admin-dropdown-menu-login-responsive" },
];
const ADMIN_NAV = ".layout-nav";
const ADMIN_NAV_ENTRY = `${ADMIN_NAV} .main-nav ul a`;
const ADMIN_LOGO = `${ADMIN_NAV} .logo img`;
const ADMIN_TITLE_BAR = ".title-bar";
const ADMIN_CONTENT = ".layout-content";
const ADMIN_HEADING = `${ADMIN_CONTENT} h1`;
const ADMIN_ACTION = `${ADMIN_CONTENT} .item_show__header .button__secondary`;
const ADMIN_TERMS_ACCEPT = "form[action$='/admin/admin_terms/accept'] button";
const ADMIN_TABLE_CELL = ".table-list tbody td";
const ADMIN_TABLE_HEAD = ".table-list thead th";
const ADMIN_FRAME = `${ADMIN_NAV}, ${ADMIN_TITLE_BAR}`;
const ADMIN_BREADCRUMB_SEPARATOR = ".process-title .text-white";
const EDITOR = ".editor-container";
const SYSTEM_EMAIL = "input[type='email']";
const SYSTEM_SUBMIT = "form button[type='submit'], form input[type='submit']";

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  };
}

/**
 * Args:
 *   page: Playwright page of a context that has not answered the data consent yet; ends with it accepted.
 */
async function acceptConsent(page) {
  await shown(CONSENT_ACCEPT)(page);
  await page.locator(CONSENT_ACCEPT).click();
  await expect(page.locator(CONSENT)).toBeHidden();
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the organization administrator through the local form.
 *   consent: false when the context has accepted the data consent already.
 */
async function signIn(page, consent = true) {
  await gotoOnion(page, `${base}/users/sign_in`);
  await shown(SIGN_IN_EMAIL)(page);
  if (consent) await acceptConsent(page);
  await page.locator(SIGN_IN_EMAIL).fill(adminEmail);
  await page.locator(SIGN_IN_PASSWORD).fill(adminPassword);
  await page.locator(SIGN_IN_SUBMIT).click();
  await expect(page).not.toHaveURL(/sign_in/, { timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: signed-in Playwright page; ends on the administration dashboard with the administrator terms accepted.
 */
async function openAdmin(page) {
  await gotoOnion(page, `${base}/admin/`);
  if (/admin_terms/.test(page.url())) {
    await page.locator(ADMIN_TERMS_ACCEPT).first().click();
    await expect(page).not.toHaveURL(/admin_terms/, { timeout: resolveTimeout(60_000) });
  }
  await shown(ADMIN_CONTENT)(page);
}

/**
 * Args:
 *   page: Playwright page on a view that renders one of the menus.
 *   variants: trigger and panel selectors per layout; the visible trigger is opened, by pointer or by click, and its panel awaited until no animation runs on it.
 */
async function openMenu(page, variants) {
  for (const { trigger, panel } of variants) {
    if (!(await page.locator(trigger).isVisible())) continue;
    await expect(async () => {
      await page.locator(trigger).hover();
      if ((await page.locator(panel).getAttribute("aria-hidden")) !== "false") await page.locator(trigger).click();
      await expect(page.locator(panel)).toHaveAttribute("aria-hidden", "false", { timeout: resolveTimeout(1_000) });
    }).toPass({ timeout: resolveTimeout(30_000) });
    await expect
      .poll(() =>
        page
          .locator(panel)
          .evaluate(
            (el) => el.getAnimations().every((a) => a.playState !== "running") && getComputedStyle(el).opacity === "1",
          ),
      )
      .toBe(true);
    return;
  }
  throw new Error(`no menu trigger is visible: ${variants.map((variant) => variant.trigger).join(", ")}`);
}

/**
 * Args:
 *   page: Playwright page.
 *   selector: element whose color is read; Decidim derives it from an organization color variable, which computes to the `color(srgb …)` notation.
 *   property: CSS property that holds the color.
 *   token: design token whose rendered pixel the color must equal.
 *   label: prefix of the assertion message.
 */
async function assertTokenPixel(page, selector, property, token, label) {
  await expect
    .poll(
      () =>
        page.evaluate(
          ([target, cssProperty, name]) => {
            const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
            const pixel = (value) => {
              ctx.clearRect(0, 0, 1, 1);
              ctx.fillStyle = "#000";
              ctx.fillStyle = value;
              ctx.fillRect(0, 0, 1, 1);
              return [...ctx.getImageData(0, 0, 1, 1).data].join(",");
            };
            const probe = document.createElement("span");
            probe.style.setProperty(cssProperty, `var(${name})`);
            document.body.appendChild(probe);
            const expected = pixel(getComputedStyle(probe).getPropertyValue(cssProperty));
            probe.remove();
            const actual = pixel(getComputedStyle(document.querySelector(target)).getPropertyValue(cssProperty));
            return actual === expected ? "equal" : `${actual} instead of ${expected}`;
          },
          [selector, property, token],
        ),
      { message: `${label}: ${selector} ${property} must render as ${token}` },
    )
    .toBe("equal");
}

/**
 * Args:
 *   page: Playwright page whose keyboard focus starts at the top of the document.
 *   frame: selector list of the frame elements.
 *   stops: number of Tab presses.
 *   label: prefix of the assertion messages.
 *
 * Returns:
 *   The number of focus stops inside the frame; each one drew its outline in `--design-on-frame`.
 */
async function assertFrameFocus(page, frame, stops, label) {
  const expected = await tokenValue(page, "--design-on-frame", "outline-color");
  let inside = 0;
  for (let stop = 0; stop < stops; stop += 1) {
    await page.keyboard.press("Tab");
    const seen = await page.evaluate((selector) => {
      const el = document.activeElement;
      if (!el || !el.closest(selector) || el.getClientRects().length === 0) return null;
      const style = getComputedStyle(el);
      return { tag: `${el.tagName}.${el.className}`, style: style.outlineStyle, width: style.outlineWidth, color: style.outlineColor };
    }, frame);
    if (seen === null) continue;
    inside += 1;
    expect(seen.style, `${label}: ${seen.tag} draws a focus outline`).not.toBe("none");
    expect(seen.width, `${label}: ${seen.tag} draws a focus outline`).not.toBe("0px");
    expect(seen.color, `${label}: ${seen.tag} draws its focus outline in --design-on-frame`).toBe(expected);
  }
  return inside;
}

function visitorViews(processUrl) {
  const state = { consentOpen: false };
  const view = (name, url, ready, then) => ({
    name,
    url,
    prepare: async (page) => {
      await shown(ready)(page);
      if (state.consentOpen) {
        await acceptConsent(page);
        state.consentOpen = false;
      }
      if (then) await then(page);
    },
  });
  return [
    {
      name: "cookie-consent",
      url: `${base}/`,
      prepare: async (page) => {
        if (!state.consentOpen) {
          await page.context().clearCookies({ name: "decidim-consent" });
          await gotoOnion(page, `${base}/`);
          state.consentOpen = true;
        }
        await shown(CONSENT_ACCEPT)(page);
      },
    },
    view("home", `${base}/`, MAIN_BAR),
    view("sign-in", `${base}/users/sign_in`, SIGN_IN_EMAIL),
    view("sign-in-error", `${base}/users/sign_in`, SIGN_IN_EMAIL, async (page) => {
      await page.locator(SIGN_IN_EMAIL).fill("design-showcase@example.org");
      await page.locator(SIGN_IN_PASSWORD).fill("not-a-real-password");
      await page.locator(SIGN_IN_SUBMIT).click();
      await shown(FLASH)(page);
    }),
    view("sign-up", `${base}/users/sign_up`, "#register-form, form.new_user"),
    view("pages", `${base}/pages`, MENU_BAR),
    view("terms-of-service", `${base}/pages/terms-of-service`, MENU_BAR),
    view("search", `${base}/search?term=a`, MENU_BAR),
    view("processes", `${base}/processes`, MENU_BAR),
    view("process", processUrl, MENU_BAR),
    view("main-menu", `${base}/pages`, MENU_BAR, (page) => openMenu(page, MAIN_MENU)),
    view("profile", `${base}/profiles/administrator`, MENU_BAR),
    view("system-sign-in", `${base}/system/admins/sign_in`, SYSTEM_EMAIL),
  ];
}

function memberViews() {
  const view = (name, path, ready, then) => ({
    name,
    url: `${base}${path}`,
    prepare: async (page) => {
      await shown(ready)(page);
      if (then) await then(page);
    },
  });
  return [
    view("account", "/account", MENU_BAR),
    view("notifications-settings", "/notifications_settings", MENU_BAR),
    view("conversations", "/conversations", MENU_BAR),
    view("account-menu", "/account", MENU_BAR, (page) => openMenu(page, ACCOUNT_MENU)),
    view("admin-dashboard", "/admin/", ADMIN_CONTENT),
    view("admin-organization", "/admin/organization/edit", `${ADMIN_CONTENT} form`),
    view("admin-homepage", "/admin/organization/homepage/edit", ADMIN_CONTENT),
    view("admin-users", "/admin/users", ADMIN_TABLE_CELL),
    view("admin-user-new", "/admin/users/new", `${ADMIN_CONTENT} form`),
    view("admin-participants", "/admin/officializations", ADMIN_TABLE_CELL),
    view("admin-static-pages", "/admin/static_pages", ADMIN_TABLE_CELL),
    view("admin-static-page-new", "/admin/static_pages/new", `${ADMIN_CONTENT} form`),
    view("admin-processes", "/admin/participatory_processes", ADMIN_TABLE_CELL),
    view("admin-process-new", "/admin/participatory_processes/new", `${ADMIN_CONTENT} form`),
    view("admin-moderations", "/admin/moderations", ADMIN_CONTENT),
    view("admin-taxonomies", "/admin/taxonomies", ADMIN_TABLE_CELL),
    view("admin-logs", "/admin/logs", ADMIN_CONTENT),
    view("admin-user-menu", "/admin/users", ADMIN_TABLE_CELL, (page) => openMenu(page, ADMIN_USER_MENU)),
  ];
}

/**
 * Args:
 *   page: Playwright page; any signed-in state is fine.
 *
 * Returns:
 *   The URL of the first participatory process the index lists.
 */
async function firstProcessUrl(page) {
  await gotoOnion(page, `${base}/processes`);
  const link = page.locator("main a[href*='/processes/']").first();
  await expect(link).toBeVisible({ timeout: resolveTimeout(60_000) });
  return new URL(await link.getAttribute("href"), `${base}/`).toString();
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}/users/sign_in`);
  await shown(SIGN_IN_EMAIL)(page);
  await assertDesignTokens(page, "decidim");
});

test("design: the public pages take surfaces, text, actions and frames from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(300_000));
  await gotoOnion(page, `${base}/users/sign_in`);
  await acceptConsent(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/users/sign_in`);
    await shown(SIGN_IN_EMAIL)(page);
    await assertToken(page, HEADER, "background-color", "--design-surface-1", `header ${mode}`);
    await assertToken(page, HEADING, "color", "--design-text", `heading ${mode}`);
    await assertToken(page, SIGN_IN_EMAIL, "background-color", "--design-surface-2", `field ${mode}`);
    await assertToken(page, SIGN_IN_EMAIL, "border-top-color", "--design-border-strong", `field ${mode}`);
    await assertTokenPixel(page, SIGN_IN_LINK, "color", "--design-link", `link ${mode}`);
    await assertToken(page, SEARCH_ICON, "fill", "--design-text-muted", `search icon ${mode}`);
    await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary", `primary action ${mode}`);
    await assertToken(page, SIGN_IN_SUBMIT, "color", "--design-on-primary", `primary action ${mode}`);
    await page.locator(SIGN_IN_SUBMIT).hover();
    await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary-hover", `hovered action ${mode}`);
    await assertToken(page, SIGN_IN_SUBMIT, "color", "--design-on-primary", `hovered action ${mode}`);
    await page.locator(HEADING).first().hover();
    await assertToken(page, MENU_BAR, "background-color", "--design-frame", `menu bar ${mode}`);
    await assertToken(page, MENU_BAR_ENTRY, "color", "--design-on-frame", `menu bar ${mode}`);
    await assertToken(page, FOOTER, "background-color", "--design-frame", `footer ${mode}`);
    await assertToken(page, FOOTER_LINK, "color", "--design-on-frame", `footer ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await gotoOnion(page, `${base}/users/sign_in`);
  await shown(SIGN_IN_EMAIL)(page);
  await assertLightAndDark(page, HEADING, "decidim sign-in");
  await assertReadable(
    page,
    [HEADING, SIGN_IN_SUBMIT, SIGN_IN_LABEL, SIGN_IN_LINK, MENU_BAR_ENTRY, FOOTER_LINK],
    "decidim sign-in",
  );
  await page.locator(SIGN_IN_EMAIL).fill("design-showcase@example.org");
  await page.locator(SIGN_IN_PASSWORD).fill("not-a-real-password");
  await page.locator(SIGN_IN_SUBMIT).click();
  await shown(FLASH)(page);
  await assertToken(page, FLASH, "background-color", "--design-danger-subtle", "sign-in error");
  await assertReadable(page, [FLASH_MESSAGE], "decidim sign-in error");
  await gotoOnion(page, `${base}/pages`);
  await shown(MENU_BAR)(page);
  const stops = await assertFrameFocus(page, MENU_BAR, 25, "public menu bar");
  expect(stops, "the Tab walk reaches the menu bar").toBeGreaterThan(0);
  await gotoOnion(page, `${base}/`);
  await shown(MAIN_BAR)(page);
  const heroImages = await page.evaluate(
    (selector) =>
      [...document.querySelectorAll(selector)].flatMap((element) =>
        [...getComputedStyle(element).backgroundImage.matchAll(/url\("([^"]+)"\)/g)].map((match) => match[1]),
      ),
    HERO,
  );
  for (const url of heroImages) {
    expect(new URL(url).origin, "the hero image is requested from the app, not from the stylesheet host").toBe(
      new URL(base).origin,
    );
  }
});

test("design: the administration takes frame, surfaces, dividers and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(300_000));
  await signIn(page);
  await openAdmin(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/admin/users`);
    await shown(ADMIN_TABLE_CELL)(page);
    await assertToken(page, ADMIN_NAV, "background-color", "--design-frame", `admin navigation ${mode}`);
    await assertToken(page, ADMIN_NAV_ENTRY, "color", "--design-on-frame", `admin navigation ${mode}`);
    await assertToken(page, ADMIN_TITLE_BAR, "background-color", "--design-frame", `title bar ${mode}`);
    await assertToken(page, ADMIN_TITLE_BAR, "color", "--design-on-frame", `title bar ${mode}`);
    await assertToken(page, ADMIN_BREADCRUMB_SEPARATOR, "color", "--design-on-frame", `breadcrumb ${mode}`);
    await assertToken(page, ADMIN_CONTENT, "background-color", "--design-surface-1", `admin page ${mode}`);
    await assertToken(page, ADMIN_HEADING, "color", "--design-text", `admin heading ${mode}`);
    await assertToken(page, ADMIN_TABLE_CELL, "border-bottom-color", "--design-border", `table divider ${mode}`);
    await assertToken(page, ADMIN_ACTION, "background-color", "--design-primary", `admin action ${mode}`);
    await assertToken(page, ADMIN_ACTION, "color", "--design-on-primary", `admin action ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await gotoOnion(page, `${base}/admin/users`);
  await shown(ADMIN_TABLE_CELL)(page);
  await assertLightAndDark(page, ADMIN_HEADING, "decidim administration");
  await assertReadable(
    page,
    [ADMIN_HEADING, ADMIN_TABLE_CELL, ADMIN_TABLE_HEAD, ADMIN_NAV_ENTRY, ADMIN_ACTION],
    "decidim administration",
  );
  await gotoOnion(page, `${base}/admin/users`);
  await shown(ADMIN_TABLE_CELL)(page);
  const stops = await assertFrameFocus(page, ADMIN_FRAME, 20, "administration frame");
  expect(stops, "the Tab walk reaches the administration frame").toBeGreaterThan(0);
  await gotoOnion(page, `${base}/admin/static_pages/new`);
  await shown(EDITOR)(page);
  await assertToken(page, EDITOR, "border-top-color", "--design-border-strong", "rich text editor");
});

test("design: the system panel sign-in takes its surface and action from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/system/admins/sign_in`);
    await shown(SYSTEM_EMAIL)(page);
    await assertToken(page, "body", "background-color", "--design-surface-3", `system page ${mode}`);
    await assertToken(page, HEADING, "color", "--design-text", `system heading ${mode}`);
    await assertToken(page, SYSTEM_SUBMIT, "background-color", "--design-primary", `system action ${mode}`);
    await assertToken(page, SYSTEM_SUBMIT, "color", "--design-on-primary", `system action ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [HEADING, SYSTEM_SUBMIT, "form label"], "decidim system sign-in");
});

test("design: organization name, colors, logo and favicon are the configured ones", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(240_000));
  await page.emulateMedia({ colorScheme: "light" });
  await gotoOnion(page, `${base}/users/sign_in`);
  await shown(SIGN_IN_EMAIL)(page);
  const themeColor = await page.locator("meta[name='theme-color']").getAttribute("content");
  const stored = await page.evaluate((value) => {
    const probe = document.createElement("span");
    probe.style.color = value;
    document.body.appendChild(probe);
    const computed = getComputedStyle(probe).color;
    probe.remove();
    return computed;
  }, themeColor);
  expect(stored, "the organization stores the primary color of the palette").toBe(
    await tokenValue(page, "--design-primary", "color"),
  );
  if (title) {
    await expect(page).toHaveTitle(new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  }
  if (!logoEnabled) return;
  const logo = page.locator(PUBLIC_LOGO).first();
  await expect(logo).toBeVisible();
  await expect(logo).toHaveAttribute("src", new RegExp(`${MARK}logo`));
  await expect
    .poll(() => logo.evaluate((element) => element.complete && element.naturalWidth > 0), {
      message: "the header logo must load",
    })
    .toBe(true);
  const box = await logo.boundingBox();
  expect(box.width, "the header logo is a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
  await expect(page.locator("link[rel='icon']").first()).toHaveAttribute("href", new RegExp(`${MARK}favicon`));
  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = page.locator(MOBILE_LOGO).first();
  await expect(mobile, "below 1024 px the header shows the favicon").toBeVisible();
  await expect(mobile).toHaveAttribute("src", new RegExp(`${MARK}favicon`));
  await expect
    .poll(() => mobile.evaluate((element) => element.complete && element.naturalWidth > 0), {
      message: "the mobile header logo must load",
    })
    .toBe(true);
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await openAdmin(page);
  const symbol = page.locator(ADMIN_LOGO).first();
  await expect(symbol).toBeVisible();
  await expect(symbol).toHaveAttribute("src", new RegExp(`${MARK}logo`));
  const symbolBox = await symbol.boundingBox();
  expect(symbolBox.width, "the administration navigation shows the square symbol").toBeLessThan(symbolBox.height * 1.5);
});

test("design: gallery of public pages, account pages and administration", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  const failures = [];
  const processUrl = await firstProcessUrl(page);
  await acceptConsent(page);
  try {
    await captureDesignGallery(page, visitorViews(processUrl));
  } catch (error) {
    failures.push(error.message);
  }
  await signIn(page, false);
  await openAdmin(page);
  try {
    await captureDesignGallery(page, memberViews());
  } catch (error) {
    failures.push(error.message);
  }
  expect(failures, failures.join("\n")).toEqual([]);
});
