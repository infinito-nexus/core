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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const lockupUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOCKUP_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const NO_SIGN_IN_PAGE = "the oauth2-proxy gate signs every visitor in, so n8n never renders its own sign-in page";
const SIGN_IN_FORM = "[data-test-id='auth-form']";
const SUBMIT = "[data-test-id='form-submit-button']";
const PASSWORD = `${SIGN_IN_FORM} input[type='password']`;
const LOGO = "[data-test-id='n8n-logo']";
const COLLAPSED_LOGO = `${LOGO}[class*='_sidebarCollapsed_']`;
const COLLAPSE = "#collapse-change-button";
const SETTINGS_BACK = "[data-test-id='settings-back']";
const AUTO_COLLAPSE_BELOW = 900;
const ADD = "[data-test-id='universal-add']";
const SIDEBAR = "#sidebar";
const MENU_ITEM = `${SIDEBAR} [data-test-id='menu-item']`;
const WORKFLOW_CARD = "[data-test-id='resources-list-item-workflow']";
const WORKFLOW_NAME = "[data-test-id='workflow-card-name']";
const CREATE_WORKFLOW = "[data-test-id='add-resource-workflow']";
const CREDENTIAL_ROW = "[data-test-id='resources-list-item']";
const EXECUTION_ROW = "[data-test-id='global-execution-list-item']";
const ROW_CHECKBOX = `${EXECUTION_ROW} .el-checkbox__inner`;
const AVATAR_DISC = ".n8n-avatar svg g > rect";
const CANVAS_NODE = ".vue-flow__node";
const THEME_SELECT = "[data-test-id='theme-select']";
const SAVE_SETTINGS = "[data-test-id='save-settings-button']";
const OPTION = ".el-select-dropdown__item:visible";
const DIALOG = ".el-dialog:visible";
const CONFIRM = ".el-message-box__btns .btn--confirm";
const CANCEL = ".el-message-box__btns .btn--cancel";
const SURVEY_VERSION = "v4";
const BROWSER_ID = "n8n-browserId";
const SHOWCASE = "Design showcase";
const SHOWCASE_NODE = "design-showcase-fields";

let session = null;

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

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    await animationsSettled(page);
  };
}

function opened(trigger, panel) {
  return async (page) => {
    await shown(trigger)(page);
    await page.locator(trigger).first().click();
    await shown(panel)(page);
    await expect(page.locator(panel).first()).toHaveCSS("opacity", "1");
  };
}

/**
 * Args:
 *   page: Playwright page whose document title is inspected.
 *   label: name of the page in the failure message.
 */
async function assertTitled(page, label) {
  await expect
    .poll(async () => (await page.title()).split(title).length - 1, {
      message: `the title of ${label} must carry the configured title exactly once`,
    })
    .toBe(1);
}

/**
 * Args:
 *   page: Playwright page that shows the logo box.
 *
 * Returns:
 *   The layout box of the logo, the URL and the natural size of the image it paints, and the size that image is painted at.
 */
async function paintedLogo(page) {
  return page.locator(LOGO).evaluate(async (element) => {
    const style = getComputedStyle(element);
    const url = style.backgroundImage.replace(/^url\("(.*)"\)$/, "$1");
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = url;
    });
    const height = (element.clientHeight * parseFloat(style.backgroundSize.split(" ").pop())) / 100;
    return {
      url,
      position: style.backgroundPosition,
      box: { width: element.clientWidth, height: element.clientHeight, right: element.getBoundingClientRect().right },
      natural: { width: image.naturalWidth, height: image.naturalHeight },
      painted: { width: (height * image.naturalWidth) / image.naturalHeight, height },
    };
  });
}

/**
 * Args:
 *   page: Playwright page that shows the expanded sidebar; its logo box must paint the lockup of logo and title wide, unclipped, clear of the add button and with a title no smaller than the sidebar entries.
 */
async function assertLockup(page) {
  const logo = await paintedLogo(page);
  expect(logo.url, "the expanded sidebar must show the lockup of logo and title").toBe(lockupUrl);
  expect(logo.position, "the lockup must start at the left edge of its box").toBe("0% 50%");
  const shown = {
    width: Math.min(logo.painted.width, logo.box.width),
    height: Math.min(logo.painted.height, logo.box.height),
  };
  expect(
    shown.width,
    `the logo in the expanded sidebar is painted ${shown.width}x${shown.height} and must be at least twice as wide as high`,
  ).toBeGreaterThanOrEqual(2 * shown.height);
  expect(logo.painted.width, "the lockup must fit the width of its box").toBeLessThanOrEqual(logo.box.width);
  expect(logo.box.right, "the lockup must end before the add button").toBeLessThanOrEqual(
    (await page.locator(ADD).boundingBox()).x,
  );
  const lockup = await apiGetOnion(page.request, logo.url);
  expect(lockup.ok(), "the lockup must be served").toBe(true);
  const titleSize = (Number(/font-size="(\d+)"/.exec(await lockup.text())[1]) * logo.painted.height) / logo.natural.height;
  const entrySize = await page.locator(MENU_ITEM).first().evaluate((entry) => parseFloat(getComputedStyle(entry).fontSize));
  expect(titleSize, "the title of the lockup must not be smaller than the sidebar entries").toBeGreaterThanOrEqual(entrySize);
}

