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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, escapeRegex, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const SUBMIT = "form input[type=submit]";
const SIDEBAR = "aside[data-slot='sidebar']";
const LAYOUT = `div:has(> div > ${SIDEBAR})`;
const HEADER = "header:has(> [data-slot='breadcrumb'])";
const ENTRY = `${SIDEBAR} [data-slot='sidebar-menu-item'] > a`;
const SELECTED = `${ENTRY}[data-active]`;
const UNSELECTED = `${ENTRY}:not([data-active])`;
const OPEN_NAVIGATION = "button[aria-label='Open navigation']";
const ACCOUNT_MENU = `${SIDEBAR} button[aria-label^='Account menu']`;
const POPOVER = "[data-slot='popover-content']";
const THEME_TOGGLE = `${HEADER} button[aria-label^='Switch to']:visible`;
const PROBE_ID = "design-palette-probe";
const PROBE = `#${PROBE_ID}`;
const LIGHT_ONLY_CHIP = `${PROBE} > .text-amber-700`;
const DARK_BOX = `${PROBE} > .bg-purple-50`;
const BOXED_CHIP = `${DARK_BOX} > .text-purple-700`;
const WHITE_BUTTON = `${PROBE} > .text-white`;
const GRADIENT_BOX = `${PROBE} > .from-blue-50`;
const CODE_TEXT = `${PROBE} > [class*='bg-[#1e1e1e]'] > .text-gray-200`;
const CODE_LINE = `${PROBE} > [class*='bg-[#1e1e1e]'] > .text-muted-foreground`;
const STATUS_TILE = `${PROBE} > .from-teal-400`;
const STATUS_AVATAR = `${PROBE} > .bg-info`;
const PROBE_MARKUP = [
  '<span class="border text-amber-700 bg-amber-50 border-amber-200">Via tool permissions</span>',
  '<div class="bg-purple-50 dark:bg-purple-950"><span class="text-purple-700 bg-purple-50">Agent</span></div>',
  '<button type="button" class="bg-gray-900 text-white">Continue</button>',
  '<div class="bg-linear-to-r from-blue-50 dark:from-blue-950">Code Interpreter</div>',
  '<div class="bg-[#1e1e1e]"><span class="text-muted-foreground">1</span><span class="text-gray-200">def apply_guardrail():</span></div>',
  '<div class="bg-linear-to-br from-teal-400 to-cyan-600 text-white">L</div>',
  '<span class="bg-info text-white">G</span>',
].join("");
const CREATE_KEY = "[data-testid='create-key-button']";
const CREATE_TEAM = "[data-testid='create-team-button']";
const MODAL = "[data-slot='dialog-content']";
const MODAL_SUBMIT = `${MODAL} button[type=submit]`;
const FIELD_LABEL = `${MODAL} [data-slot='field-label']`;
const RADIO_LABEL = `${MODAL} label:has([data-slot='radio-group-item'])`;
const AGENT_BOX = `${MODAL} .bg-purple-50`;
const AGENT_LABEL = `${AGENT_BOX} label[for='create-key-agent']`;
const SELECT = `${MODAL} [data-slot='select-trigger']`;
const DROPDOWN = "[data-slot='select-content']";
const CARD = "[data-slot='card']";
const TEXT_FIELD = `${MODAL} [data-slot='input']:not([type='number'])`;
const NUMBER_FIELD = `${MODAL} [data-slot='input'][type='number']`;
const SELECT_FIELD = "[data-slot='select-trigger']";
const CODE_BLOCK = "pre:has(> code[class*='language-'])";
const SHOWCASE_TEAM = "Design Review";
const SHOWCASE_KEY = "design-showcase";
const PANELS = [
  ["keys", "api-keys"],
  ["test-key", "playground"],
  ["models", "models-and-endpoints"],
  ["usage", "usage"],
  ["teams", "teams"],
  ["organizations", "organizations"],
  ["users", "users"],
  ["model-hub", "model-hub-table"],
  ["logs", "logs"],
  ["mcp-servers", "mcp-servers"],
  ["caching", "caching"],
  ["budgets", "budgets"],
  ["tags", "tag-management"],
  ["router-settings", "router-settings"],
  ["logging-alerts", "logging-and-alerts"],
  ["admin-settings", "admin-panel"],
  ["ui-theme", "ui-theme"],
];

/**
 * Args:
 *   base: base URL of the admin UI.
 *   route: route segment of the panel, as the sidebar links it.
 *
 * Returns:
 *   The panel URL with the trailing slash the static export serves its index.html under.
 */
function panelUrl(base, route) {
  return `${base}/ui/${route}/`;
}

