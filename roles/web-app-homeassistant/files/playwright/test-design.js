const { test, expect } = require("@playwright/test");

const { SHELL, SIGN_IN_FORM } = require("./_shared");
const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
  tokenValue,
} = require("./design");
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const LOG_IN = "ha-authorize .action ha-button button";
const SIGN_IN_TEXTS = ["ha-authorize h1", LOG_IN, "ha-authorize a.forgot-password", "ha-authorize ha-checkbox"];
const ACTIONS = "developer-tools-action";
const PERFORM = `${ACTIONS} ha-progress-button button`;
const SIDEBAR = "ha-sidebar";
const SIDEBAR_TOGGLE = "Sidebar toggle";
const USER_INITIALS = `${SIDEBAR} ha-user-badge .initials`;
const SHELL_TEXTS = [`${ACTIONS} .header-title`, `${ACTIONS} p.secondary`, PERFORM, `${SIDEBAR} .title`, USER_INITIALS];
const THEME_ROW = "ha-pick-theme-row";
const PROFILE_CARD = "ha-profile-section-general ha-card";
const DIALOG = "dialog[open]";
const NARROW_BELOW = 870;
const OWN_THEME = "Home Assistant";
const SHOWCASE_LIST = "todo.shopping_list";
const SHOWCASE_TODO = "Review the corporate design";

/**
 * Args:
 *   page: Playwright page whose finite animations, those inside shadow roots included, must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            new Promise((resolve) => {
              const running = (root) =>
                root
                  .getAnimations()
                  .some(
                    (animation) =>
                      animation.playState === "running" &&
                      animation.effect?.getComputedTiming().iterations !== Infinity,
                  ) || [...root.querySelectorAll("*")].some((element) => element.shadowRoot && running(element.shadowRoot));
              requestAnimationFrame(() => requestAnimationFrame(() => resolve(running(document))));
            }),
        ),
      { message: "every finite animation of the page, shadow roots included, must have ended" },
    )
    .toBe(false);
}

/**
 * Args:
 *   locator: Playwright locator whose first match is measured, shadow roots included.
 *
 * Returns:
 *   The contrast ratio between the text color of the element and the first opaque background on its flattened ancestor chain.
 */