/**
 * Args:
 *   page: signed-in Playwright page; the request runs inside it, so the session cookie and the browser id n8n binds it to travel along.
 *   method: HTTP verb.
 *   path: path below the n8n origin.
 *   payload: JSON body, omitted for a request without one.
 *
 * Returns:
 *   The HTTP status and the `data` member of the answer.
 */
async function rest(page, method, path, payload) {
  return page.evaluate(
    async ([verb, url, body, browserIdKey]) => {
      const response = await fetch(url, {
        method: verb,
        headers: {
          "content-type": "application/json",
          "browser-id": window.localStorage.getItem(browserIdKey) || "",
        },
        body: body === null ? undefined : JSON.stringify(body),
      });
      const answer = await response.json().catch(() => null);
      return { status: response.status, data: answer ? answer.data : null };
    },
    [method, path, payload === undefined ? null : payload, BROWSER_ID],
  );
}

/**
 * Args:
 *   page: signed-in Playwright page of an owner; the first-run survey n8n lays over the workflow list and the editor gets answered empty when it is still open, the way its only button does.
 */
async function skipSurvey(page) {
  const owner = await rest(page, "GET", "/rest/login");
  expect(owner.status, "the session must resolve its user").toBe(200);
  if (owner.data.personalizationAnswers) return;
  const settings = await rest(page, "GET", "/rest/settings");
  const answered = await rest(page, "POST", "/rest/me/survey", {
    version: SURVEY_VERSION,
    personalization_survey_submitted_at: new Date().toISOString(),
    personalization_survey_n8n_version: settings.data.versionCli,
  });
  expect(answered.status, "answering the first-run survey").toBeLessThan(300);
}

function showcaseWorkflow() {
  const node = (id, name, type, typeVersion, position, parameters) => ({
    id: `design-showcase-${id}`,
    name,
    type: `n8n-nodes-base.${type}`,
    typeVersion,
    position,
    parameters,
  });
  const link = (target) => ({ node: target, type: "main", index: 0 });
  return {
    name: SHOWCASE,
    active: false,
    settings: { executionOrder: "v1" },
    nodes: [
      node("start", "Start", "manualTrigger", 1, [0, 0], {}),
      node("fields", "Edit Fields", "set", 3.4, [220, 0], {
        assignments: {
          assignments: [
            { id: "design-showcase-greeting", name: "greeting", value: "Hello from the design showcase", type: "string" },
          ],
        },
        options: {},
      }),
      node("done", "Done", "noOp", 1, [440, -100], {}),
      node("archive", "Archive", "noOp", 1, [440, 100], {}),
      node("note", "Note", "stickyNote", 1, [-20, -260], {
        content: "## Design showcase\nSeeded for the corporate design review.",
        height: 160,
        width: 320,
      }),
    ],
    connections: {
      Start: { main: [[link("Edit Fields")]] },
      "Edit Fields": { main: [[link("Done"), link("Archive")]] },
    },
  };
}

/**
 * Args:
 *   page: signed-in Playwright page; a workflow, one execution of it and a credential named after the showcase get created when they are missing.
 *
 * Returns:
 *   The ids of the showcase workflow and the showcase credential.
 */
