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
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.FLOWISE_BASE_URL, "FLOWISE_BASE_URL")).replace(/\/+$/, "");
const ownerEmail = decodeDotenvQuotedValue(process.env.FLOWISE_OWNER_EMAIL || "");
const ownerPassword = decodeDotenvQuotedValue(process.env.FLOWISE_OWNER_PASSWORD || "");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const ssoEnabled = process.env.SSO_SERVICE_ENABLED === "true";
const lockupUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOCKUP_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const SHOWCASE = "Design showcase";
const DARK_KEY = "isDarkMode";
const BANNER_KEY = "flowise.announcementDismissed";
const SIGN_IN_SUBMIT = "form button[type='submit']";
const EMAIL = "input[name='username']";
const PASSWORD = "input[name='password']";
const HEADING = "main h1";
const PRIMARY = ".MuiButton-containedPrimary";
const ADD = `main ${PRIMARY}`;
const ITEM = "main .MuiCard-root .MuiCard-root";
const ROW = "main table tbody tr";
const DRAWER = ".MuiDrawer-paper";
const NAV_ITEM = `${DRAWER} .MuiListItemButton-root`;
const NAV_SELECTED = `${NAV_ITEM}.Mui-selected`;
const HEADER_AVATAR = ".MuiAppBar-root .MuiAvatar-root";
const SWITCH = ".MuiAppBar-root .MuiSwitch-root";
const SWITCH_INPUT = `${SWITCH} input`;
const DIALOG = ".MuiDialog-paper";
const POPPER = ".MuiPopper-root .MuiPaper-root";
const NODE = ".react-flow__node";
const LOGO = "img[alt='Flowise']";

let session = null;

test.use({ ignoreHTTPSErrors: true });

/**
 * Args:
 *   page: Playwright page.
 *   selector: element that must be visible before every finite animation of the page has ended.
 */
async function settled(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          document
            .getAnimations()
            .some((a) => a.playState === "running" && a.effect?.getComputedTiming().iterations !== Infinity),
        ),
      { timeout: resolveTimeout(10_000), message: "every finite animation must have ended" },
    )
    .toBe(false);
}

function shown(selector) {
  return (page) => settled(page, selector);
}

/**
 * Args:
 *   page: Playwright page that ends on the Flowise sign-in form, through the oauth2 gate when SSO is on.
 */
