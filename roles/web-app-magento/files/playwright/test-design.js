const { test, expect } = require("@playwright/test");

const { TWO_FACTOR_SKIP, adminSignIn, twoFactorEnabled } = require("./admin");
const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
  tokenValue,
} = require("./design");
const { MENU, guestViews, memberViews, usageNoticeShows } = require("./gallery-views");
const { apiGetOnion, decodeDotenvQuotedValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { SIGN_IN_FORM, adminNavigator, customerSignIn, hideUsageNotice, openShop, seedShowcase } = require("./showcase");
const { resolveTimeout } = require("./timeouts");

const designTitle = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const designTheme = decodeDotenvQuotedValue(process.env.DESIGN_THEME || "");
const designLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const designAdminLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_ADMIN_LOGO_URL || "");
const designAdminLoginLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_ADMIN_LOGIN_LOGO_URL || "");

const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const SIGN_IN_BUTTON = `${SIGN_IN_FORM} button.action.login`;
const HEADER_PANEL = ".page-header .panel.wrapper";
const INJECTED_SHEET = /\/_shared\/css\/|\/roles\/web-app-magento\//;
const ROLE_SHEET = "link[href*='/roles/web-app-magento/'][href*='style.css']";
const CACHE_GRID = "#cache_grid_table";
const TREE_SELECTION = ".jstree-default .jstree-clicked";

function style(page, selector, property, pseudo) {
  return page
    .locator(selector)
    .first()
    .evaluate((element, [name, part]) => getComputedStyle(element, part).getPropertyValue(name), [property, pseudo]);
}

async function inEachMode(page, check) {
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await check(mode);
  }
  await page.emulateMedia({ colorScheme: null });
}

async function focusStops(page, first, frame) {
  await page.locator(first).first().focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  const stops = [];
  for (let index = 0; index < 40; index += 1) {
    const stop = await page.evaluate((selector) => {
      const element = document.activeElement;
      return element.closest(selector)
        ? { name: `${element.tagName.toLowerCase()}.${element.className.toString().split(" ")[0]}`, ring: getComputedStyle(element).boxShadow }
        : null;
    }, frame);
    if (!stop) break;
    stops.push(stop);
    await page.keyboard.press("Tab");
  }
  return stops;
}

async function openCacheManagement(page) {
  const nav = adminNavigator();
  await adminSignIn(page);
  await nav.open(page, MENU.cache, CACHE_GRID);
  await hideUsageNotice(page);
  return nav;
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await openShop(page, "/", ".page-footer");
  await assertDesignTokens(page, "magento storefront");
});

test("design: the storefront takes surfaces, text, primary action, fields and dividers from the tokens", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await openShop(page, "/customer/account/login/", SIGN_IN_FORM);
  await inEachMode(page, async (mode) => {
    await assertToken(page, "body", "background-color", "--design-surface-1", `storefront page ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `storefront text ${mode}`);
    await assertToken(page, SIGN_IN_BUTTON, "background-color", "--design-primary", `storefront primary ${mode}`);
    await assertToken(page, SIGN_IN_BUTTON, "color", "--design-on-primary", `storefront on-primary ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} #email`, "border-top-color", "--design-border-strong", `storefront field ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} #email`, "background-color", "--design-surface-2", `storefront field ${mode}`);
    await assertToken(page, ".login-container .block-title", "border-bottom-color", "--design-border", `storefront divider ${mode}`);
    await assertToken(page, ".footer.content", "border-top-color", "--design-border", `storefront footer divider ${mode}`);
    await assertToken(page, ".page-footer", "background-color", "--design-surface-3", `storefront footer ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} a.action.remind`, "color", "--design-link", `storefront link ${mode}`);
    await assertToken(page, HEADER_PANEL, "background-color", "--design-frame", `storefront header panel ${mode}`);
    await assertToken(page, `${HEADER_PANEL} .header.links a`, "color", "--design-on-frame", `storefront header link ${mode}`);
    await assertToken(page, ".copyright", "background-color", "--design-frame", `storefront copyright ${mode}`);
    await assertToken(page, ".copyright", "color", "--design-on-frame", `storefront copyright ${mode}`);
  });
  await page.locator(`${SIGN_IN_FORM} #email`).focus();
  await inEachMode(page, async (mode) => {
    const link = (await tokenValue(page, "--design-link", "color")).replace(/\s/g, "");
    expect(
      (await style(page, `${SIGN_IN_FORM} #email`, "box-shadow")).replace(/\s/g, ""),
      `a focused storefront field draws its ring in --design-link (${mode})`,
    ).toContain(link);
  });
  await assertLightAndDark(page, ".login-container", "magento storefront");
  await assertReadable(
    page,
    [".page-title", SIGN_IN_BUTTON, ".login-container .block-title", `${SIGN_IN_FORM} a.action.remind`, ".footer.content a", ".copyright", `${HEADER_PANEL} .header.links a`],
    "magento storefront",
  );
});