async function seedShowcase(page) {
  const named = encodeURIComponent(JSON.stringify({ name: SHOWCASE }));
  const workflows = await rest(page, "GET", `/rest/workflows?filter=${named}`);
  expect(workflows.status, "the owner session must list workflows").toBe(200);
  let workflow = workflows.data.find((entry) => entry.name === SHOWCASE);
  if (!workflow) {
    const created = await rest(page, "POST", "/rest/workflows", showcaseWorkflow());
    expect(created.status, "seeding the showcase workflow").toBeLessThan(300);
    workflow = created.data;
  }

  const ofWorkflow = encodeURIComponent(JSON.stringify({ workflowId: workflow.id }));
  const executed = () => rest(page, "GET", `/rest/executions?filter=${ofWorkflow}&limit=1`);
  if ((await executed()).data.results.length === 0) {
    const run = await rest(page, "POST", `/rest/workflows/${workflow.id}/run`, {
      workflowData: { ...showcaseWorkflow(), id: workflow.id },
    });
    expect(run.status, "running the showcase workflow once").toBeLessThan(300);
    await expect
      .poll(async () => (await executed()).data.results.filter((entry) => entry.stoppedAt).length, {
        message: "the showcase execution must finish",
        timeout: resolveTimeout(60_000),
      })
      .toBeGreaterThan(0);
  }

  const credentials = await rest(page, "GET", "/rest/credentials");
  expect(credentials.status, "the owner session must list credentials").toBe(200);
  let credential = credentials.data.find((entry) => entry.name === SHOWCASE);
  if (!credential) {
    const created = await rest(page, "POST", "/rest/credentials", {
      name: SHOWCASE,
      type: "httpHeaderAuth",
      data: { name: "X-Design-Showcase", value: "dummy-value" },
    });
    expect(created.status, "seeding the showcase credential").toBeLessThan(300);
    credential = created.data;
  }
  return { workflowId: workflow.id, credentialId: credential.id };
}

function signInViews(base) {
  return [
    { name: "sign-in", url: `${base}/signin`, prepare: shown(SIGN_IN_FORM) },
    {
      name: "sign-in-focus",
      url: `${base}/signin`,
      prepare: async (page) => {
        await shown(SIGN_IN_FORM)(page);
        await page.locator(`${SIGN_IN_FORM} input`).first().focus();
        await animationsSettled(page);
      },
    },
  ];
}

/**
 * Args:
 *   views: gallery views of the signed-in interface. n8n keeps the collapse state of the main sidebar across pages, so each view first brings a wide viewport into the state it names: collapsed for a view marked `collapsed`, expanded otherwise. Below the width n8n collapses the sidebar by itself the state stays as it is.
 *
 * Returns:
 *   The views with that step in front of their own preparation.
 */
function withSidebarState(views) {
  return views.map(({ collapsed = false, ...view }) => ({
    ...view,
    prepare: async (page) => {
      await shown(`${SIDEBAR} ${LOGO}, ${SETTINGS_BACK}`)(page);
      const wide = page.viewportSize().width >= AUTO_COLLAPSE_BELOW;
      if (wide && (await page.locator(COLLAPSED_LOGO).isVisible()) !== collapsed) {
        await page.locator(COLLAPSE).click();
        await expect(page.locator(COLLAPSED_LOGO)).toHaveCount(collapsed ? 1 : 0);
        await animationsSettled(page);
      }
      await view.prepare(page);
    },
  }));
}

function signedInViews(base, { workflowId, credentialId }) {
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  const open = (name, path, trigger, panel) => ({ name, url: `${base}${path}`, prepare: opened(trigger, panel) });
  const editor = `/workflow/${workflowId}`;
  return [
    view("workflows", "/home/workflows", WORKFLOW_CARD),
    open(
      "workflow-menu",
      "/home/workflows",
      `${WORKFLOW_CARD} [data-test-id='workflow-card-actions']`,
      "[data-test-id='action-open']:visible",
    ),
    open(
      "add-menu",
      "/home/workflows",
      "[data-test-id='universal-add']",
      "[data-test-id='navigation-menu-item']:visible",
    ),
    {
      name: "user-menu",
      url: `${base}/home/workflows`,
      prepare: async (page) => {
        await shown(WORKFLOW_CARD)(page);
        const expanded = page.locator("[data-test-id='user-menu']");
        const collapsed = page.locator("[data-test-id='main-sidebar-user-menu'] .n8n-avatar");
        await ((await expanded.isVisible()) ? expanded : collapsed).click();
        await shown(".el-dropdown-menu:visible")(page);
      },
    },
    {
      name: "navigation",
      url: `${base}/home/workflows`,
      prepare: async (page) => {
        await shown(WORKFLOW_CARD)(page);
        await page.locator(`${MENU_ITEM}:visible`).nth(1).hover();
        await animationsSettled(page);
      },
    },
    { name: "navigation-collapsed", url: `${base}/home/workflows`, collapsed: true, prepare: shown(WORKFLOW_CARD) },
    view("credentials", "/home/credentials", CREDENTIAL_ROW),
    view("credential-new", "/home/credentials/create", DIALOG),
    view("credential-edit", `/home/credentials/${credentialId}`, DIALOG),
    {
      name: "credential-delete",
      url: `${base}/home/credentials/${credentialId}`,
      prepare: opened("[data-test-id='credential-delete-button']", CONFIRM),
    },
    view("executions", "/home/executions", EXECUTION_ROW),
    view("editor", editor, CANVAS_NODE),
    view("editor-node", `${editor}/${SHOWCASE_NODE}`, "[data-test-id='ndv']"),
    open("editor-node-creator", editor, "[data-test-id='node-creator-plus-button']", "[data-test-id='node-creator']"),
    {
      name: "editor-settings",
      url: `${base}${editor}`,
      prepare: async (page) => {
        await opened("[data-test-id='workflow-menu']", "[data-test-id='workflow-menu-item-settings']:visible")(page);
        await page.locator("[data-test-id='workflow-menu-item-settings']:visible").click();
        await shown("[data-test-id='workflow-settings-dialog']")(page);
      },
    },
    view("editor-executions", `${editor}/executions`, "[data-test-id='executions-sidebar']"),
    view("settings-personal", "/settings/personal", THEME_SELECT),
    open("theme-picker", "/settings/personal", THEME_SELECT, OPTION),
    view("settings-users", "/settings/users", "[data-test-id='settings-users-invite-button']"),
    open("invite-user", "/settings/users", "[data-test-id='settings-users-invite-button']", DIALOG),
  ];
}

