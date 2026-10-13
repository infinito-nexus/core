const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
} = require("./design");
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const AUTH_CARD = "#auth-login-card";
const AUTH_SUBMIT = `${AUTH_CARD} button[type=submit]`;
const CHAT_INPUT = "#chat-input";
const INPUT_CONTAINER = "#message-input-container";
const MODEL_BUTTON = "[id^='model-selector-'][id$='-button']";
const SIDEBAR = "#sidebar";
const SIDEBAR_TOGGLE = "#sidebar-toggle-button";
const USER_MENU = "img[aria-label='Open User Profile Menu']";
const SETTINGS_TABS = "#settings-tabs-container";
const SETTINGS_GENERAL = "#tab-general";
const SETTINGS_SAVE = `${SETTINGS_GENERAL} button.bg-black`;
const THEME_SELECT = `${SETTINGS_GENERAL} select`;
const ANSWER = "#response-content-container";
const CODE_BLOCK = ".cm-editor";
const UPDATE_NOTICE = "[class*='bg-[#F1F8FE]']";
const WORKSPACE = "#workspace-container";
const DIALOG = "[role='dialog'][aria-modal='true']";
const SHOWCASE_TITLE = "Design showcase";
const SHOWCASE_PROMPT = "design-showcase";
const SHOWCASE_ANSWER = [
  "## Palette check",
  "",
  "A paragraph with a [link](https://infinito.nexus), **bold text** and `inline code`.",
  "",
  "> A quotation with a divider below.",
  "",
  "---",
  "",
  "| Token | Use |",
  "|---|---|",
  "| surface | page and panels |",
  "| primary | actions |",
  "",
  "```python",
  "# comment",
  "def answer(value: int) -> str:",
  '    return f"{value + 1}"',
  "```",
].join("\n");

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
      { message: "every finite animation of the page must have ended", timeout: resolveTimeout(10_000) },
    )
    .toBe(false);
}

/**
 * Args:
 *   page: Playwright page that shows the sign-in page of the app.
 *   base: base URL of the app.
 */
async function openSignIn(page, base) {
  await gotoOnion(page, `${base}/auth`);
  await expect(page.locator(AUTH_CARD)).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(page.locator("#splash-screen")).toHaveCount(0);
}

/**
 * Args:
 *   page: Playwright page with a fresh context.
 *   shared: helpers of the role spec; the administrator signs in through the provider the deployment enables.
 */
async function signIn(page, shared) {
  const { env } = shared;
  if (isServiceEnabled("sso")) {
    await shared.signInViaDashboardOidc(page, env.adminUsername, env.adminPassword, "administrator");
  } else if (isServiceEnabled("ldap")) {
    await shared.signInViaLdap(page, env.adminUsername, env.adminPassword, "administrator");
  } else {
    await shared.signInViaNativePassword(page, env.adminEmail, env.adminPassword, "administrator");
  }
  await expect(page.locator(CHAT_INPUT)).toBeVisible({ timeout: resolveTimeout(60_000) });
  await shared.dismissAllOpenModals(page);
}

async function chatReady(page) {
  await expect(page.locator(CHAT_INPUT)).toBeVisible({ timeout: resolveTimeout(10_000) });
  await expect(page.locator("#splash-screen")).toHaveCount(0);
  await animationsSettled(page);
}

async function loaded(page) {
  await expect(page.locator("svg:has(.spinner_ajPY):visible")).toHaveCount(0, { timeout: resolveTimeout(10_000) });
  await animationsSettled(page);
}

function visible(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(page.locator("#splash-screen")).toHaveCount(0);
    await loaded(page);
  };
}

