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
const { apiGetOnion, decodeDotenvQuotedValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const PAIRING_APPROVAL_MS = 180_000;
const PAIRING_PROBE_MS = 5_000;
const PAIRING_HINT =
  "the gateway holds the pairing request of this browser; approve it with `openclaw devices approve` while the gallery waits";
const SETTINGS_KEY = "openclaw.control.settings.v1:";
const CARD = ".login-gate__card";
const CONNECT = ".login-gate__connect";
const SETTINGS_PAGES = [
  { name: "settings", path: "/settings/general", title: "Settings" },
  { name: "settings-channels", path: "/settings/channels", title: "Channels" },
  { name: "settings-appearance", path: "/settings/appearance", title: "Appearance" },
  { name: "settings-mcp", path: "/settings/mcp", title: "MCP" },
  { name: "settings-infrastructure", path: "/settings/infrastructure", title: "Infrastructure" },
  { name: "settings-ai-agents", path: "/settings/ai-agents", title: "AI & Agents" },
];
const PAGES = [
  { name: "chat", path: "/chat", title: "Chat" },
  { name: "overview", path: "/overview", title: "Overview" },
  { name: "activity", path: "/activity", title: "Activity" },
  { name: "agents", path: "/agents", title: "Agents" },
  { name: "usage", path: "/usage", title: "Usage" },
  { name: "cron", path: "/cron", title: "Cron Jobs" },
  { name: "skills", path: "/skills", title: "Skills" },
  { name: "nodes", path: "/nodes", title: "Nodes" },
  { name: "logs", path: "/logs", title: "Logs" },
  { name: "debug", path: "/debug", title: "Debug" },
  ...SETTINGS_PAGES,
];

function ready(title) {
  return async (page) => {
    await expect(page.locator(".dashboard-header__breadcrumb-current")).toHaveText(title, {
      timeout: resolveTimeout(60_000),
    });
    await expect(page.locator("main .skeleton")).toHaveCount(0);
    await page.waitForLoadState("networkidle");
  };
}

async function openNavigation(page) {
  const toggle = page.locator(".topbar-nav-toggle");
  if (await toggle.isVisible()) await toggle.click();
  await expect(page.locator(".sidebar .nav-item").first()).toBeInViewport();
}

async function expandNavigation(page) {
  const more = page.locator(".nav-section__label");
  if ((await more.getAttribute("aria-expanded")) === "false") await more.click();
  await expect(more).toHaveAttribute("aria-expanded", "true");
}

/**
 * Args:
 *   page: Playwright page that shows the Control UI.
 *
 * Returns:
 *   The settings the Control UI keeps in the browser, as its theme and mode switches store them.
 */
async function storedSettings(page) {
  return page.evaluate((prefix) => {
    const key = Object.keys(window.localStorage).find((name) => name.startsWith(prefix));
    return JSON.parse(window.localStorage.getItem(key));
  }, SETTINGS_KEY);
}

/**
 * Args:
 *   page: Playwright page that shows the Control UI.
 *   choice: theme and mode values to store the way the switches of the Control UI store them.
 */
async function storeSettings(page, choice) {
  await page.evaluate(
    ([prefix, values]) => {
      const key = Object.keys(window.localStorage).find((name) => name.startsWith(prefix));
      window.localStorage.setItem(key, JSON.stringify({ ...JSON.parse(window.localStorage.getItem(key)), ...values }));
    },
    [SETTINGS_KEY, choice],
  );
}

function gateViews(base) {
  const gate = async (page) => {
    await expect(page.locator(".login-gate__failure")).toBeVisible({ timeout: resolveTimeout(60_000) });
  };
  return [
    { name: "login", url: `${base}/`, prepare: gate },
    {
      name: "login-focus",
      url: `${base}/`,
      prepare: async (page) => {
        await gate(page);
        await page.locator(".login-gate__secret-row input").first().focus();
      },
    },
    {
      name: "login-help",
      url: `${base}/`,
      prepare: async (page) => {
        await gate(page);
        await page.locator(".login-gate__help-title").click();
        await expect(page.locator(".login-gate__steps")).toBeVisible();
      },
    },
  ];
}

function dashboardViews(base) {
  return [
    ...PAGES.map(({ name, path, title }) => ({ name, url: `${base}${path}`, prepare: ready(title) })),
    {
      name: "sessions",
      url: `${base}/sessions`,
      prepare: async (page) => {
        await ready("Sessions")(page);
        const showAll = page.getByRole("button", { name: "Show all", exact: true });
        if (await showAll.isVisible()) await showAll.click();
        await expect(page.locator("main .session-key-cell").first()).toBeVisible();
      },
    },
    {
      name: "cron-new",
      url: `${base}/cron`,
      prepare: async (page) => {
        await ready("Cron Jobs")(page);
        await page.getByRole("button", { name: "New Job" }).first().click();
        await expect(page.locator(".cqc-container")).toBeVisible();
      },
    },
    {
      name: "navigation",
      url: `${base}/sessions`,
      prepare: async (page) => {
        await ready("Sessions")(page);
        await openNavigation(page);
        await page.locator(".sidebar .nav-item[href$='/cron']").hover();
      },
    },
    {
      name: "command-palette",
      url: `${base}/overview`,
      prepare: async (page) => {
        await ready("Overview")(page);
        await page.locator(".topbar-search:visible, .sidebar-search:visible").first().click();
        await expect(page.locator(".cmd-palette__item--active")).toBeVisible();
      },
    },
    {
      name: "session-menu",
      url: `${base}/chat`,
      prepare: async (page) => {
        await ready("Chat")(page);
        await openNavigation(page);
        await page.locator(".sidebar-recent-session").first().click({ button: "right" });
        await expect(page.getByRole("menu").last()).toBeVisible();
      },
    },
  ];
}

exports.register = function (shared) {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.openGate(page);
    await assertDesignTokens(page, "openclaw");
  });

  test("design: the corporate theme of the Control UI carries page, primary action and text", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.openGate(page);
    const html = page.locator("html");
    expect(
      (await storedSettings(page)).customTheme.themeId,
      "the theme slot of the Control UI must hold the corporate theme",
    ).toBe(decodeDotenvQuotedValue(process.env.DESIGN_THEME_ID));
    await expect(html, "the Control UI must select its corporate theme").toHaveAttribute("data-theme", /^custom/);
    await expect(html).toHaveAttribute("data-design-corporate", "");

    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(html).toHaveAttribute("data-theme-mode", mode);
      await assertToken(page, shared.GATE, "background-color", "--design-surface-1", `gate ${mode}`);
      await assertToken(page, CARD, "background-color", "--design-surface-2", `gate ${mode}`);
      await assertToken(page, ".login-gate__title", "color", "--design-text", `gate ${mode}`);
      await assertToken(page, CONNECT, "background-color", "--design-primary", `gate ${mode}`);
      await assertToken(page, CONNECT, "color", "--design-on-primary", `gate ${mode}`);
      expect(
        await tokenValue(page, "--accent", "color"),
        `gate ${mode}: the accent of the theme must be the palette link color`,
      ).toBe(await tokenValue(page, "--design-link", "color"));
      expect(
        await tokenValue(page, "--ok", "color"),
        `gate ${mode}: the status colors outside the theme slot must come from the palette`,
      ).toBe(await tokenValue(page, "--design-success", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, CARD, "openclaw gate");
    await expect(page.locator(".login-gate__failure")).toBeVisible({ timeout: resolveTimeout(60_000) });
    await assertReadable(
      page,
      [
        ".login-gate__title",
        ".login-gate__sub",
        ".login-gate__form .field > span",
        ".login-gate__form input",
        CONNECT,
        ".login-gate__failure-title",
        ".login-gate__failure-summary",
        ".login-gate__failure-docs",
        ".login-gate__help-title",
      ],
      "openclaw gate",
    );
  });

  test("design: the mode and the theme stored by the Control UI decide the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await shared.openGate(page);
    const html = page.locator("html");
    const gate = page.locator(shared.GATE);
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");
    await expect(html, "the corporate theme follows the browser preference").not.toHaveAttribute("data-design-theme");

    await storeSettings(page, { themeMode: "dark" });
    await shared.openGate(page);
    await expect(html).toHaveAttribute("data-theme-mode", "dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(
      await tokenValue(page, "--design-surface-1", "background-color"),
      "a dark mode chosen in the Control UI must switch the tokens while the browser prefers light",
    ).not.toBe(lightSurface);
    await assertToken(page, shared.GATE, "background-color", "--design-surface-1", "dark mode chosen in the Control UI");

    await storeSettings(page, { themeMode: "system", theme: "knot" });
    await shared.openGate(page);
    await expect(html).toHaveAttribute("data-theme", "openknot-light");
    await expect(html).not.toHaveAttribute("data-design-corporate");
    await expect(gate, "a theme chosen in the Control UI must keep its own palette").not.toHaveCSS(
      "background-color",
      lightSurface,
    );
    await expect(page.locator(CONNECT)).not.toHaveCSS(
      "background-color",
      await tokenValue(page, "--design-primary", "background-color"),
    );
    expect((await storedSettings(page)).theme, "a chosen theme must survive the next visit").toBe("knot");

    await storeSettings(page, { theme: "custom" });
    await shared.openGate(page);
    await expect(html).toHaveAttribute("data-design-corporate", "");
    await assertToken(page, shared.GATE, "background-color", "--design-surface-1", "corporate theme chosen again");
  });

  test("design: the Control UI serves the generated logo and shows the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

    await shared.openGate(page);
    if (logoUrl) {
      const served = await apiGetOnion(page.request, `${shared.env.baseUrl}/favicon.svg`);
      const generated = await apiGetOnion(page.request, logoUrl);
      expect(served.ok(), "the Control UI serves a logo").toBe(true);
      expect(generated.ok(), "the generated logo is published on the CDN").toBe(true);
      expect(await served.text(), "the Control UI must serve the generated corporate logo").toBe(await generated.text());
      await expect
        .poll(() => page.locator(".login-gate__logo").evaluate((image) => image.naturalWidth), {
          message: "the login gate must render the served logo",
        })
        .toBeGreaterThan(0);
    }
    if (title) {
      await expect(page).toHaveTitle(title);
      expect(
        await page.locator(".login-gate__title").evaluate((element) => getComputedStyle(element, "::after").content),
        "the login gate must show the configured title",
      ).toBe(JSON.stringify(title));
      await expect(page.locator(".login-gate__title")).toHaveCSS("font-size", "0px");
    }
  });

  test("design: the dashboard takes the palette and its own switches decide it", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    test.skip(!(await shared.openDashboard(page, "/overview", PAIRING_PROBE_MS)), PAIRING_HINT);
    await ready("Overview")(page);
    await expandNavigation(page);
    const html = page.locator("html");
    const toggle = page.locator(".theme-mode-toggle");
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");

    await assertToken(page, "body", "background-color", "--design-surface-1", "dashboard");
    await assertToken(page, "main .card", "background-color", "--design-surface-2", "dashboard card");
    await assertToken(page, ".nav-item--active", "background-color", "--design-surface-active", "selected navigation");
    await assertReadable(
      page,
      [
        ".sidebar-brand__title",
        ".nav-item--active .nav-item__text",
        ".nav-item:not(.nav-item--active) .nav-item__text",
        ".nav-section__label-text",
        ".dashboard-header__breadcrumb-link",
        ".dashboard-header__breadcrumb-current",
        ".sidebar-recent-session__name",
      ],
      "openclaw dashboard",
    );

    await expect(toggle).toHaveAttribute("aria-label", /System/);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-label", /Light/);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-label", /Dark/);
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(
      await tokenValue(page, "--design-surface-1", "background-color"),
      "the dark mode of the toggle must switch the tokens while the browser prefers light",
    ).not.toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "dark mode of the toggle");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-label", /System/);
    await expect(html).not.toHaveAttribute("data-design-theme");

    await shared.open(page, "/settings/appearance");
    await ready("Appearance")(page);
    const corporate = (await storedSettings(page)).customTheme.label;
    await page.getByRole("button", { name: "Knot", exact: true }).first().click();
    await expect(html).toHaveAttribute("data-theme", "openknot-light");
    await expect(html).not.toHaveAttribute("data-design-corporate");
    await expect(page.locator("body"), "a theme chosen in the dashboard must keep its own palette").not.toHaveCSS(
      "background-color",
      lightSurface,
    );
    await page.getByRole("button", { name: corporate, exact: true }).first().click();
    await expect(html).toHaveAttribute("data-design-corporate", "");
    await assertToken(page, "body", "background-color", "--design-surface-1", "corporate theme chosen again");
  });

  test("design: gallery of login gate, dashboard and settings views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    const base = shared.env.baseUrl;

    await shared.openGate(page);
    await captureDesignGallery(page, gateViews(base));

    test.skip(!(await shared.openDashboard(page, "/overview", PAIRING_APPROVAL_MS)), PAIRING_HINT);
    await expandNavigation(page);
    await captureDesignGallery(page, dashboardViews(base));
  });
};