/**
 * Args:
 *   page: Playwright page whose finite animations must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            new Promise((resolve) => {
              requestAnimationFrame(() =>
                requestAnimationFrame(() =>
                  resolve(
                    document
                      .getAnimations()
                      .some(
                        (animation) =>
                          animation.playState === "running" &&
                          animation.effect?.getComputedTiming().iterations !== Infinity,
                      ),
                  ),
                ),
              );
            }),
        ),
      { message: "every finite animation of the page must have ended" },
    )
    .toBe(false);
}

/**
 * Args:
 *   page: Playwright page that shows a signed-in view whose data must have arrived; the header is the shell part every viewport shows.
 */
async function ready(page) {
  await expect(page.locator(HEADER)).toBeVisible({ timeout: resolveTimeout(60_000) });
  await page.waitForLoadState("networkidle");
  await expect(page.locator(".animate-spin:visible")).toHaveCount(0);
  await animationsSettled(page);
}

/**
 * Args:
 *   page: Playwright page that shows a signed-in view; below the desktop breakpoint the sidebar lives in a sheet that this opens.
 */
async function showNavigation(page) {
  if (await page.locator(`${SIDEBAR}:visible`).count()) return;
  await page.locator(OPEN_NAVIGATION).click();
  await expect(page.locator(`${SIDEBAR}:visible`)).toHaveCount(1);
  await animationsSettled(page);
}

function opened(selector, trigger) {
  return async (page) => {
    await ready(page);
    await trigger(page);
    const panel = page.locator(selector).first();
    await expect(panel).toBeVisible();
    await animationsSettled(page);
    await expect(panel).toHaveCSS("opacity", "1");
  };
}

async function openKeyDialog(page) {
  await page.locator(CREATE_KEY, { hasText: "Create New Key" }).first().click();
}

async function openTeamDialog(page) {
  await page.locator(CREATE_TEAM, { hasText: "Create Team" }).first().click();
}

async function openAccountMenu(page) {
  await showNavigation(page);
  await page.locator(`${ACCOUNT_MENU}:visible`).click();
}

async function openExamples(page) {
  await page.getByRole("tab", { name: "Examples" }).click();
  await expect(page.locator(CODE_BLOCK).first()).toBeVisible();
  await animationsSettled(page);
}

/**
 * Args:
 *   page: Playwright page that is signed in to the admin UI.
 *   base: base URL of the admin UI.
 */
async function seedShowcase(page, base) {
  const token = (await page.context().cookies()).find((cookie) => cookie.name === "token");
  expect(token, "the sign-in must leave the session token cookie").toBeTruthy();
  const session = JSON.parse(Buffer.from(token.value.split(".")[1], "base64url").toString("utf8"));
  const headers = { Authorization: `Bearer ${session.key}` };
  const teams = await (await apiGetOnion(page.request, `${base}/team/list`, { headers })).json();
  let team = teams.find((entry) => entry.team_alias === SHOWCASE_TEAM);
  if (!team) {
    const created = await apiFetchOnion(page.request, `${base}/team/new`, {
      method: "POST",
      headers,
      data: { team_alias: SHOWCASE_TEAM, max_budget: 25 },
    });
    expect(created.ok(), "seeding the showcase team").toBe(true);
    team = await created.json();
  }
  const keys = await (await apiGetOnion(page.request, `${base}/key/list?key_alias=${SHOWCASE_KEY}`, { headers })).json();
  if (keys.keys.length === 0) {
    const created = await apiFetchOnion(page.request, `${base}/key/generate`, {
      method: "POST",
      headers,
      data: { key_alias: SHOWCASE_KEY, team_id: team.team_id, max_budget: 10 },
    });
    expect(created.ok(), "seeding the showcase key").toBe(true);
  }
}

function signInViews(base) {
  const url = `${base}/fallback/login`;
  return [
    { name: "sign-in", url },
    { name: "sign-in-focus", url, prepare: (page) => page.locator("#username").focus() },
    { name: "sign-in-hover", url, prepare: (page) => page.locator(SUBMIT).hover() },
  ];
}

