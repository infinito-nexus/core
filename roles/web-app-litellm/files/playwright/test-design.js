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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const SUBMIT = "form input[type=submit]";
const NAVBAR = "nav";
const SIDEBAR = ".ant-layout-sider";
const SELECTED = `${SIDEBAR} .ant-menu-item-selected`;
const UNSELECTED = `${SIDEBAR} .ant-menu-item:not(.ant-menu-item-selected)`;
const CREATE_KEY = "button.tremor-Button-root";
const MODAL = ".ant-modal-content";
const MODAL_SUBMIT = `${MODAL} button[type=submit]`;
const SELECT = `${MODAL} .ant-select-selector`;
const CARD = ".tremor-Card-root";
const TEXT_FIELD = `${MODAL} .tremor-TextInput-root`;
const NUMBER_FIELD = `${MODAL} .tremor-NumberInput-root`;
const SELECT_FIELD = "button[id^='headlessui-listbox-button']";
const CODE_BLOCK = "pre:has(> code[class*='language-'])";
const NARROW_BELOW = 768;
const SHOWCASE_TEAM = "Design Review";
const SHOWCASE_KEY = "design-showcase";
const PANELS = [
  ["keys", "api-keys"],
  ["test-key", "llm-playground"],
  ["models", "models"],
  ["usage", "new_usage"],
  ["teams", "teams"],
  ["organizations", "organizations"],
  ["users", "users"],
  ["model-hub", "model-hub-table"],
  ["logs", "logs"],
  ["mcp-servers", "mcp-servers"],
  ["caching", "caching"],
  ["budgets", "budgets"],
  ["tags", "tag-management"],
  ["router-settings", "general-settings"],
  ["logging-alerts", "settings"],
  ["admin-settings", "admin-panel"],
  ["ui-theme", "ui-theme"],
];

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
 *   page: Playwright page that shows a signed-in view whose data must have arrived.
 */
async function loaded(page) {
  await expect(page.locator(SIDEBAR)).toBeVisible({ timeout: resolveTimeout(60_000) });
  await page.waitForLoadState("networkidle");
  await expect(page.locator(".ant-spin-spinning:visible, .animate-spin:visible")).toHaveCount(0);
  await animationsSettled(page);
}

/**
 * Args:
 *   page: Playwright page that shows a signed-in view; a narrow viewport gets the sidebar collapsed so the panel is visible.
 */