async function authHeaders(page) {
  const token = await page.evaluate(() => window.localStorage.getItem("token"));
  expect(token, "the sign-in must leave the session token").toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

function showcaseChat() {
  const user = "design-showcase-user";
  const assistant = "design-showcase-assistant";
  const timestamp = 1_760_000_000;
  const messages = [
    {
      id: user,
      parentId: null,
      childrenIds: [assistant],
      role: "user",
      content: "Show the palette in a table and a code block.",
      timestamp,
      models: [SHOWCASE_PROMPT],
    },
    {
      id: assistant,
      parentId: user,
      childrenIds: [],
      role: "assistant",
      content: SHOWCASE_ANSWER,
      model: SHOWCASE_PROMPT,
      modelName: SHOWCASE_TITLE,
      modelIdx: 0,
      timestamp,
      done: true,
    },
  ];
  return {
    title: SHOWCASE_TITLE,
    models: [SHOWCASE_PROMPT],
    params: {},
    tags: [],
    timestamp: timestamp * 1000,
    messages,
    history: { currentId: assistant, messages: Object.fromEntries(messages.map((message) => [message.id, message])) },
  };
}

/**
 * Args:
 *   page: Playwright page that is signed in.
 *   base: base URL of the app.
 * Returns: the id of the showcase chat.
 */
async function seedShowcase(page, base) {
  const headers = await authHeaders(page);
  const chats = await (await apiGetOnion(page.request, `${base}/api/v1/chats/?page=1`, { headers })).json();
  let chat = chats.find((entry) => entry.title === SHOWCASE_TITLE);
  if (!chat) {
    const created = await apiFetchOnion(page.request, `${base}/api/v1/chats/new`, {
      method: "POST",
      headers,
      data: { chat: showcaseChat() },
    });
    expect(created.ok(), "seeding the showcase chat").toBe(true);
    chat = await created.json();
  }
  return chat.id;
}

function settingsEntry(page) {
  return page
    .locator("button, [role='menuitem']")
    .filter({ hasText: /^\s*Settings\s*$/ })
    .first();
}

async function openUserMenu(page) {
  await chatReady(page);
  const trigger = page.locator(USER_MENU).first();
  if (!(await trigger.isVisible())) {
    await page.locator(SIDEBAR_TOGGLE).first().click();
    await expect(page.locator(SIDEBAR)).toBeVisible({ timeout: resolveTimeout(10_000) });
    await animationsSettled(page);
  }
  await trigger.click();
  await expect(settingsEntry(page)).toBeVisible({ timeout: resolveTimeout(10_000) });
  await animationsSettled(page);
}

function settings(tab) {
  return async (page) => {
    await openUserMenu(page);
    await settingsEntry(page).click();
    await expect(page.locator(SETTINGS_TABS)).toBeVisible({ timeout: resolveTimeout(10_000) });
    const button = page.locator(`${SETTINGS_TABS} button[aria-controls='${tab}']`).first();
    if (tab !== "tab-general") await button.click();
    await expect(button).toHaveAttribute("aria-selected", "true", { timeout: resolveTimeout(10_000) });
    await loaded(page);
  };
}

async function openModelSelector(page) {
  await chatReady(page);
  await page.locator(MODEL_BUTTON).first().click();
  await expect(page.locator("#model-search-input")).toBeVisible({ timeout: resolveTimeout(10_000) });
  await animationsSettled(page);
}

function signInViews(base) {
  const url = `${base}/auth`;
  return [
    { name: "sign-in", url, prepare: visible(AUTH_CARD) },
    {
      name: "sign-in-focus",
      url,
      prepare: async (page) => {
        await visible(AUTH_CARD)(page);
        await page.locator(`${AUTH_CARD} input`).first().focus();
      },
    },
    {
      name: "sign-in-hover",
      url,
      prepare: async (page) => {
        await visible(AUTH_CARD)(page);
        await page.locator(AUTH_SUBMIT).first().hover();
      },
    },
  ];
}

function signedInViews(base, chatId) {
  const admin = (tab) => ({ name: `admin-settings-${tab}`, url: `${base}/`, prepare: settings(`tab-admin-${tab}`) });
  const workspace = (name, path) => ({ name, url: `${base}/workspace/${path}`, prepare: visible(WORKSPACE) });
  return [
    { name: "chat-new", url: `${base}/`, prepare: chatReady },
    { name: "chat-model-selector", url: `${base}/`, prepare: openModelSelector },
    { name: "chat-conversation", url: `${base}/c/${chatId}`, prepare: visible(ANSWER) },
    {
      name: "chat-code-block",
      url: `${base}/c/${chatId}`,
      prepare: async (page) => {
        await visible(CODE_BLOCK)(page);
        await page.locator(CODE_BLOCK).first().scrollIntoViewIfNeeded();
      },
    },
    { name: "chat-user-menu", url: `${base}/`, prepare: openUserMenu },
    { name: "settings-general", url: `${base}/`, prepare: settings("tab-general") },
    { name: "settings-interface", url: `${base}/`, prepare: settings("tab-interface") },
    { name: "settings-personalization", url: `${base}/`, prepare: settings("tab-personalization") },
    { name: "settings-audio", url: `${base}/`, prepare: settings("tab-audio") },
    workspace("workspace-models", "models"),
    workspace("workspace-knowledge", "knowledge"),
    workspace("workspace-knowledge-create", "knowledge/create"),
    workspace("workspace-prompts", "prompts"),
    workspace("workspace-prompt-create", "prompts/create"),
    workspace("workspace-tools", "tools"),
    { name: "admin-users", url: `${base}/admin/users`, prepare: visible("a[href='/admin']") },
    { name: "admin-groups", url: `${base}/admin/users/groups`, prepare: visible("a[href='/admin']") },
    { name: "admin-functions", url: `${base}/admin/functions`, prepare: visible("a[href='/admin/functions']") },
    { name: "admin-evaluations", url: `${base}/admin/evaluations`, prepare: visible("a[href='/admin/evaluations']") },
    admin("general"),
    admin("connections"),
    admin("authentication"),
    admin("interface"),
    admin("documents"),
  ];
}

exports.register = function (shared) {
  const base = shared.env.openwebuiBaseUrl;

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignIn(page, base);
    await assertDesignTokens(page, "openwebui");
  });

  test("design: the sign-in page takes surface, text and action from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openSignIn(page, base);
      await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${mode}\\b`));
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, AUTH_CARD, "color", "--design-text", `sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, AUTH_CARD, "openwebui sign-in");
    await assertReadable(page, [`${AUTH_CARD} .text-2xl`, AUTH_SUBMIT], "openwebui sign-in");
  });

  test("design: the chat shell takes surfaces, text, dividers and the primary action from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/`);
      await chatReady(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `shell ${mode}`);
      await assertToken(page, INPUT_CONTAINER, "border-top-color", "--design-border", `chat input ${mode}`);
      if (await page.locator(UPDATE_NOTICE).count()) {
        await assertToken(page, UPDATE_NOTICE, "background-color", "--design-info-subtle", `update notice ${mode}`);
        await assertToken(page, UPDATE_NOTICE, "color", "--design-info", `update notice ${mode}`);
      }
      await settings("tab-general")(page);
      await assertToken(page, SETTINGS_SAVE, "background-color", "--design-primary", `settings ${mode}`);
      await assertToken(page, SETTINGS_SAVE, "color", "--design-on-primary", `settings ${mode}`);
      await page.locator(SETTINGS_SAVE).first().hover();
      await assertToken(page, SETTINGS_SAVE, "background-color", "--design-primary-hover", `hovered save ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, SETTINGS_GENERAL, "openwebui settings");
    await assertReadable(page, [SETTINGS_SAVE, THEME_SELECT], "openwebui settings");
  });

  test("design: a stored answer renders Markdown, table and code from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    const chatId = await seedShowcase(page, base);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/c/${chatId}`);
      await visible(ANSWER)(page);
      await assertToken(page, `${ANSWER} p`, "color", "--design-text", `answer ${mode}`);
      await assertToken(page, `${ANSWER} p a`, "color", "--design-link", `answer ${mode}`);
      await assertToken(page, `${ANSWER} th`, "border-bottom-color", "--design-border", `answer table head ${mode}`);
      await assertToken(page, `${ANSWER} td`, "border-bottom-color", "--design-border", `answer table ${mode}`);
      await assertToken(page, CODE_BLOCK, "background-color", "--design-surface-1", `code block ${mode}`);
      await assertToken(page, `${CODE_BLOCK} .cm-content`, "color", "--design-text", `code block ${mode}`);
      await assertToken(page, `${CODE_BLOCK} .cm-gutters`, "color", "--design-text-muted", `code gutter ${mode}`);
      await assertToken(page, `${CODE_BLOCK} .cm-gutters`, "border-right-color", "--design-border", `code gutter ${mode}`);
      await assertToken(page, `${CODE_BLOCK} .cm-activeLine`, "background-color", "--design-surface-hover", `code line ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, CODE_BLOCK, "openwebui code block");
    await assertReadable(
      page,
      [`${ANSWER} p`, `${ANSWER} th`, `${ANSWER} td`, `${CODE_BLOCK} .cm-activeLineGutter`],
      "openwebui answer",
    );
  });

  test("design: the native theme setting drives the palette and leaves OLED dark to the user", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page, shared);
    await page.emulateMedia({ colorScheme: "light" });
    await gotoOnion(page, `${base}/`);
    await settings("tab-general")(page);
    const html = page.locator("html");

    await page.locator(THEME_SELECT).first().selectOption("dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    await assertToken(page, "body", "background-color", "--design-surface-1", "theme dark");
    const dark = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);

    await page.locator(THEME_SELECT).first().selectOption("light");
    await expect(html).toHaveAttribute("data-design-theme", "light");
    await assertToken(page, "body", "background-color", "--design-surface-1", "theme light");
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).not.toBe(dark);

    await page.locator(THEME_SELECT).first().selectOption("oled-dark");
    await expect(html).toHaveAttribute("data-design-app-theme", "oled-dark");
    await expect(page.locator(`${DIALOG} > div`).first()).toHaveCSS("background-color", "rgb(0, 0, 0)");

    await page.locator(THEME_SELECT).first().selectOption("system");
    await expect(html).not.toHaveAttribute("data-design-theme", /.*/);
    await assertToken(page, "body", "background-color", "--design-surface-1", "theme system");
  });

  test("design: provisioning: the role provisions the administrator the native sign-in accepts", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(isServiceEnabled("sso") || isServiceEnabled("ldap"), "the native administrator exists only without sso and ldap");
    const response = await apiFetchOnion(page.request, `${base}/api/v1/auths/signin`, {
      method: "POST",
      data: { email: shared.env.adminEmail, password: shared.env.adminPassword },
      failOnStatusCode: false,
    });
    expect(response.status(), "the administrator task must leave a working native sign-in").toBe(200);
    expect((await response.json()).role, "the provisioned account must be an administrator").toBe("admin");
  });

  test("design: provisioning: the in-house custom.css carries the palette mapping", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const response = await apiGetOnion(page.request, `${base}/static/custom.css`);
    expect(response.ok(), "/static/custom.css must be served").toBe(true);
    expect(await response.text(), "custom.css must map the gray scale onto the tokens").toContain("var(--design-surface-1)");
  });

  test("design: logo and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(
      !logoUrl && !title,
      "Open WebUI LICENSE clause 4 forbids replacing its name and logo above 50 users without an enterprise license, so the role keeps both until the operator decides",
    );

    await openSignIn(page, base);
    if (title) await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    if (logoUrl) {
      const logo = page.locator("img#logo").first();
      await expect(logo).toBeVisible();
      expect(
        await logo.evaluate((image) => image.complete && image.naturalWidth > 0),
        "the sign-in logo must load",
      ).toBe(true);
    }
  });

  test("design: gallery of sign-in, chat, settings, workspace and administration", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));

    const failures = [];
    await openSignIn(page, base);
    await captureDesignGallery(page, signInViews(base)).catch((error) => failures.push(error.message));

    await signIn(page, shared);
    const chatId = await seedShowcase(page, base);
    await captureDesignGallery(page, signedInViews(base, chatId)).catch((error) => failures.push(error.message));
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
