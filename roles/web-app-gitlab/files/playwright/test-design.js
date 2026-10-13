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
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const adminPassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));
const title = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_TITLE, "DESIGN_TITLE"));
const logoEnabled = (process.env.DESIGN_LOGO_ENABLED || "").toLowerCase() === "true";

const MODES = ["light", "dark"];
const USERNAME = "[data-testid='username-field']";
const PASSWORD = "[data-testid='password-field']";
const SIGN_IN = "[data-testid='sign-in-button']";
const TOPBAR = "header.super-topbar";
const PANEL = ".js-static-panel";
const CONFIRM = "main .btn-confirm";
const DROPDOWN = ".gl-new-dropdown-panel";
const PREFERENCES_FORM = "main form.edit_user";
const GROUP = "design-showcase";
const PROJECT = `${GROUP}/showcase`;
const PREFERENCES = "/-/profile/preferences";
const ROOT_USERNAME = "root";

let session = null;

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

function opened(trigger) {
  return async (page) => {
    await shown(trigger)(page);
    await page.locator(trigger).first().click();
    const panel = page.locator(`${DROPDOWN}:visible`).first();
    await expect(panel).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(panel).toHaveCSS("opacity", "1", { timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   page: Playwright page that ends signed in as GitLab's root account on the start page; later calls reuse the first session.
 */
async function signIn(page) {
  if (session) {
    await page.context().addCookies(session);
  } else {
    await gotoOnion(page, `${base}/users/sign_in`);
    await expect(page.locator(USERNAME)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(USERNAME).fill(ROOT_USERNAME);
    await expect(page.locator(PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
    await page.locator(PASSWORD).fill(adminPassword);
    await page.locator(SIGN_IN).click();
    await page.waitForURL((url) => !url.pathname.startsWith("/users/sign_in"), { timeout: resolveTimeout(30_000) });
    session = await page.context().cookies();
  }
  await gotoOnion(page, `${base}/`);
  await expect(page.locator(TOPBAR)).toBeVisible({ timeout: resolveTimeout(10_000) });
}

/**
 * Args:
 *   page: signed-in Playwright page; the call runs in it with the session cookie and the CSRF token of the page.
 *   method: HTTP verb.
 *   path: path below /api/v4.
 *   payload: JSON body, omitted for a request without one.
 *
 * Returns:
 *   The HTTP status and the parsed answer.
 */
async function api(page, method, path, payload) {
  return page.evaluate(
    async ([verb, url, body]) => {
      const token = document.querySelector("meta[name='csrf-token']")?.content || "";
      const response = await fetch(url, {
        method: verb,
        credentials: "same-origin",
        headers: { "content-type": "application/json", "x-csrf-token": token },
        body: body === null ? undefined : JSON.stringify(body),
      });
      return { status: response.status, data: await response.json().catch(() => null) };
    },
    [method, `/api/v4${path}`, payload === undefined ? null : payload],
  );
}

/**
 * Args:
 *   page: signed-in Playwright page; group, project, labels, milestone, issue, branch, merge request and wiki page of the showcase get created when missing.
 */
async function seedShowcase(page) {
  let group = await api(page, "GET", `/groups/${GROUP}`);
  if (group.status !== 200) {
    group = await api(page, "POST", "/groups", { name: "Design showcase", path: GROUP, visibility: "private" });
    expect(group.status, "seeding the showcase group").toBeLessThan(300);
  }
  const listed = await api(page, "GET", `/groups/${group.data.id}/projects?search=showcase`);
  let id = listed.data.find((entry) => entry.path === "showcase")?.id;
  if (!id) {
    const created = await api(page, "POST", "/projects", {
      name: "Showcase",
      path: "showcase",
      namespace_id: group.data.id,
      initialize_with_readme: true,
      visibility: "private",
    });
    expect(created.status, "seeding the showcase project").toBeLessThan(300);
    id = created.data.id;
  }
  const project = `/projects/${id}`;
  const labels = (await api(page, "GET", `${project}/labels`)).data.map((label) => label.name);
  for (const [name, color] of [["design", "#6699cc"], ["review", "#44aa77"], ["blocked", "#cc5544"]]) {
    if (!labels.includes(name)) await api(page, "POST", `${project}/labels`, { name, color });
  }
  if ((await api(page, "GET", `${project}/milestones?title=Showcase`)).data.length === 0) {
    await api(page, "POST", `${project}/milestones`, { title: "Showcase" });
  }
  if ((await api(page, "GET", `${project}/issues?search=Showcase`)).data.length === 0) {
    const issue = await api(page, "POST", `${project}/issues`, {
      title: "Showcase issue",
      description: "Seeded for the corporate design review.",
      labels: "design,review",
    });
    expect(issue.status, "seeding the showcase issue").toBeLessThan(300);
    await api(page, "POST", `${project}/issues/${issue.data.iid}/notes`, { body: "A first comment." });
  }
  if ((await api(page, "GET", `${project}/repository/branches/design-change`)).status !== 200) {
    const commit = await api(page, "POST", `${project}/repository/commits`, {
      branch: "design-change",
      start_branch: "main",
      commit_message: "Add a showcase file",
      actions: [{ action: "create", file_path: "showcase.md", content: "# Showcase\n\nSeeded change.\n" }],
    });
    expect(commit.status, "seeding the showcase branch").toBeLessThan(300);
  }
  if ((await api(page, "GET", `${project}/merge_requests?source_branch=design-change`)).data.length === 0) {
    await api(page, "POST", `${project}/merge_requests`, {
      source_branch: "design-change",
      target_branch: "main",
      title: "Showcase merge request",
      labels: "design",
    });
  }
  if ((await api(page, "GET", `${project}/wikis/home`)).status !== 200) {
    await api(page, "POST", `${project}/wikis`, { title: "home", content: "## Showcase wiki\n\n- one\n- two\n" });
  }
}

/**
 * Args:
 *   page: signed-in Playwright page; the preferences form of the administrator is submitted with the color mode and opened again.
 *   id: color mode id, 1 light, 2 dark, 3 auto.
 */
async function pickColorMode(page, id) {
  await gotoOnion(page, `${base}${PREFERENCES}`);
  await shown(PREFERENCES_FORM)(page);
  const status = await page.evaluate(
    async ([selector, mode]) => {
      const form = document.querySelector(selector);
      const data = new FormData(form);
      data.set("user[color_mode_id]", String(mode));
      const token = document.querySelector("meta[name='csrf-token']")?.content || "";
      const response = await fetch(form.action, {
        method: "POST",
        body: data,
        credentials: "same-origin",
        headers: { accept: "application/json", "x-csrf-token": token },
      });
      return response.status;
    },
    [PREFERENCES_FORM, id],
  );
  expect(status, `saving color mode ${id}`).toBeLessThan(400);
  await gotoOnion(page, `${base}${PREFERENCES}`);
  await shown(PREFERENCES_FORM)(page);
}

function views() {
  const p = `/${PROJECT}`;
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  return [
    view("home", "/", "main h1"),
    view("projects", "/dashboard/projects", `main a[href$='${p}']`),
    view("project", p, "main #readme, main article"),
    view("file", `${p}/-/blob/main/README.md`, "main .file-holder"),
    view("commits", `${p}/-/commits/main`, "main a[href*='/-/commit/']"),
    view("branches", `${p}/-/branches`, "main a[href*='design-change']"),
    view("issues", `${p}/-/issues`, "main [data-testid='issuable-title-link']"),
    view("issue", `${p}/-/issues/1`, "main h1"),
    view("issue-new", `${p}/-/issues/new`, CONFIRM),
    view("merge-requests", `${p}/-/merge_requests`, `main a[href$='${p}/-/merge_requests/1']`),
    view("merge-request", `${p}/-/merge_requests/1`, "main h1"),
    view("merge-request-diff", `${p}/-/merge_requests/1/diffs`, "main [data-testid='rd-diff-file']"),
    view("labels", `${p}/-/labels`, "main .gl-label"),
    view("wiki", `${p}/-/wikis/home`, "main .md"),
    view("project-settings", `${p}/edit`, "main form"),
    view("members", `${p}/-/project_members`, "main table"),
    view("group", `/${GROUP}`, `main a[href$='${p}']`),
    view("preferences", PREFERENCES, PREFERENCES_FORM),
    view("profile-settings", "/-/user_settings/profile", "main form"),
    view("admin", "/admin", "main h1"),
    view("admin-users", "/admin/users", "main table"),
    view("admin-settings", "/admin/application_settings/general", "main section"),
    view("admin-appearance", "/admin/application_settings/appearance", "main form"),
    view("search", "/search?search=showcase", "main a.project"),
    view("new-project", "/projects/new", "main h2"),
    { name: "create-menu", url: `${base}/`, prepare: opened(`${TOPBAR} [data-testid='new-menu-toggle']`) },
    { name: "user-menu", url: `${base}/`, prepare: opened(`${TOPBAR} [data-testid='user-menu-toggle']`) },
  ];
}

test("design: a color mode picked in the preferences is respected and mirrored", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.emulateMedia({ colorScheme: "light" });
  await signIn(page);
  await pickColorMode(page, 3);
  const html = page.locator("html");
  const surface = () => tokenValue(page, "--design-surface-1", "background-color");
  const lightSurface = await surface();
  await expect(html, "Auto follows the browser").not.toHaveAttribute("data-design-theme");
  try {
    await pickColorMode(page, 2);
    await expect(html).toHaveClass(/gl-dark/);
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(await surface(), "Dark picked in GitLab must switch the tokens while the browser prefers light").not.toBe(lightSurface);
    await page.emulateMedia({ colorScheme: "dark" });
    await pickColorMode(page, 1);
    await expect(html).toHaveAttribute("data-design-theme", "light");
    expect(await surface(), "Light picked in GitLab must keep the light tokens while the browser prefers dark").toBe(lightSurface);
  } finally {
    await pickColorMode(page, 3);
  }
  await expect(html).not.toHaveAttribute("data-design-theme");
});

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "GitLab");
});

test("design: the sign-in page takes text, controls and primary action from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/users/sign_in`);
    await shown(SIGN_IN)(page);
    await assertToken(page, "main", "color", "--design-text", `sign-in ${mode}`);
    await assertToken(page, SIGN_IN, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, SIGN_IN, "color", "--design-on-primary", `sign-in ${mode}`);
    await page.locator(USERNAME).focus();
    await assertToken(page, USERNAME, "border-top-color", "--design-link", `focused sign-in field ${mode}`);
    const control = await tokenValue(page, "--design-border-strong", "color");
    const shadow = await page.locator(PASSWORD).evaluate((field) => getComputedStyle(field).boxShadow);
    expect(shadow, `sign-in field boundary ${mode}`).toContain(control);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [SIGN_IN, "main label", "main h1"], "GitLab sign-in");
});

test("design: the signed-in interface takes frame, panel, primary action, text and dividers from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await seedShowcase(page);
  await gotoOnion(page, `${base}/${PROJECT}/-/issues/new`);
  await shown(CONFIRM)(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-frame", `chrome ${mode}`);
    await assertToken(page, `${TOPBAR} a.brand-logo`, "color", "--design-on-frame", `top bar ${mode}`);
    await assertToken(page, `${TOPBAR} [data-testid='new-menu-toggle']`, "color", "--design-on-frame", `top bar ${mode}`);
    await assertToken(page, PANEL, "background-color", "--design-surface-2", `content panel ${mode}`);
    await assertToken(page, "main form", "color", "--design-text", `issue form ${mode}`);
    await assertToken(page, CONFIRM, "background-color", "--design-primary", `issue form ${mode}`);
    await assertToken(page, CONFIRM, "color", "--design-on-primary", `issue form ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, PANEL, "GitLab content panel");
  await assertReadable(page, ["main label", CONFIRM, "main h1"], "GitLab issue form");

  await gotoOnion(page, `${base}/${PROJECT}/-/labels`);
  await shown("main li.js-label-list-item")(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "main li.js-label-list-item", "border-bottom-color", "--design-border", `label list divider ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: every focus stop in the top bar draws its indicator in the frame text color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; }" });
  const onFrame = await tokenValue(page, "--design-on-frame", "color");
  await page.locator(`${TOPBAR} a.brand-logo`).focus();
  const stops = [];
  for (let step = 0; step < 12; step += 1) {
    const stop = await page.evaluate(() => {
      const element = document.activeElement;
      const style = getComputedStyle(element);
      return {
        inFrame: Boolean(element.closest(".super-topbar")),
        name: `${element.tagName}.${String(element.className).split(" ")[0]}`,
        indicator: style.outlineStyle === "none" ? style.boxShadow : style.outlineColor,
      };
    });
    if (!stop.inFrame) break;
    stops.push(stop);
    await page.keyboard.press("Tab");
  }
  expect(stops.length, "focus stops inside the top bar").toBeGreaterThan(2);
  for (const stop of stops) {
    expect(stop.indicator, `${stop.name} focus indicator`).toContain(onFrame);
  }
});

test("design: GitLab shows the generated logos and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}/users/sign_in`);
  await shown(SIGN_IN)(page);
  await expect(page.locator("main h1").first()).toHaveText(title);
  test.skip(!logoEnabled, "the logo replacement is disabled for this role");
  const logo = page.locator("img.js-portrait-logo-detection");
  await expect(logo).toHaveAttribute("src", /\/uploads\/-\/system\/appearance\//);
  expect(await logo.evaluate((image) => image.naturalWidth), "the sign-in logo must load").toBeGreaterThan(0);
  await expect(page.locator("link#favicon")).toHaveAttribute("href", /\/uploads\/-\/system\/appearance\//);
  await signIn(page);
  const header = page.locator(`${TOPBAR} [data-testid='brand-header-custom-logo']`);
  await expect(header).toBeVisible({ timeout: resolveTimeout(10_000) });
  expect(await header.evaluate((image) => image.naturalWidth), "the top bar logo must load").toBeGreaterThan(0);
});

test("design: root signs in natively and reaches the admin area", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const response = await gotoOnion(page, `${base}/admin`);
  expect(response.status(), "the admin area answers root").toBe(200);
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.locator(`${TOPBAR} [data-testid='user-menu-toggle']`)).toBeVisible({ timeout: resolveTimeout(10_000) });
});

test("design: gallery of sign-in, project, issues, merge requests, settings, admin and menus", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  await signIn(page);
  await seedShowcase(page);
  const signedIn = session;
  await page.context().clearCookies();
  const failures = [];
  await captureDesignGallery(page, [
    { name: "sign-in", url: `${base}/users/sign_in`, prepare: shown(SIGN_IN) },
    { name: "forgot-password", url: `${base}/users/password/new`, prepare: shown("#user_email") },
  ]).catch((error) => failures.push(error));
  await page.context().addCookies(signedIn);
  await captureDesignGallery(page, views()).catch((error) => failures.push(error));
  expect(failures.map((error) => String(error.message)), "gallery captures").toEqual([]);
});