async function ready(page) {
  await loaded(page);
  const collapse = page.locator(`${NAVBAR} button[title='Collapse sidebar']`);
  if (page.viewportSize().width < NARROW_BELOW && (await collapse.count()) > 0) {
    await collapse.click();
    await expect(page.locator(SIDEBAR)).toHaveClass(/ant-layout-sider-collapsed/);
    await animationsSettled(page);
  }
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
  await page.getByRole("button", { name: /Create New Team/ }).first().click();
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
  const panel = (key) => `${base}/ui/?page=${key}`;
  return [
    ...PANELS.map(([name, key]) => ({ name, url: panel(key), prepare: ready })),
    { name: "key-create", url: panel("api-keys"), prepare: opened(MODAL, openKeyDialog) },
    {
      name: "key-create-select",
      url: panel("api-keys"),
      prepare: opened(".ant-select-dropdown:not(.ant-select-dropdown-hidden)", async (page) => {
        await openKeyDialog(page);
        await expect(page.locator(MODAL).first()).toBeVisible();
        await animationsSettled(page);
        await page.locator(SELECT).first().click();
      }),
    },
    { name: "team-create", url: panel("teams"), prepare: opened(MODAL, openTeamDialog) },
    {
      name: "model-add",
      url: panel("models"),
      prepare: async (page) => {
        await ready(page);
        await page.getByRole("tab", { name: "Add Model" }).first().click();
        await expect(page.locator(".ant-form").first()).toBeVisible();
        await loaded(page);
      },
    },
    {
      name: "user-menu",
      url: panel("api-keys"),
      prepare: opened(".ant-dropdown:not(.ant-dropdown-hidden)", (page) =>
        page.locator(`${NAVBAR} button`, { hasText: "User" }).hover(),
      ),
    },
    {
      name: "navigation",
      url: panel("api-keys"),
      prepare: async (page) => {
        await loaded(page);
        await page.locator(UNSELECTED).first().hover();
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
    await assertReadable(
      page,
      ["form h2", "form .subtitle", "form label", "form .info-header", "form .info-box p", "form .info-box a", SUBMIT],
      "litellm sign-in",
    );
  });

  test("design: the signed-in shell takes surfaces, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.signIn(page);
    await seedShowcase(page, base);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/ui/?page=api-keys`);
      await ready(page);
      await expect(page.locator(CREATE_KEY).first()).toContainText("Create New Key");
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, ".ant-layout", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, NAVBAR, "background-color", "--design-surface-2", `shell ${mode}`);
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
    await assertLightAndDark(page, NAVBAR, "litellm shell");
    await assertLightAndDark(page, SIDEBAR, "litellm shell");
    await assertReadable(
      page,
      [
        `${NAVBAR} a`,
        `${SELECTED} .ant-menu-title-content`,
        `${UNSELECTED} .ant-menu-title-content`,
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
      await gotoOnion(page, `${base}/ui/?page=api-keys`);
      await opened(MODAL, openKeyDialog)(page);
      await assertToken(page, MODAL, "background-color", "--design-surface-2", `dialog ${mode}`);
      await assertToken(page, `${MODAL} .ant-form-item-label > label`, "color", "--design-text", `dialog ${mode}`);
      await assertToken(page, SELECT, "background-color", "--design-surface-2", `dialog ${mode}`);
      await assertToken(page, SELECT, "border-top-color", "--design-border-strong", `dialog ${mode}`);
      await assertToken(page, MODAL_SUBMIT, "background-color", "--design-surface-2", `dialog ${mode}`);
      await assertToken(page, MODAL_SUBMIT, "border-top-color", "--design-border-strong", `dialog ${mode}`);
      await assertToken(page, MODAL_SUBMIT, "color", "--design-text", `dialog ${mode}`);
      await page.locator(SELECT).first().click();
      const dropdown = ".ant-select-dropdown:not(.ant-select-dropdown-hidden)";
      await expect(page.locator(dropdown).first()).toBeVisible();
      await animationsSettled(page);
      await assertToken(page, dropdown, "background-color", "--design-surface-2", `dropdown ${mode}`);
      await page.keyboard.press("Escape");
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, MODAL, "litellm dialog");
    await assertReadable(
      page,
      [`${MODAL} .ant-form-item-label > label`, `${MODAL} .ant-radio-wrapper`, MODAL_SUBMIT],
      "litellm dialog",
    );
  });

  test("design: code samples take surface and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.signIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/ui/?page=budgets`);
      await ready(page);
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
      await gotoOnion(page, `${base}/ui/?page=new_usage`);
      await ready(page);
      const outline = (await tokenValue(page, "--design-border", "color")).replace(/[()]/g, "\\$&");
      await expect(
        page.locator(CARD).first(),
        `card ${mode}: the outline ring must take --design-border`,
      ).toHaveCSS("box-shadow", new RegExp(`${outline} 0px 0px 0px 1px`));

      await gotoOnion(page, `${base}/ui/?page=api-keys`);
      await opened(MODAL, openKeyDialog)(page);
      await assertToken(page, TEXT_FIELD, "border-top-color", "--design-border-strong", `text field ${mode}`);
      await page.locator(`${TEXT_FIELD} input`).first().focus();
      await expect(page.locator(TEXT_FIELD).first()).toHaveClass(/ring-tremor-brand-muted/);
      await assertToken(page, TEXT_FIELD, "background-color", "--design-surface-2", `focused text field ${mode}`);

      await gotoOnion(page, `${base}/ui/?page=teams`);
      await opened(MODAL, openTeamDialog)(page);
      await assertToken(page, NUMBER_FIELD, "border-top-color", "--design-border-strong", `number field ${mode}`);

      await gotoOnion(page, `${base}/ui/?page=general-settings`);
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
      await expect(page.locator(shared.SHELL)).toHaveCSS("content", `url("${logoUrl}")`);
      for (const icon of await page.locator("link[rel~='icon']").all()) {
        await expect(icon).toHaveAttribute("href", faviconUrl);
      }
      for (const url of [logoUrl, faviconUrl]) {
        expect((await apiGetOnion(page.request, url)).ok(), `${url} is published on the CDN`).toBe(true);
      }
    }
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