function signedInViews(base) {
  const panel = (route) => panelUrl(base, route);
  return [
    ...PANELS.map(([name, route]) => ({ name, url: panel(route), prepare: ready })),
    { name: "key-create", url: panel("api-keys"), prepare: opened(MODAL, openKeyDialog) },
    {
      name: "key-create-select",
      url: panel("api-keys"),
      prepare: opened(DROPDOWN, async (page) => {
        await openKeyDialog(page);
        await expect(page.locator(MODAL).first()).toBeVisible();
        await animationsSettled(page);
        await page.locator(SELECT).first().click();
      }),
    },
    { name: "team-create", url: panel("teams"), prepare: opened(MODAL, openTeamDialog) },
    {
      name: "model-add",
      url: panel("models-and-endpoints"),
      prepare: async (page) => {
        await ready(page);
        await page.getByRole("tab", { name: "Add Model" }).first().click();
        await expect(page.locator("[data-slot='tabs-content']:visible").first()).toBeVisible();
        await ready(page);
      },
    },
    { name: "user-menu", url: panel("api-keys"), prepare: opened(POPOVER, openAccountMenu) },
    {
      name: "navigation",
      url: panel("api-keys"),
      prepare: async (page) => {
        await ready(page);
        await showNavigation(page);
        await page.locator(`${UNSELECTED}:visible`).first().hover();
      },
    },
  ];
}

