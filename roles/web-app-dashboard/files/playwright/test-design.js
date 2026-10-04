const { test } = require("./fixtures/onion-test");

const { assertDesignTokens, captureDesignGallery, galleryEnabled } = require("./design");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

function baseUrl() {
  return decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
}

async function clickIfVisible(locator) {
  if (await locator.isVisible().catch(() => false)) {
    await locator.click({ timeout: resolveTimeout(10_000) });
  }
}

async function hoverIfVisible(locator) {
  if (await locator.isVisible().catch(() => false)) {
    await locator.hover({ timeout: resolveTimeout(10_000) });
  }
}

function openMenu(menu, pick) {
  return async (page) => {
    await clickIfVisible(page.locator(`.menu-${menu} .navbar-toggler`).first());
    const toggles = page.locator(`.menu-${menu} .nav-item.dropdown > .dropdown-toggle`);
    await clickIfVisible(pick === "last" ? toggles.last() : toggles.nth(pick));
  };
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${baseUrl()}/`);
    await assertDesignTokens(page, "dashboard");
  });

  test("design: gallery of portal states", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    const base = baseUrl();

    await captureDesignGallery(page, [
      { name: "start", url: `${base}/` },
      { name: "start-de", url: `${base}/de` },
      { name: "start-ja", url: `${base}/ja` },
      { name: "start-ar-rtl", url: `${base}/ar` },
      {
        name: "nav-burger",
        url: `${base}/`,
        prepare: (page) => clickIfVisible(page.locator(".menu-header .navbar-toggler").first()),
      },
      { name: "header-menu-first", url: `${base}/`, prepare: openMenu("header", 0) },
      { name: "header-menu-second", url: `${base}/`, prepare: openMenu("header", 1) },
      { name: "header-menu-last", url: `${base}/`, prepare: openMenu("header", "last") },
      {
        name: "header-submenu",
        url: `${base}/`,
        prepare: async (page) => {
          await openMenu("header", 0)(page);
          await hoverIfVisible(page.locator(".menu-header .dropdown-submenu > .dropdown-toggle").first());
        },
      },
      {
        name: "language-item-hover",
        url: `${base}/`,
        prepare: async (page) => {
          await openMenu("header", "last")(page);
          await hoverIfVisible(page.locator(".menu-header .dropdown-menu.show .dropdown-item").nth(2));
        },
      },
      { name: "footer-menu-first", url: `${base}/`, prepare: openMenu("footer", 0) },
      { name: "footer-menu-last", url: `${base}/`, prepare: openMenu("footer", "last") },
      {
        name: "cards",
        url: `${base}/`,
        prepare: (page) => page.locator(".card").nth(3).scrollIntoViewIfNeeded().catch(() => {}),
      },
      { name: "card-hover", url: `${base}/`, prepare: (page) => hoverIfVisible(page.locator(".card").first()) },
      {
        name: "focus-ring",
        url: `${base}/`,
        prepare: async (page) => {
          await page.keyboard.press("Tab");
          await page.keyboard.press("Tab");
        },
      },
      {
        name: "tooltip",
        url: `${base}/`,
        prepare: async (page) => {
          await clickIfVisible(page.locator(".menu-header .navbar-toggler").first());
          await hoverIfVisible(page.locator('.menu-header .nav-link[data-bs-toggle="tooltip"]').first());
          await page.locator(".tooltip.show").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
        },
      },
      { name: "fullscreen", url: `${base}/?fullscreen=1` },
      { name: "fullwidth", url: `${base}/?fullwidth=1` },
      {
        name: "modal-contact",
        url: `${base}/`,
        prepare: async (page) => {
          await openMenu("footer", "last")(page);
          await clickIfVisible(page.locator(".menu-footer .dropdown-menu.show .dropdown-item").first());
          await page.locator(".modal.show").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
        },
      },
      {
        name: "footer",
        url: `${base}/`,
        prepare: (page) => page.locator(".footer").scrollIntoViewIfNeeded().catch(() => {}),
      },
    ]);
  });
};