test("design: the corporate theme carries the light palette without the injected sheets", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await page.emulateMedia({ colorScheme: "light" });
  await openShop(page, "/customer/account/login/", SIGN_IN_FORM);
  await expect(
    page.locator(`link[href*='/frontend/${designTheme}/'][href$='/css/styles-m.css']`),
    "the storefront links the compiled stylesheet of the corporate theme",
  ).toHaveCount(1);
  const expected = {
    frame: await tokenValue(page, "--design-frame", "color"),
    primary: await tokenValue(page, "--design-primary", "color"),
    surface: await tokenValue(page, "--design-surface-1", "color"),
    text: await tokenValue(page, "--design-text", "color"),
  };
  const disabled = await page.evaluate((pattern) => {
    const injected = [...document.styleSheets].filter((sheet) => new RegExp(pattern).test(sheet.href || ""));
    for (const sheet of injected) sheet.disabled = true;
    return injected.length;
  }, INJECTED_SHEET.source);
  expect(disabled, "the injected design sheets are found before they are switched off").toBeGreaterThan(2);
  expect(
    {
      frame: await style(page, HEADER_PANEL, "background-color"),
      primary: await style(page, SIGN_IN_BUTTON, "background-color"),
      surface: await style(page, "body", "background-color"),
      text: await style(page, "body", "color"),
    },
    "the compiled theme holds the light values of the palette",
  ).toEqual(expected);
});