exports.register = function (shared) {
  const base = shared.env.baseUrl;

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.openSignIn(page);
    await assertDesignTokens(page, "litellm");
  });

  test("design: the sign-in form takes surface, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await shared.openSignIn(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, "form", "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, "form h2", "color", "--design-text", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await page.locator(SUBMIT).hover();
      await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "form", "litellm sign-in");
    await assertReadable(page, ["form h2", "form .subtitle", "form label", SUBMIT], "litellm sign-in");
  });

  test("design: the signed-in shell takes surfaces, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.signIn(page);
    await seedShowcase(page, base);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, panelUrl(base, "api-keys"));
      await ready(page);
      await expect(page.locator(CREATE_KEY).first()).toContainText("Create New Key");
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, LAYOUT, "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, HEADER, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, SIDEBAR, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, SELECTED, "background-color", "--design-surface-active", `shell ${mode}`);
      await assertToken(page, SELECTED, "color", "--design-link", `shell ${mode}`);
      await assertToken(page, UNSELECTED, "color", "--design-text", `shell ${mode}`);
      await assertToken(page, CREATE_KEY, "background-color", "--design-primary", `shell ${mode}`);
      await assertToken(page, CREATE_KEY, "color", "--design-on-primary", `shell ${mode}`);
      await page.locator(UNSELECTED).first().hover();
      await assertToken(page, UNSELECTED, "background-color", "--design-surface-hover", `hovered entry ${mode}`);
      await page.locator(CREATE_KEY).first().hover();
      await assertToken(page, CREATE_KEY, "background-color", "--design-primary-hover", `hovered action ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, HEADER, "litellm shell");
    await assertLightAndDark(page, SIDEBAR, "litellm shell");
    await assertReadable(
      page,
      [
        `${HEADER} [data-slot='breadcrumb-page']`,
        `${SELECTED} > span`,
        `${UNSELECTED} > span`,
        CREATE_KEY,
        "table th",
        { selector: "table td", optional: true },
      ],
      "litellm shell",
    );
  });

  test("design: dialogs, form fields and dropdowns take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, panelUrl(base, "api-keys"));
      await opened(MODAL, openKeyDialog)(page);
      await expect(page.locator("html"), `the app must render its ${mode} variants`).toHaveClass(
        new RegExp(`(^|\\s)${mode}(\\s|$)`),
      );
      await assertToken(page, MODAL, "background-color", "--design-surface-2", `dialog ${mode}`);
      await assertToken(page, FIELD_LABEL, "color", "--design-text", `dialog ${mode}`);
      await assertToken(page, SELECT, "background-color", "--design-surface-2", `dialog ${mode}`);
      await assertToken(page, SELECT, "border-top-color", "--design-border-strong", `dialog ${mode}`);
      await assertToken(page, MODAL_SUBMIT, "background-color", "--design-primary", `dialog ${mode}`);
      await assertToken(page, TEXT_FIELD, "border-top-color", "--design-border-strong", `dialog ${mode}`);
      await assertToken(page, MODAL_SUBMIT, "color", "--design-on-primary", `dialog ${mode}`);
      await page.locator(RADIO_LABEL).filter({ hasText: /^Agent/ }).click();
      await expect(page.locator(AGENT_BOX)).toBeVisible();
      await expect(page.locator(AGENT_BOX)).toHaveClass(/dark:bg-purple-950/);
      await assertToken(page, AGENT_BOX, "background-color", "--design-info-subtle", `agent box ${mode}`);
      await assertToken(page, AGENT_BOX, "border-top-color", "--design-info-border", `agent box ${mode}`);
      await page.locator(SELECT).first().click();
      await expect(page.locator(DROPDOWN).first()).toBeVisible();
      await animationsSettled(page);
      await assertToken(page, DROPDOWN, "background-color", "--design-surface-2", `dropdown ${mode}`);
      await page.keyboard.press("Escape");
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, MODAL, "litellm dialog");
    await assertReadable(page, [FIELD_LABEL, RADIO_LABEL, AGENT_LABEL, MODAL_SUBMIT], "litellm dialog");
  });

  test("design: code samples take surface and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, panelUrl(base, "budgets"));
      await ready(page);
      await openExamples(page);
      await assertToken(page, CODE_BLOCK, "background-color", "--design-surface-3", `code sample ${mode}`);
      await assertToken(page, `${CODE_BLOCK} > code`, "color", "--design-text", `code sample ${mode}`);
      await expect(page.locator(`${CODE_BLOCK} > code`).first()).toHaveCSS("text-shadow", "none");
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, CODE_BLOCK, "litellm code sample");
    await assertReadable(page, [`${CODE_BLOCK} > code`, `${CODE_BLOCK} .token`], "litellm code sample");
  });

  test("design: card outlines, field boundaries and focused text fields keep the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, panelUrl(base, "ui-theme"));
      await ready(page);
      const outline = escapeRegex(await tokenValue(page, "--design-border", "color"));
      await expect(
        page.locator(CARD).first(),
        `card ${mode}: the outline ring must take --design-border`,
      ).toHaveCSS("box-shadow", new RegExp(`${outline} 0px 0px 0px 1px`));

      await gotoOnion(page, panelUrl(base, "api-keys"));
      await opened(MODAL, openKeyDialog)(page);
      await assertToken(page, TEXT_FIELD, "border-top-color", "--design-border-strong", `text field ${mode}`);
      await page.locator(TEXT_FIELD).first().focus();
      await expect(page.locator(TEXT_FIELD).first()).toBeFocused();
      await assertToken(page, TEXT_FIELD, "border-top-color", "--design-link", `focused text field ${mode}`);
      await assertToken(page, TEXT_FIELD, "background-color", "--design-surface-2", `focused text field ${mode}`);

      await gotoOnion(page, panelUrl(base, "teams"));
      await opened(MODAL, openTeamDialog)(page);
      await assertToken(page, NUMBER_FIELD, "border-top-color", "--design-border-strong", `number field ${mode}`);

      await gotoOnion(page, panelUrl(base, "router-settings"));
      await ready(page);
      await assertToken(page, SELECT_FIELD, "border-top-color", "--design-border-strong", `select field ${mode}`);
    }
  });

  test("design: the admin UI shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

    await shared.openSignIn(page);
    if (title) await expect(page).toHaveTitle(title);
    if (logoUrl) {
      await expect(page.locator("form .logo")).toHaveCSS("background-image", `url("${logoUrl}")`);
      await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    }

    await shared.signIn(page);
    if (title) await expect(page).toHaveTitle(title);
    if (logoUrl) {
      const settings = await (await apiGetOnion(page.request, `${base}/get/ui_theme_settings`)).json();
      expect(settings.values.logo_url, "LiteLLM's own logo_url setting must carry the corporate lockup").toBe(logoUrl);
      const brand = page.locator(shared.SHELL);
      await expect(brand, "the sidebar must take its logo from the setting").toHaveAttribute("src", logoUrl);
      await expect(brand, "no stylesheet may swap the sidebar logo").toHaveCSS("content", "normal");
      await expect
        .poll(() => brand.evaluate((image) => image.complete && image.naturalWidth > 0), { message: "the lockup must load" })
        .toBe(true);
      const box = await brand.boundingBox();
      expect(box.width, "the wide lockup must carry the title next to the symbol").toBeGreaterThan(2 * box.height);
      for (const icon of await page.locator("link[rel~='icon']").all()) {
        await expect(icon).toHaveAttribute("href", faviconUrl);
      }
      for (const url of [logoUrl, faviconUrl]) {
        expect((await apiGetOnion(page.request, url)).ok(), `${url} is published on the CDN`).toBe(true);
      }
      await gotoOnion(page, panelUrl(base, "ui-theme"));
      await ready(page);
      await expect(
        page.locator("input[placeholder='https://example.com/logo.png']"),
        "the UI theme page must show the configured logo URL",
      ).toHaveValue(logoUrl);
    }
  });

  test("design: the admin UI theme follows the browser like the palette until the switch carries a choice", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await shared.signIn(page);
    const html = page.locator("html");
    const stored = () => page.evaluate(() => window.localStorage.getItem("theme"));
    expect(await stored(), "the design script must hand the browser choice to next-themes").toBe("system");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, panelUrl(base, "api-keys"));
      await ready(page);
      await expect(html, `the app must follow a ${mode} browser`).toHaveClass(new RegExp(`(^|\\s)${mode}(\\s|$)`));
      await expect(html, "the system choice must leave the palette on the browser").not.toHaveAttribute(
        "data-design-theme",
        /.*/,
      );
      await assertToken(page, "body", "background-color", "--design-surface-1", `system ${mode}`);
      await expect(page.locator(shared.SHELL), `the ${mode} logo must show`).toBeVisible();
      await expect(page.locator(THEME_TOGGLE)).toHaveAttribute(
        "aria-label",
        mode === "dark" ? "Switch to light mode" : /^Switch to dark mode/,
      );
    }

    await page.emulateMedia({ colorScheme: "light" });
    await gotoOnion(page, panelUrl(base, "api-keys"));
    await ready(page);
    const background = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const light = await background();

    await page.locator(THEME_TOGGLE).click();
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    await assertToken(page, "body", "background-color", "--design-surface-1", "theme dark");
    expect(await background(), "the dark choice must change the surface").not.toBe(light);

    await page.locator(THEME_TOGGLE).click();
    await expect(html).toHaveAttribute("data-design-theme", "light");
    await assertToken(page, "body", "background-color", "--design-surface-1", "theme light");
    expect(await background(), "the light choice must restore the surface").toBe(light);

    await page.emulateMedia({ colorScheme: "dark" });
    await gotoOnion(page, panelUrl(base, "api-keys"));
    await ready(page);
    expect(await stored(), "a reload must keep the light choice").toBe("light");
    await expect(html, "a stored light choice must beat a dark browser").toHaveClass(/(^|\s)light(\s|$)/);
    await expect(html).toHaveAttribute("data-design-theme", "light");
    expect(await background(), "a stored light choice must keep the light surface in a dark browser").toBe(light);
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: palette steps flip in dark mode only where the element carries a dark variant", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.signIn(page);
    await gotoOnion(page, panelUrl(base, "api-keys"));
    await ready(page);
    await page.evaluate(
      ([id, markup]) => {
        const probe = document.createElement("div");
        probe.id = id;
        probe.innerHTML = markup;
        document.body.append(probe);
      },
      [PROBE_ID, PROBE_MARKUP],
    );
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("html")).toHaveClass(new RegExp(`(^|\\s)${mode}(\\s|$)`));
      await assertToken(page, LIGHT_ONLY_CHIP, "background-color", "--design-warning-subtle", `light-only chip ${mode}`);
      await assertToken(page, LIGHT_ONLY_CHIP, "color", "--design-warning", `light-only chip ${mode}`);
      await assertToken(page, DARK_BOX, "background-color", "--design-info-subtle", `dark-variant box ${mode}`);
      await assertToken(page, BOXED_CHIP, "background-color", "--design-info-subtle", `chip in a dark-variant box ${mode}`);
      await assertToken(page, BOXED_CHIP, "color", "--design-info", `chip in a dark-variant box ${mode}`);
      await assertToken(
        page,
        WHITE_BUTTON,
        "background-color",
        mode === "dark" ? "--design-surface-hover" : "--design-text",
        `white-text fill ${mode}`,
      );
      await assertToken(page, GRADIENT_BOX, "--tw-gradient-from", "--design-primary-50", `dark-variant gradient ${mode}`);
      const dark = mode === "dark";
      await assertToken(page, CODE_TEXT, "color", dark ? "--design-text" : "--design-border", `code view text ${mode}`);
      await assertToken(
        page,
        CODE_LINE,
        "color",
        dark ? "--design-text-muted" : "--design-border-strong",
        `code view line number ${mode}`,
      );
      for (const stop of ["--tw-gradient-from", "--tw-gradient-to"]) {
        await assertToken(page, STATUS_TILE, stop, dark ? "--design-info-border" : "--design-info", `white tile ${mode}`);
      }
      await assertToken(page, STATUS_AVATAR, "color", "--design-on-info", `white text on a status fill ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(
      page,
      [LIGHT_ONLY_CHIP, BOXED_CHIP, WHITE_BUTTON, CODE_TEXT, CODE_LINE, STATUS_AVATAR],
      "litellm palette steps",
    );
  });

  test("design: gallery of sign-in, administration panels, dialogs and menus", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));

    await shared.openSignIn(page);
    await captureDesignGallery(page, signInViews(base));

    await shared.signIn(page);
    await seedShowcase(page, base);
    await captureDesignGallery(page, signedInViews(base));
  });
};