exports.register = function (shared) {
  const base = shared.env.n8nBaseUrl;

  async function openSignIn(page) {
    await gotoOnion(page, `${base}/signin`);
    await shown(SIGN_IN_FORM)(page);
  }

  /**
   * Args:
   *   page: Playwright page that ends signed in as the instance owner. The first call signs in; later calls reuse that session, because n8n limits sign-in attempts per client.
   */
  async function signIn(page) {
    if (session) {
      await page.context().addCookies(session.cookies);
      await page.addInitScript(([key, value]) => window.localStorage.setItem(key, value), [BROWSER_ID, session.browserId]);
      await gotoOnion(page, `${base}/home/workflows`);
    } else if (shared.env.oidcEnabled) {
      await shared.signInViaN8nOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");
    } else {
      await gotoOnion(page, `${base}/signin`);
      await shared.performN8nLoginForm(page, shared.env.adminEmail, shared.env.n8nOwnerPassword);
    }
    await expect(page.locator(SIDEBAR)).toBeVisible({ timeout: resolveTimeout(60_000) });
    if (!session) {
      await skipSurvey(page);
      session = {
        cookies: await page.context().cookies(),
        browserId: (await page.evaluate((key) => window.localStorage.getItem(key), BROWSER_ID)) || "",
      };
    }
  }

  async function pickTheme(page, label) {
    await page.locator(THEME_SELECT).click();
    await page.locator(OPTION, { hasText: label }).click();
    await page.locator(SAVE_SETTINGS).click();
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await assertDesignTokens(page, "n8n");
  });

  test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(shared.env.oidcEnabled, NO_SIGN_IN_PAGE);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openSignIn(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, SIGN_IN_FORM, "background-color", "--design-surface-2", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await assertToken(page, PASSWORD, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
      await page.locator(SUBMIT).hover();
      await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, SIGN_IN_FORM, "n8n sign-in");
    await assertReadable(page, [SIGN_IN_FORM, SUBMIT, `${SIGN_IN_FORM} label`, `${SIGN_IN_FORM} a`], "n8n sign-in");
  });

  test("design: the signed-in interface takes surfaces, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await seedShowcase(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/home/workflows`);
      await shown(WORKFLOW_CARD)(page);
      await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
      await assertToken(page, `${SIDEBAR} > div`, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, WORKFLOW_CARD, "background-color", "--design-surface-2", `shell ${mode}`);
      await assertToken(page, WORKFLOW_NAME, "color", "--design-text", `shell ${mode}`);
      await assertToken(page, AVATAR_DISC, "fill", "--design-frame", `avatar ${mode}`);
      await assertToken(page, ".n8n-avatar span", "color", "--design-on-frame", `avatar ${mode}`);
      await assertToken(page, CREATE_WORKFLOW, "background-color", "--design-primary", `shell ${mode}`);
      await assertToken(page, CREATE_WORKFLOW, "color", "--design-on-primary", `shell ${mode}`);
      await page.locator(CREATE_WORKFLOW).hover();
      await assertToken(page, CREATE_WORKFLOW, "background-color", "--design-primary-hover", `hovered action ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, WORKFLOW_CARD, "n8n shell");
    await assertReadable(
      page,
      [WORKFLOW_NAME, CREATE_WORKFLOW, MENU_ITEM, "[data-test-id='project-name']", "[data-test-id='project-subtitle']"],
      "n8n shell",
    );

    await gotoOnion(page, `${base}/home/executions`);
    await shown(EXECUTION_ROW)(page);
    await assertToken(page, ROW_CHECKBOX, "border-top-color", "--design-border-strong", "list checkbox");
    await assertReadable(page, [`${EXECUTION_ROW} td`, "[data-test-id='execution-status']"], "n8n executions");
  });

  test("design: a theme picked in the personal settings is respected and mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await signIn(page);
    await gotoOnion(page, `${base}/settings/personal`);
    await shown(THEME_SELECT)(page);
    const html = page.locator("html");
    const surface = () => tokenValue(page, "--design-surface-1", "background-color");
    const lightSurface = await surface();
    await expect(html, "the palette follows the browser preference").not.toHaveAttribute("data-design-theme");

    await pickTheme(page, "Dark");
    await expect(page.locator("body")).toHaveAttribute("data-theme", "dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(await surface(), "a dark theme picked in n8n must switch the tokens while the browser prefers light").not.toBe(
      lightSurface,
    );
    await assertToken(page, "body", "background-color", "--design-surface-1", "dark theme picked in n8n");

    await gotoOnion(page, page.url());
    await shown(THEME_SELECT)(page);
    await expect(html, "the picked theme must survive a reload").toHaveAttribute("data-design-theme", "dark");

    await page.emulateMedia({ colorScheme: "dark" });
    await pickTheme(page, "Light");
    await expect(html).toHaveAttribute("data-design-theme", "light");
    expect(await surface(), "a light theme picked in n8n must keep the light tokens while the browser prefers dark").toBe(
      lightSurface,
    );
    await assertToken(page, "body", "background-color", "--design-surface-1", "light theme picked in n8n");

    await pickTheme(page, "System");
    await expect(html, "the system theme hands the mode back to the browser").not.toHaveAttribute("data-design-theme");
  });

  test("design: the interface shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

    await signIn(page);
    await seedShowcase(page);
    await gotoOnion(page, `${base}/home/workflows`);
    await shown(WORKFLOW_CARD)(page);
    if (title) await assertTitled(page, "a signed-in page");
    if (logoUrl) {
      expect(faviconUrl, "a role that renders a logo also renders DESIGN_FAVICON_URL").toBeTruthy();
      await expect(page.locator(`${LOGO} > svg`).first()).toHaveCSS("visibility", "hidden");
      if (lockupUrl) await assertLockup(page);
      await page.locator(COLLAPSE).click();
      await expect(page.locator(COLLAPSED_LOGO)).toHaveCSS("background-image", `url("${logoUrl}")`);
      await expect(page.locator(COLLAPSED_LOGO)).toHaveCSS("background-position", "50% 50%");
      await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
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
  });

  test("design: the sign-in page shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    test.skip(shared.env.oidcEnabled, NO_SIGN_IN_PAGE);

    await openSignIn(page);
    if (title) await assertTitled(page, "the sign-in page");
    if (logoUrl) {
      await expect(page.locator(LOGO)).toHaveCSS("background-image", `url("${lockupUrl || logoUrl}")`);
      await expect(page.locator(LOGO)).toHaveCSS("background-position", "50% 50%");
      await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
    }
  });

  test("design: a confirmation dialog takes its actions from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    const { credentialId } = await seedShowcase(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/home/credentials/${credentialId}`);
      await opened("[data-test-id='credential-delete-button']", CONFIRM)(page);
      await assertToken(page, CONFIRM, "background-color", "--design-primary", `confirmation ${mode}`);
      await assertToken(page, CONFIRM, "color", "--design-on-primary", `confirmation ${mode}`);
      await assertToken(page, CANCEL, "color", "--design-text", `confirmation ${mode}`);
      await assertToken(page, CANCEL, "background-color", "--design-surface-2", `confirmation ${mode}`);
      await page.locator(CONFIRM).hover();
      await assertToken(page, CONFIRM, "background-color", "--design-primary-hover", `hovered confirmation ${mode}`);
      await page.locator(CANCEL).hover();
      await assertToken(page, CANCEL, "color", "--design-link", `hovered cancellation ${mode}`);
      await assertToken(page, CANCEL, "border-top-color", "--design-link", `hovered cancellation ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: gallery of sign-in, lists, editor, settings, dialogs and menus", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));

    if (!shared.env.oidcEnabled) await captureDesignGallery(page, signInViews(base));

    await signIn(page);
    await captureDesignGallery(page, withSidebarState(signedInViews(base, await seedShowcase(page))));
  });
};
