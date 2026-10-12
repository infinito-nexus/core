const { test, expect } = require("./fixtures/onion-test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
} = require("./design");
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

async function openBurger(page, menu) {
  const toggler = page.locator(`.menu-${menu} .navbar-toggler`).first();
  if (await toggler.isVisible().catch(() => false)) {
    await toggler.click({ timeout: resolveTimeout(10_000) });
    await page
      .locator(`.menu-${menu} .navbar-collapse.show`)
      .waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  }
}

function openMenu(menu, pick) {
  return async (page) => {
    await openBurger(page, menu);
    const toggles = page.locator(`.menu-${menu} .nav-item.dropdown > .dropdown-toggle`);
    await clickIfVisible(pick === "last" ? toggles.last() : toggles.nth(pick));
  };
}

exports.register = function (shared) {
  async function openPortal(page) {
    await gotoOnion(page, `${baseUrl()}/`);
    await shared.waitForDashboardReady(page);
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openPortal(page);
    await assertDesignTokens(page, "dashboard");
  });

  test("design: portal text stays readable in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openPortal(page);
    await assertLightAndDark(page, "body", "dashboard");
    await assertReadable(
      page,
      [
        "header.header h1",
        ".navbar .nav-link",
        ".card .card-title",
        ".card .card-text",
        ".card .btn",
        ".footer a",
      ].map((selector) => ({ selector, optional: true })),
      "dashboard",
    );
  });

  test("design: portal page, header, navigation and scroll thumb take their tokens in light and dark mode", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await openPortal(page);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `dashboard page ${mode}`);
      await assertToken(page, "header.header", "background-color", "--design-surface-2", `dashboard header ${mode}`);
      await assertToken(page, ".navbar.menu-header", "background-color", "--design-surface-2", `dashboard navbar ${mode}`);
      await assertToken(page, ".navbar.menu-header", "color", "--design-text", `dashboard navbar text ${mode}`);
      await assertToken(page, "#scroll-thumb", "background-color", "--design-neutral-400", `dashboard scroll thumb ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: cards take the surface, text and divider tokens in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openPortal(page);
    test.skip((await page.locator(".card").count()) === 0, "this deployment renders no card");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".card", "background-color", "--design-surface-2", `dashboard card ${mode}`);
      await assertToken(page, ".card", "color", "--design-text", `dashboard card text ${mode}`);
      await assertToken(page, ".card .card-title", "color", "--design-text", `dashboard card title ${mode}`);
      await assertToken(page, ".card", "border-top-color", "--design-border", `dashboard card divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the current language is filled with the primary color and its text", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openPortal(page);
    await openMenu("header", "last")(page);
    const active = ".menu-header .language-menu.show .dropdown-item.active";
    await expect(page.locator(active)).toBeVisible({ timeout: resolveTimeout(10_000) });
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, active, "background-color", "--design-primary", `dashboard current language ${mode}`);
      await assertToken(page, active, "color", "--design-on-primary", `dashboard current language text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [active], "dashboard current language");
  });

  test("design: an open menu entry follows the color mode and stays readable with its items", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openPortal(page);
    await openMenu("header", 0)(page);
    await assertLightAndDark(page, ".menu-header .nav-link.show", "dashboard open menu");
    await assertReadable(
      page,
      [".menu-header .nav-link.show", ".menu-header .dropdown-menu.show .dropdown-item"],
      "dashboard open menu",
    );
  });

  test("design: a submenu box encloses its first entry", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openPortal(page);
    await openMenu("header", 0)(page);
    const submenu = page.locator(".menu-header .dropdown-menu.show .dropdown-submenu").first();
    test.skip((await submenu.count()) === 0, "the first header menu of this deployment has no submenu");
    await submenu.locator("> .dropdown-toggle").hover({ timeout: resolveTimeout(10_000) });
    const box = submenu.locator("> .dropdown-menu");
    await expect(box).toBeVisible();
    const [boxBottom, entryBottom] = await box.evaluate((menu) => [
      menu.getBoundingClientRect().bottom,
      menu.firstElementChild.getBoundingClientRect().bottom,
    ]);
    expect(boxBottom, "dashboard: the submenu box must reach below its first entry").toBeGreaterThanOrEqual(
      entryBottom,
    );
  });

  test("design: a hovered card is not filtered and keeps its text readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openPortal(page);
    const card = page.locator(".card").first();
    test.skip((await card.count()) === 0, "this deployment renders no card");
    await card.hover({ timeout: resolveTimeout(10_000) });
    expect(
      await card.evaluate((element) => getComputedStyle(element).filter),
      "dashboard: a hovered card must not be filtered",
    ).toBe("none");
    await assertReadable(page, [".card:hover .card-title"], "dashboard hovered card");
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
      { name: "nav-burger", url: `${base}/`, prepare: (page) => openBurger(page, "header") },
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
        prepare: (page) => page.locator(".card").last().scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) }),
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
          await openBurger(page, "header");
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