async function openSignIn(page) {
  await gotoOnion(page, `${base}/signin`);
  if (ssoEnabled && !page.url().startsWith(base)) {
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
    await gotoOnion(page, `${base}/signin`);
  }
  await settled(page, SIGN_IN_SUBMIT);
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the Flowise instance owner. Flowise rate-limits sign-in, so a later call reuses the last session and only fills the form again when Flowise sends that session back to the sign-in page.
 */
async function signIn(page) {
  await page.addInitScript((key) => window.localStorage.setItem(key, "true"), BANNER_KEY);
  if (session) {
    await page.context().addCookies(session);
    await gotoOnion(page, `${base}/chatflows`);
    await expect(page.locator(`${HEADING}, ${SIGN_IN_SUBMIT}`).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  }
  if (!session || (await page.locator(SIGN_IN_SUBMIT).isVisible())) {
    expect(ownerEmail, "FLOWISE_OWNER_EMAIL must be set").toBeTruthy();
    expect(ownerPassword, "FLOWISE_OWNER_PASSWORD must be set").toBeTruthy();
    await openSignIn(page);
    await expect(page.locator(EMAIL)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(EMAIL).fill(ownerEmail);
    await expect(page.locator(PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(PASSWORD).fill(ownerPassword);
    await page.locator(SIGN_IN_SUBMIT).click();
  }
  await expect(page.locator(HEADING)).toBeVisible({ timeout: resolveTimeout(60_000) });
  session = await page.context().cookies();
}

/**
 * Args:
 *   page: Playwright page on the Flowise origin.
 *   method: HTTP verb.
 *   path: path below /api/v1.
 *   payload: JSON body, omitted for a request without one.
 *
 * Returns:
 *   The HTTP status and the parsed answer.
 */
async function api(page, method, path, payload) {
  return page.evaluate(
    async ([verb, url, body]) => {
      const response = await fetch(url, {
        method: verb,
        credentials: "include",
        headers: { "content-type": "application/json", "x-request-from": "internal" },
        body: body === null ? undefined : JSON.stringify(body),
      });
      return { status: response.status, data: await response.json().catch(() => null) };
    },
    [method, `/api/v1${path}`, payload === undefined ? null : payload],
  );
}

/**
 * Args:
 *   page: signed-in Playwright page.
 *   listPath: API path that lists the entities.
 *   createPath: API path that creates one.
 *   payload: body of the creation.
 *
 * Returns:
 *   The entity named after the showcase, created when it is missing.
 */
async function ensure(page, listPath, createPath, payload) {
  const listed = await api(page, "GET", listPath);
  expect(listed.status, `listing ${listPath}`).toBe(200);
  const entries = Array.isArray(listed.data) ? listed.data : listed.data?.data || [];
  const found = entries.find((entry) => entry.name === SHOWCASE);
  if (found) return found;
  const created = await api(page, "POST", createPath, payload);
  expect(created.status, `seeding ${createPath}`).toBeLessThan(300);
  return created.data;
}

/**
 * Args:
 *   page: signed-in Playwright page; one chatflow and one agentflow built from shipped marketplace templates, a tool, a variable, a credential and a document store named after the showcase get created when they are missing.
 *
 * Returns:
 *   The ids the gallery opens.
 */
async function seedShowcase(page) {
  const templates = await api(page, "GET", "/marketplaces/templates");
  expect(templates.status, "listing the marketplace templates").toBe(200);
  const template = (type) => templates.data.find((entry) => entry.type === type && entry.flowData);
  const chatflow = await ensure(page, "/chatflows?type=CHATFLOW", "/chatflows", {
    name: SHOWCASE,
    type: "CHATFLOW",
    flowData: template("Chatflow").flowData,
  });
  const agentflow = await ensure(page, "/chatflows?type=AGENTFLOW", "/chatflows", {
    name: SHOWCASE,
    type: "AGENTFLOW",
    flowData: template("AgentflowV2").flowData,
  });
  await ensure(page, "/tools", "/tools", {
    name: SHOWCASE,
    description: "Seeded for the corporate design review",
    color: "linear-gradient(rgb(255,255,255), rgb(255,255,255))",
    schema: "[]",
    func: "return 'ok'",
  });
  await ensure(page, "/variables", "/variables", { name: SHOWCASE, value: "showcase", type: "static" });
  await ensure(page, "/credentials", "/credentials", {
    name: SHOWCASE,
    credentialName: "openAIApi",
    plainDataObj: { openAIApiKey: "design-showcase" },
  });
  const store = await ensure(page, "/document-store/store", "/document-store/store", {
    name: SHOWCASE,
    description: "Seeded for the corporate design review",
  });
  return { chatflowId: chatflow.id, agentflowId: agentflow.id, storeId: store.id };
}

function opened(ready, trigger, panel) {
  return async (page) => {
    await settled(page, ready);
    await page.locator(trigger).first().click();
    await settled(page, panel);
    await expect(page.locator(panel).first()).toHaveCSS("opacity", "1");
  };
}

/**
 * Args:
 *   page: Playwright page on the chatflow list.
 *   style: title of the toggle button for the wanted display, `Card View` or `List View`.
 */
async function display(page, style) {
  await settled(page, HEADING);
  const toggle = page.locator(`main button[title='${style}']`);
  if ((await toggle.getAttribute("aria-pressed")) !== "true") await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
}

function visitorViews() {
  return [
    { name: "sign-in", url: `${base}/signin`, prepare: shown(SIGN_IN_SUBMIT) },
    {
      name: "sign-in-error",
      url: `${base}/signin?error=${encodeURIComponent(JSON.stringify({ message: "Incorrect Email or Password" }))}`,
      prepare: shown(".MuiAlert-filledError"),
    },
    { name: "forgot-password", url: `${base}/forgot-password`, prepare: shown("form button[type='submit'], main button") },
  ];
}

function signedInViews({ chatflowId, agentflowId, storeId }) {
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  const open = (name, path, ready, trigger, panel) => ({ name, url: `${base}${path}`, prepare: opened(ready, trigger, panel) });
  return [
    {
      name: "chatflows-cards",
      url: `${base}/chatflows`,
      prepare: async (page) => {
        await display(page, "Card View");
        await settled(page, ITEM);
      },
    },
    {
      name: "chatflows-list",
      url: `${base}/chatflows`,
      prepare: async (page) => {
        await display(page, "List View");
        await settled(page, ROW);
      },
    },
    {
      name: "navigation",
      url: `${base}/chatflows`,
      prepare: async (page) => {
        await display(page, "Card View");
        if (!(await page.locator(DRAWER).isVisible())) await page.locator(HEADER_AVATAR).first().click();
        await settled(page, NAV_SELECTED);
        await page.locator(NAV_ITEM).nth(2).hover();
        await settled(page, NAV_SELECTED);
      },
    },
    open("profile-menu", "/chatflows", HEADING, `${HEADER_AVATAR} >> nth=-1`, POPPER),
    view("canvas-chatflow", `/canvas/${chatflowId}`, NODE),
    open("canvas-add-nodes", `/canvas/${chatflowId}`, NODE, "button[title='Add Node'], .MuiFab-root", POPPER),
    view("agentflows", "/agentflows", HEADING),
    view("agentcanvas", `/v2/agentcanvas/${agentflowId}`, NODE),
    view("executions", "/executions", HEADING),
    view("assistants", "/assistants", HEADING),
    view("marketplaces", "/marketplaces", ITEM),
    {
      name: "marketplace-detail",
      url: `${base}/marketplaces`,
      prepare: async (page) => {
        await settled(page, ITEM);
        await page.locator(ITEM).first().click();
        await settled(page, NODE);
      },
    },
    view("tools", "/tools", HEADING),
    open("tool-dialog", "/tools", HEADING, ADD, DIALOG),
    view("credentials", "/credentials", ROW),
    open("credential-add", "/credentials", ROW, ADD, DIALOG),
    view("variables", "/variables", ROW),
    open("variable-dialog", "/variables", ROW, ADD, DIALOG),
    view("document-stores", "/document-stores", HEADING),
    view("document-store-detail", `/document-stores/${storeId}`, HEADING),
    view("account-settings", "/account", "main input"),
  ];
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "Flowise");
});

test("design: the provisioned owner holds the instance, so a visitor can no longer claim it", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await openSignIn(page);
  const resolved = await api(page, "POST", "/auth/resolve");
  expect(resolved.data?.redirectUrl, "an instance without an owner sends visitors to the account setup").toBe("/signin");
  const claim = await api(page, "POST", "/account/register", {
    user: { email: "visitor", name: "visitor", credential: "visitor" },
  });
  expect(claim.status, "registration must be refused").toBe(400);
  expect(claim.data?.message, "registration must be refused because the owner exists").toBe(
    "You can only have one organization",
  );
  await gotoOnion(page, `${base}/`);
  await expect.poll(() => new URL(page.url()).pathname, { timeout: resolveTimeout(10_000) }).toBe("/signin");
  await signIn(page);
});

test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await openSignIn(page);
    await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
    await assertToken(page, "h1", "color", "--design-text", `sign-in ${mode}`);
    await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, SIGN_IN_SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
    await assertToken(page, "form a", "color", "--design-link", `sign-in ${mode}`);
    await assertToken(page, `${EMAIL} ~ fieldset`, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
    await page.locator(SIGN_IN_SUBMIT).hover();
    await assertToken(page, SIGN_IN_SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, "form", "Flowise sign-in");
  await assertReadable(
    page,
    ["h1", SIGN_IN_SUBMIT, "form a", { selector: "form .MuiTypography-root", optional: true }],
    "Flowise sign-in",
  );
});

test("design: the signed-in interface takes surfaces, primary action, text and dividers from the palette", async ({
  page,
}) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await seedShowcase(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/chatflows`);
    await display(page, "Card View");
    await settled(page, ITEM);
    await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
    await assertToken(page, ".MuiAppBar-root", "background-color", "--design-surface-1", `header ${mode}`);
    await assertToken(page, DRAWER, "background-color", "--design-surface-1", `navigation ${mode}`);
    await assertToken(page, NAV_SELECTED, "background-color", "--design-surface-active", `selected entry ${mode}`);
    await assertToken(page, ITEM, "background-color", "--design-surface-2", `card ${mode}`);
    await assertToken(page, ITEM, "border-top-color", "--design-border", `card border ${mode}`);
    await assertToken(page, HEADING, "color", "--design-text", `heading ${mode}`);
    await assertToken(page, ADD, "background-color", "--design-primary", `add new ${mode}`);
    await assertToken(page, ADD, "color", "--design-on-primary", `add new ${mode}`);
    await page.locator(ADD).first().hover();
    await expect(page.locator(ADD).first(), "the hovered action must carry no gradient").toHaveCSS("background-image", "none");
    await assertToken(page, ADD, "background-color", "--design-primary-hover", `hovered add new ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ITEM, "Flowise card");
  await assertReadable(page, [HEADING, `${ITEM} .MuiTypography-root`, ADD, NAV_SELECTED], "Flowise shell");

  await gotoOnion(page, `${base}/variables`);
  await settled(page, ROW);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "main table thead th", "border-bottom-color", "--design-border", `row divider ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [`${ROW} td`, "main table thead th"], "Flowise table");

  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/chatflows`);
    await opened(HEADING, `${HEADER_AVATAR} >> nth=-1`, POPPER)(page);
    await assertToken(page, `${POPPER} .MuiList-root`, "background-color", "--design-surface-2", `profile menu ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: the canvas takes node cards, actions, pagination and controls from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const { chatflowId } = await seedShowcase(page);
  const card = `${NODE} .MuiCard-root`;
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/canvas/${chatflowId}`);
    await settled(page, NODE);
    await assertToken(page, card, "background-color", "--design-surface-2", `node card ${mode}`);
    await assertToken(page, card, "border-top-color", "--design-border-strong", `node card ${mode}`);
    await assertToken(page, `${NODE} .MuiDivider-root + .MuiBox-root`, "background-color", "--design-surface-3", `node section ${mode}`);
    await assertToken(page, ".MuiFab-primary", "background-color", "--design-primary", `add nodes ${mode}`);
    await assertToken(page, ".MuiFab-primary", "color", "--design-on-primary", `add nodes ${mode}`);
    await assertToken(page, ".react-flow__controls-button", "background-color", "--design-surface-2", `canvas controls ${mode}`);
    await assertToken(page, ".react-flow__attribution", "background-color", "--design-surface-2", `attribution ${mode}`);

    await gotoOnion(page, `${base}/variables`);
    await settled(page, ROW);
    await assertToken(page, ".MuiPaginationItem-root.Mui-selected", "background-color", "--design-primary", `page ${mode}`);
    await assertToken(page, ".MuiPaginationItem-root.Mui-selected", "color", "--design-on-primary", `page ${mode}`);
    await assertToken(page, `${ROW} .MuiIconButton-colorPrimary`, "color", "--design-link", `edit ${mode}`);
    await assertToken(page, `${ROW} .MuiIconButton-colorError`, "color", "--design-danger", `delete ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await gotoOnion(page, `${base}/canvas/${chatflowId}`);
  await settled(page, NODE);
  await assertReadable(page, [`${card} .MuiTypography-root`, `${NODE} .MuiDivider-root + .MuiBox-root .MuiTypography-root`], "Flowise canvas");
});

test("design: the header switch picks the mode and is mirrored into the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.emulateMedia({ colorScheme: "light" });
  await signIn(page);
  await page.evaluate((key) => window.localStorage.removeItem(key), DARK_KEY);
  await gotoOnion(page, `${base}/chatflows`);
  await settled(page, SWITCH);
  const html = page.locator("html");
  const surface = () => tokenValue(page, "--design-surface-1", "background-color");
  await expect(html, "without a choice the palette follows the browser").not.toHaveAttribute("data-design-theme");
  expect(
    await page.evaluate((key) => window.localStorage.getItem(key), DARK_KEY),
    "the browser preference seeds the Flowise mode",
  ).toBe("false");
  const lightSurface = await surface();

  await page.locator(SWITCH_INPUT).click();
  await expect(html).toHaveAttribute("data-design-theme", "dark");
  expect(await surface(), "the dark switch must switch the tokens while the browser prefers light").not.toBe(lightSurface);
  await gotoOnion(page, page.url());
  await settled(page, SWITCH);
  await expect(html, "the picked mode must survive a reload").toHaveAttribute("data-design-theme", "dark");

  await page.locator(SWITCH_INPUT).click();
  await expect(html).toHaveAttribute("data-design-theme", "light");
  expect(await surface(), "the light switch must bring the light tokens back").toBe(lightSurface);
  await page.evaluate((key) => window.localStorage.removeItem(key), DARK_KEY);
});

test("design: logo, favicon and title are the configured ones", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!lockupUrl && !title, "logo and title replacement are disabled for this role");
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await settled(page, LOGO);
  if (title) await expect.poll(() => page.title()).toBe(title);
  if (lockupUrl) {
    expect(faviconUrl, "DESIGN_FAVICON_URL is written whenever the lockup is").toBeTruthy();
    await expect(page.locator(LOGO).first()).toHaveCSS("content", `url("${lockupUrl}")`);
    const box = await page.locator(LOGO).first().boundingBox();
    expect(box.width, "the header logo box must be wider than high").toBeGreaterThan(box.height);
    await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    for (const url of [lockupUrl, faviconUrl]) {
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
});

test("design: gallery of sign-in, lists, canvases, dialogs, settings and navigation", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  await openSignIn(page);
  const visitor = await captureDesignGallery(page, visitorViews()).catch((error) => error);
  await signIn(page);
  await captureDesignGallery(page, signedInViews(await seedShowcase(page)));
  expect(visitor, "the visitor views must be captured").toBeUndefined();
});