test("design: the storefront shows the configured logo, favicon, title and welcome text", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await openShop(page, "/customer/account/login/", SIGN_IN_FORM);
  if (designTitle) {
    expect(await page.title(), "the page title ends with the design title").toMatch(
      new RegExp(` - ${designTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
    );
    await expect(page.locator(`${HEADER_PANEL} .greet.welcome`).first()).toContainText(designTitle, {
      timeout: resolveTimeout(60_000),
    });
  }
  test.skip(!designLogoUrl, "the logo replacement is disabled");
  const logo = page.locator("a.logo img");
  const src = await logo.evaluate((image) => image.src);
  expect(src, "the logo is the file the design task stored in the media directory").toMatch(
    /\/media\/logo\/infinito\/logo-[0-9a-f]{12}\.svg$/,
  );
  await expect.poll(() => logo.evaluate((image) => image.naturalWidth), { message: "the storefront logo loads" }).toBeGreaterThan(0);
  const box = await logo.boundingBox();
  expect(box.width, "the storefront logo is a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
  const served = await apiGetOnion(page.request, src);
  const generated = await apiGetOnion(page.request, designLogoUrl);
  expect(generated.ok(), `the generated logo answers ${generated.status()}`).toBe(true);
  expect(Buffer.compare(await served.body(), await generated.body()), "Magento serves the generated lockup").toBe(0);
  const icon = await page.locator("link[rel='icon']").first().evaluate((link) => link.href);
  expect(icon, "the favicon is the file the design task stored in the media directory").toMatch(
    /\/media\/favicon\/infinito\/favicon-[0-9a-f]{12}\.ico$/,
  );
  expect((await apiGetOnion(page.request, icon)).status(), "the favicon is served").toBe(200);
});

test("design: every image the role stylesheet references is served", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await openShop(page, "/", ".page-footer");
  const sheet = await page.locator(ROLE_SHEET).first().evaluate((link) => link.href);
  const css = await (await apiGetOnion(page.request, sheet)).text();
  const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
    .filter((target) => !target.startsWith("data:"))
    .map((target) => new URL(target, sheet).href);
  expect(targets.length, "the role stylesheet references images").toBeGreaterThan(0);
  for (const target of targets) {
    const answer = await apiGetOnion(page.request, target);
    expect(
      `${answer.status()} ${answer.headers()["content-type"]}`,
      `${target} must be served as an image; a relative url() resolves against the stylesheet on the CDN`,
    ).toMatch(/^200 image\//);
  }
});

test("design: focus stops inside the storefront header panel draw in the frame text color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await openShop(page, "/customer/account/login/", SIGN_IN_FORM);
  const onFrame = (await tokenValue(page, "--design-on-frame", "color")).replace(/\s/g, "");
  const stops = await focusStops(page, `${HEADER_PANEL} a`, HEADER_PANEL);
  expect(stops.length, "the Tab walk visits the links of the header panel").toBeGreaterThan(1);
  for (const stop of stops) {
    expect(stop.ring.replace(/\s/g, ""), `${stop.name} draws its focus ring in --design-on-frame`).toContain(onFrame);
  }
});

test("design: the admin sign-in page sits on the frame with the corporate logo", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await openShop(page, "/admin", "#login-form");
  await inEachMode(page, async (mode) => {
    await assertToken(page, "body", "background-color", "--design-frame", `admin sign-in page ${mode}`);
    await assertToken(page, ".page-wrapper", "background-color", "--design-surface-2", `admin sign-in box ${mode}`);
    await assertToken(page, ".admin__legend", "color", "--design-text", `admin sign-in legend ${mode}`);
    await assertToken(page, ".action-login", "background-color", "--design-primary", `admin sign-in button ${mode}`);
    await assertToken(page, ".action-login", "color", "--design-on-primary", `admin sign-in button ${mode}`);
    await assertToken(page, "#login", "border-top-color", "--design-border-strong", `admin sign-in field ${mode}`);
    await assertToken(page, ".login-footer", "color", "--design-on-frame", `admin sign-in footer ${mode}`);
  });
  await assertReadable(page, [".admin__legend", ".action-login", ".admin__field-label", ".action-forgotpassword"], "magento admin sign-in");
  test.skip(!designAdminLoginLogoUrl, "the logo replacement is disabled");
  expect(await style(page, ".login-header .logo-img", "content"), "the sign-in box shows the corporate lockup").toContain(
    designAdminLoginLogoUrl,
  );
  const box = await page.locator(".login-header .logo-img").boundingBox();
  expect(box.width, "the sign-in logo is a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
});

test("design: the admin maps its tokens and keeps the menu on the frame", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(twoFactorEnabled(), TWO_FACTOR_SKIP);
  test.setTimeout(resolveTimeout(300_000));
  await page.setViewportSize(DESKTOP);
  const nav = await openCacheManagement(page);
  await assertDesignTokens(page, "magento admin");
  await inEachMode(page, async (mode) => {
    const frame = await tokenValue(page, "--design-frame", "background-color");
    expect(await style(page, ".menu-wrapper", "background-color", "::before"), `admin menu ${mode}`).toBe(frame);
    await assertToken(page, ".admin__menu .level-0 > a", "color", "--design-on-frame", `admin menu entry ${mode}`);
    await assertToken(page, "body", "background-color", "--design-surface-1", `admin page ${mode}`);
    await assertToken(page, ".page-wrapper", "background-color", "--design-surface-2", `admin content ${mode}`);
    await assertToken(page, ".page-title", "color", "--design-text", `admin title ${mode}`);
    await assertToken(page, "#flush_magento", "background-color", "--design-primary", `admin primary ${mode}`);
    await assertToken(page, "#flush_magento", "color", "--design-on-primary", `admin on-primary ${mode}`);
    await assertToken(page, `${CACHE_GRID} thead th`, "background-color", "--design-surface-3", `admin grid head ${mode}`);
    await assertToken(page, `${CACHE_GRID} thead th`, "color", "--design-text", `admin grid head ${mode}`);
    await assertToken(page, `${CACHE_GRID} tbody td`, "border-bottom-color", "--design-border", `admin grid divider ${mode}`);
  });
  await assertLightAndDark(page, ".page-title", "magento admin");
  await assertReadable(
    page,
    [".page-title", "#flush_magento", `${CACHE_GRID} thead th`, `${CACHE_GRID} tbody td`, `${CACHE_GRID} .grid-severity-notice`, ".admin-user-account-text"],
    "magento admin",
  );
  if (designAdminLogoUrl) {
    expect(await style(page, ".menu-wrapper .logo-img", "content"), "the menu shows the corporate logo").toContain(designAdminLogoUrl);
  }
  await nav.open(page, MENU.categories, TREE_SELECTION);
  await inEachMode(page, async (mode) => {
    await assertToken(page, TREE_SELECTION, "background-color", "--design-surface-active", `admin tree selection ${mode}`);
  });
  await assertReadable(page, [TREE_SELECTION], "magento admin category tree");
});

test("design: focus stops inside the admin menu draw in the frame text color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(twoFactorEnabled(), TWO_FACTOR_SKIP);
  test.setTimeout(resolveTimeout(300_000));
  await page.setViewportSize(DESKTOP);
  await openCacheManagement(page);
  const onFrame = (await tokenValue(page, "--design-on-frame", "color")).replace(/\s/g, "");
  const stops = await focusStops(page, ".menu-wrapper a.logo", ".menu-wrapper");
  expect(stops.length, "the Tab walk visits the logo and the menu entries").toBeGreaterThan(5);
  for (const stop of stops) {
    expect(stop.ring.replace(/\s/g, ""), `${stop.name} draws its focus ring in --design-on-frame`).toContain(onFrame);
  }
});

test("design: gallery of storefront and admin", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.skip(twoFactorEnabled(), TWO_FACTOR_SKIP);
  test.setTimeout(resolveTimeout(5_400_000));
  await openShop(page, "/", "a.logo img");
  await seedShowcase(page);
  const failures = [];
  await captureDesignGallery(page, guestViews()).catch((error) => failures.push(error.message));
  await customerSignIn(page);
  const nav = adminNavigator();
  const notice = await usageNoticeShows(page, nav);
  await captureDesignGallery(page, memberViews(nav, notice)).catch((error) => failures.push(error.message));
  expect(failures, failures.join("\n")).toEqual([]);
});