async function contrastOf(locator) {
  return locator.first().evaluate((element) => {
    const context = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    const rgba = (value) => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = "#000";
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const luminance = (channels) => {
      const [r, g, b] = channels.map((channel) => {
        const share = channel / 255;
        return share <= 0.04045 ? share / 12.92 : ((share + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const parent = (node) => node.assignedSlot || node.parentElement || node.getRootNode().host || null;
    let background = [255, 255, 255];
    for (let current = element; current; current = parent(current)) {
      const [r, g, b, a] = rgba(getComputedStyle(current).backgroundColor);
      if (a > 0.5) {
        background = [r, g, b];
        break;
      }
    }
    const [r, g, b, a] = rgba(getComputedStyle(element).color);
    const color = [r, g, b].map((channel, index) => a * channel + (1 - a) * background[index]);
    const [fg, bg] = [luminance(color), luminance(background)];
    return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
  });
}

async function assertContrast(page, selectors, label) {
  for (const selector of selectors) {
    expect(
      await contrastOf(page.locator(selector)),
      `${label}: '${selector}' must reach contrast 4.5 against its background`,
    ).toBeGreaterThanOrEqual(4.5);
  }
}

/**
 * Args:
 *   page: Playwright page that shows the signed-in interface.
 *
 * Returns:
 *   The theme state of the frontend: applied theme, default theme and the selection of the user.
 */
async function themeState(page) {
  return page.evaluate(() => {
    const { themes, selectedTheme, config } = document.querySelector("home-assistant").hass;
    return {
      applied: themes.theme,
      standard: themes.default_theme,
      standardDark: themes.default_dark_theme,
      selected: selectedTheme,
      location: config.location_name,
    };
  });
}

/**
 * Args:
 *   page: Playwright page that shows the signed-in interface.
 *   theme: name of the theme to store for the user the way the profile controls do; an empty string returns to the default theme and the automatic mode.
 */
async function selectTheme(page, theme) {
  await page.evaluate(
    (name) =>
      document.querySelector("home-assistant").dispatchEvent(
        new CustomEvent("settheme", {
          detail: { theme: name || undefined, dark: undefined },
          bubbles: true,
          composed: true,
        }),
      ),
    theme,
  );
}

async function seedShowcase(page) {
  await page.evaluate(
    async ([list, summary]) => {
      const { hass } = document.querySelector("home-assistant");
      const listed = await hass.callWS({ type: "todo/item/list", entity_id: list });
      if (listed.items.length === 0) await hass.callService("todo", "add_item", { item: summary }, { entity_id: list });
    },
    [SHOWCASE_LIST, SHOWCASE_TODO],
  );
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
  };
}

function dialogOpened(prepare) {
  return async (page) => {
    await prepare(page);
    await expect(page.locator(DIALOG).first()).toHaveCSS("opacity", "1");
  };
}

async function dockSidebar(page) {
  const collapsed = await page.evaluate(() => window.localStorage.getItem("dockedSidebar") === '"auto"');
  if (collapsed) {
    await page.evaluate(() => window.localStorage.setItem("dockedSidebar", '"docked"'));
    await gotoOnion(page, page.url());
    await expect(page.locator(SHELL)).toBeVisible({ timeout: resolveTimeout(90_000) });
  }
}

function settled(views) {
  return views.map((view) => ({
    ...view,
    prepare: async (page) => {
      await view.prepare(page);
      await page.waitForLoadState("networkidle");
      await animationsSettled(page);
    },
  }));
}

function signedIn(views) {
  return settled(
    views.map((view) => ({
      ...view,
      prepare: async (page) => {
        await expect(page.locator(SHELL)).toBeVisible({ timeout: resolveTimeout(90_000) });
        await dockSidebar(page);
        await expect(page.locator("hass-loading-screen:visible")).toHaveCount(0);
        await view.prepare(page);
      },
    })),
  );
}

function signInViews(base) {
  return [
    { name: "sign-in", url: `${base}/`, prepare: shown(SIGN_IN_FORM) },
    {
      name: "sign-in-focus",
      url: `${base}/`,
      prepare: async (page) => {
        await shown(SIGN_IN_FORM)(page);
        await page.locator(LOG_IN).focus();
      },
    },
    { name: "sign-in-error", url: `${base}/auth/authorize`, prepare: shown("ha-authorize ha-alert") },
  ];
}

function signedInViews(base) {
  const panel = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  const integrations = "ha-config-integrations-dashboard";
  return [
    panel("overview", "/home/overview", "ha-panel-home hui-root"),
    panel("energy", "/energy", "ha-panel-energy hui-root"),
    panel("activity", "/logbook", "ha-panel-logbook"),
    panel("history", "/history", "ha-panel-history"),
    panel("todo", "/todo", "ha-panel-todo"),
    panel("media", "/media-browser", "ha-panel-media-browser"),
    panel("settings", "/config/dashboard", "ha-config-dashboard ha-config-navigation"),
    panel("settings-system", "/config/system", "ha-config-system-navigation ha-card"),
    panel("settings-people", "/config/person", "ha-config-person ha-card"),
    panel("settings-users", "/config/users", "ha-config-users ha-data-table"),
    panel("settings-dashboards", "/config/lovelace/dashboards", "ha-config-lovelace-dashboards ha-data-table"),
    panel("settings-integrations", "/config/integrations/dashboard", `${integrations} ha-integration-card`),
    panel("settings-automations", "/config/automation/dashboard", "ha-automation-picker ha-data-table"),
    panel("settings-areas", "/config/areas/dashboard", "ha-config-areas-dashboard ha-card"),
    panel("developer-tools", "/config/developer-tools/action", PERFORM),
    panel("profile", "/profile/general", THEME_ROW),
    {
      name: "theme-picker",
      url: `${base}/profile/general`,
      prepare: async (page) => {
        await shown(THEME_ROW)(page);
        await page.locator(`${THEME_ROW} ha-theme-picker`).click();
        await expect(page.locator("ha-combo-box-item", { hasText: OWN_THEME }).first()).toBeVisible();
      },
    },
    {
      name: "more-info",
      url: `${base}/home/overview?more-info-entity-id=sun.sun`,
      prepare: dialogOpened(shown("ha-panel-home hui-root")),
    },
    {
      name: "add-integration",
      url: `${base}/config/integrations/dashboard`,
      prepare: dialogOpened(async (page) => {
        await shown(`${integrations} ha-integration-card`)(page);
        await page.locator(`${integrations} ha-button[slot="fab"]`).click();
      }),
    },
    {
      name: "quick-bar",
      url: `${base}/config/dashboard`,
      prepare: dialogOpened(async (page) => {
        await shown("ha-config-dashboard ha-config-navigation")(page);
        await page.locator("ha-config-dashboard #button-quick-bar").click();
      }),
    },
    {
      name: "navigation",
      url: `${base}/home/overview`,
      prepare: async (page) => {
        await shown("ha-panel-home hui-root")(page);
        const sidebar = page.locator(SIDEBAR);
        if (page.viewportSize().width < NARROW_BELOW) {
          await page.locator("ha-panel-home ha-menu-button").click();
          await expect(sidebar).toHaveAttribute("expanded", "");
        } else {
          await expect(sidebar).toHaveAttribute("expanded", "");
          await sidebar.getByRole("button", { name: SIDEBAR_TOGGLE }).click();
          await expect(sidebar).not.toHaveAttribute("expanded");
        }
      },
    },
  ];
}

exports.register = function (shared) {
  const base = shared.env.baseUrl;

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.openSignIn(page);
    await assertDesignTokens(page, "homeassistant");
  });

  test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await shared.openSignIn(page);
      await assertToken(page, "html", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, "ha-authorize h1", "color", "--design-text", `sign-in ${mode}`);
      await assertToken(page, LOG_IN, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, LOG_IN, "color", "--design-on-primary", `sign-in ${mode}`);
      await assertContrast(page, SIGN_IN_TEXTS, `sign-in ${mode}`);
      await page.locator(LOG_IN).hover();
      await assertToken(page, LOG_IN, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "ha-authorize", "homeassistant sign-in");
    await assertReadable(page, ["ha-authorize"], "homeassistant sign-in");
  });

  test("design: the corporate theme is the default theme of the hub", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const manifest = await apiGetOnion(page.request, `${base}/manifest.json`);
    expect(manifest.ok(), "the hub serves its web app manifest").toBe(true);
    expect(
      (await manifest.json()).theme_color,
      "the manifest carries the primary color of the default theme once the hub selected the corporate theme",
    ).toBe(decodeDotenvQuotedValue(process.env.DESIGN_THEME_COLOR));
  });

  test("design: the signed-in interface takes surface, primary action and text from the corporate theme", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    const theme = decodeDotenvQuotedValue(process.env.DESIGN_THEME);
    await shared.signIn(page);
    await selectTheme(page, "");
    await expect
      .poll(() => themeState(page), { message: "a user who picked no theme must get the corporate theme" })
      .toMatchObject({ applied: theme, standard: theme, standardDark: theme });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/config/developer-tools/action`);
      await expect(page.locator(PERFORM)).toBeVisible({ timeout: resolveTimeout(60_000) });
      await animationsSettled(page);
      await assertToken(page, "html", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, SIDEBAR, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, `${ACTIONS} ha-card`, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, `${ACTIONS} .header-title`, "color", "--design-text", `shell ${mode}`);
      await assertToken(page, PERFORM, "background-color", "--design-primary", `shell ${mode}`);
      await assertToken(page, PERFORM, "color", "--design-on-primary", `shell ${mode}`);
      await assertContrast(page, SHELL_TEXTS, `shell ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "home-assistant", "homeassistant shell");
    await assertReadable(page, ["home-assistant"], "homeassistant shell");
  });

  test("design: a mode and a theme picked in the profile are respected and mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await shared.signIn(page);
    await gotoOnion(page, `${base}/profile/general`);
    const row = page.locator(THEME_ROW);
    const html = page.locator("html");
    await expect(row).toBeVisible({ timeout: resolveTimeout(60_000) });
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");
    await expect(html, "the corporate theme follows the browser preference").not.toHaveAttribute("data-design-theme");

    try {
      await row.getByRole("radio", { name: "Dark" }).click();
      await expect(html).toHaveAttribute("data-design-theme", "dark");
      expect(
        await tokenValue(page, "--design-surface-1", "background-color"),
        "a dark mode picked in the profile must switch the tokens while the browser prefers light",
      ).not.toBe(lightSurface);
      await assertToken(page, "html", "background-color", "--design-surface-1", "dark mode picked in the profile");
      await assertToken(page, PROFILE_CARD, "background-color", "--design-surface-2", "dark mode picked in the profile");

      await row.getByRole("radio", { name: "Light" }).click();
      await expect(html, "a mode that equals the browser preference needs no override").not.toHaveAttribute(
        "data-design-theme",
      );
      await page.emulateMedia({ colorScheme: "dark" });
      await expect(html).toHaveAttribute("data-design-theme", "light");
      expect(
        await tokenValue(page, "--design-surface-1", "background-color"),
        "a light mode picked in the profile must keep the light tokens while the browser prefers dark",
      ).toBe(lightSurface);
      await assertToken(page, PROFILE_CARD, "background-color", "--design-surface-2", "light mode picked in the profile");
      await page.emulateMedia({ colorScheme: "light" });

      await row.locator("ha-theme-picker").click();
      await page.locator("ha-combo-box-item", { hasText: OWN_THEME }).first().click();
      await expect.poll(async () => (await themeState(page)).applied, { message: "the picked theme must apply" }).toBe("default");
      await expect(page.locator(PROFILE_CARD).first(), "a theme picked in the profile must keep its own palette").not.toHaveCSS(
        "background-color",
        await tokenValue(page, "--design-surface-2", "background-color"),
      );
    } finally {
      await selectTheme(page, "");
    }
    await expect
      .poll(async () => (await themeState(page)).applied, { message: "the corporate theme must apply again" })
      .toBe(decodeDotenvQuotedValue(process.env.DESIGN_THEME));
  });

  test("design: the hub shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

    await shared.openSignIn(page);
    if (title) await expect(page).toHaveTitle(title);
    if (logoUrl) {
      await expect(page.locator(".header img")).toHaveCSS("content", `url("${logoUrl}")`);
      await expect(page.locator("link[rel='icon']")).toHaveAttribute("href", faviconUrl);
      for (const url of [logoUrl, faviconUrl]) {
        expect(
          await page.evaluate(
            (src) =>
              new Promise((resolve) => {
                const image = new Image();
                image.onload = () => resolve(image.naturalWidth > 0);
                image.onerror = () => resolve(false);
                image.src = src;
              }),
            url,
          ),
          `the page must be allowed to load ${url}`,
        ).toBe(true);
      }
    }

    await shared.signIn(page);
    await gotoOnion(page, `${base}/profile/general`);
    await expect(page.locator(THEME_ROW)).toBeVisible({ timeout: resolveTimeout(60_000) });
    if (title) {
      await expect
        .poll(() => page.title(), { message: "the title of a signed-in page must carry the configured title" })
        .toContain(title);
      expect((await themeState(page)).location, "the onboarding must name the hub after the configured title").toBe(title);
    }
    if (logoUrl) await expect(page.locator("link[rel='icon']")).toHaveAttribute("href", faviconUrl);
  });

  test("design: gallery of sign-in, panels, settings and dialogs", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));

    await shared.openSignIn(page);
    await captureDesignGallery(page, settled(signInViews(base)));

    await shared.signIn(page);
    await selectTheme(page, "");
    await seedShowcase(page);
    await captureDesignGallery(page, signedIn(signedInViews(base)));
  });
};
