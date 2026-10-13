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

const SHOWCASE = "Design Showcase";
const PLUGIN_MANIFEST = "/plugins/infinito-design/infinito-design.json";
const PLUGIN_SHEET = "/plugins/infinito-design/infinito-design.css";
const LOGO_URL = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const LOGO_AUTH_URL = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_AUTH_URL || "");
const MODES = ["light", "dark"];

function base() {
  return decodeDotenvQuotedValue(process.env.TAIGA_BASE_URL).replace(/\/$/, "");
}

function credentials() {
  return {
    username: decodeDotenvQuotedValue(process.env.LOGIN_USERNAME),
    password: decodeDotenvQuotedValue(process.env.LOGIN_PASSWORD),
  };
}

async function ready(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
}

async function api(request, token, method, path, data) {
  const response = await apiFetchOnion(request, `${base()}/api/v1${path}`, {
    method,
    headers: token ? { Authorization: `Bearer ${token}`, "x-disable-pagination": "1" } : {},
    ...(data ? { data } : {}),
  });
  expect(response.ok(), `${method} ${path} answered ${response.status()}`).toBe(true);
  return response.status() === 204 ? null : response.json();
}

function lowestRef(entries) {
  return Math.min(...entries.map((entry) => entry.ref));
}

async function ensureShowcase(request) {
  const auth = await api(request, null, "POST", "/auth", { type: "normal", ...credentials() });
  const token = auth.auth_token;
  const call = (method, path, data) => api(request, token, method, path, data);
  let project = (await call("GET", `/projects?member=${auth.id}`)).find((entry) => entry.name === SHOWCASE);
  if (!project) {
    project = await call("POST", "/projects", { name: SHOWCASE, description: "Corporate design showcase", is_private: false });
    await call("PATCH", `/projects/${project.id}`, {
      is_backlog_activated: true,
      is_kanban_activated: true,
      is_issues_activated: true,
      is_epics_activated: true,
      is_wiki_activated: true,
    });
  }
  const pid = project.id;
  let sprints = await call("GET", `/milestones?project=${pid}`);
  if (sprints.length === 0) {
    const start = new Date();
    const finish = new Date(start.getTime() + 14 * 86_400_000);
    const day = (date) => date.toISOString().slice(0, 10);
    sprints = [await call("POST", "/milestones", { project: pid, name: "Sprint 1", estimated_start: day(start), estimated_finish: day(finish) })];
  }
  const sprint = sprints[0];
  const stories = await call("GET", `/userstories?project=${pid}`);
  if (stories.length === 0) {
    const seeds = [
      ["Sign-in page in the corporate design", sprint.id],
      ["Kanban board colors", sprint.id],
      ["Release notes", null],
      ["Dark mode review", null],
    ];
    for (const [subject, milestone] of seeds) {
      stories.push(await call("POST", "/userstories", { project: pid, subject, milestone }));
    }
    for (const subject of ["Check the logo", "Measure the contrast"]) {
      await call("POST", "/tasks", { project: pid, subject, milestone: sprint.id, user_story: stories[0].id });
    }
  }
  const issues = await call("GET", `/issues?project=${pid}`);
  if (issues.length === 0) {
    for (const subject of ["Logo is blurry on the sign-in page", "Dark mode contrast of the filters"]) {
      issues.push(await call("POST", "/issues", { project: pid, subject }));
    }
  }
  if ((await call("GET", `/epics?project=${pid}`)).length === 0) {
    await call("POST", "/epics", { project: pid, subject: "Corporate design" });
  }
  if ((await call("GET", `/wiki?project=${pid}`)).length === 0) {
    await call("POST", "/wiki", { project: pid, slug: "home", content: "# Design Showcase\n\nEvery Taiga surface in the corporate design." });
  }
  return {
    slug: project.slug,
    sprint: sprint.slug,
    story: lowestRef(stories),
    issue: lowestRef(issues),
    userId: auth.id,
    username: auth.username,
  };
}

async function signInDjangoAdmin(page) {
  const { username, password } = credentials();
  await gotoOnion(page, `${base()}/admin/login/?next=/admin/`);
  await ready(page, "#login-form");
  await page.locator("#id_username").fill(username);
  await expect(page.locator("#id_password")).toBeEditable({ timeout: resolveTimeout(10_000) });
  await page.locator("#id_password").fill(password);
  await page.locator("#login-form [type='submit']").click();
  await ready(page, "#user-tools");
}

async function assertFrameFocus(page, frameSelector, popupSelector, label) {
  const expected = {
    frame: await tokenValue(page, "--design-on-frame", "color"),
    popup: await tokenValue(page, "--design-link", "color"),
  };
  let checked = 0;
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate(
      ([frame, popup]) => {
        const element = document.activeElement;
        if (!element || !element.closest(frame)) return null;
        const style = getComputedStyle(element);
        return { where: element.closest(popup) ? "popup" : "frame", style: style.outlineStyle, color: style.outlineColor };
      },
      [frameSelector, popupSelector],
    );
    if (!stop) continue;
    checked += 1;
    expect(stop.style, `${label}: focus stop ${checked} draws no outline`).not.toBe("none");
    expect(stop.color, `${label}: focus stop ${checked} (${stop.where}) outline color`).toBe(expected[stop.where]);
  }
  expect(checked, `${label}: no focus stop inside ${frameSelector}`).toBeGreaterThan(0);
}

function galleryViews(showcase) {
  const view = (name, path, selector, extra) => ({
    name,
    url: `${base()}${path}`,
    prepare: async (p) => {
      await ready(p, selector);
      if (extra) await extra(p);
    },
  });
  const project = `/project/${showcase.slug}`;
  return {
    visitor: [
      view("discover", "/discover", ".discover-header"),
      view("discover-search", "/discover/search", "div.master input[type='text']"),
      view("login", "/login", ".auth .logo-svg"),
      view("forgot-password", "/forgot-password", ".auth form"),
      view("admin-login", "/admin/login/", "#login-form"),
    ],
    member: [
      view("dashboard", "/", "div.master .title-bar, div.master h1, div.master section"),
      view("user-menu", "/", "nav.navbar [tg-dropdown-user]", async (p) => {
        await p.locator("nav.navbar [tg-dropdown-user]").first().hover();
        const menu = p.locator(".navbar-dropdown.dropdown-user").first();
        await expect(menu).toBeVisible({ timeout: resolveTimeout(10_000) });
        await expect
          .poll(() => menu.evaluate((element) => getComputedStyle(element).opacity), { timeout: resolveTimeout(10_000) })
          .toBe("1");
      }),
      view("projects-list", "/projects/", "div.master h1"),
      view("project-new", "/project/new", "div.master h1"),
      view("timeline", `${project}/timeline`, "div.master .timeline, div.master section"),
      view("backlog", `${project}/backlog`, ".backlog-table-body .row"),
      view("taskboard", `${project}/taskboard/${showcase.sprint}`, ".taskboard-table, .taskboard"),
      view("kanban", `${project}/kanban`, ".kanban-table-header, .kanban-table"),
      view("issues", `${project}/issues`, ".issues-table .row, .issues-table"),
      view("issue-detail", `${project}/issue/${showcase.issue}`, "div.master [class*='detail']:visible"),
      view("us-detail", `${project}/us/${showcase.story}`, "div.master [class*='detail']:visible"),
      view("epics", `${project}/epics`, ".epics-table, div.master h1"),
      view("wiki", `${project}/wiki/home`, ".wiki-content, div.master h1"),
      view("team", `${project}/team`, ".table-team, div.master h1"),
      view("admin-project-details", `${project}/admin/project-profile/details`, ".menu-secondary"),
      view("admin-modules", `${project}/admin/project-profile/modules`, ".menu-secondary"),
      view("admin-status", `${project}/admin/project-values/status`, ".menu-secondary"),
      view("admin-roles", `${project}/admin/roles`, ".menu-secondary"),
      view("user-settings-profile", "/user-settings/user-profile", ".menu-secondary"),
      view("user-settings-notifications", "/user-settings/mail-notifications", ".menu-secondary"),
      view("profile", `/profile/${showcase.username}`, ".profile-bar, div.master section"),
      view("django-index", "/admin/", "#content-main"),
      view("django-users", "/admin/users/user/", "#result_list"),
      view("django-user-change", `/admin/users/user/${showcase.userId}/change/`, "#content-main form"),
    ],
  };
}

exports.register = function (shared) {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    expect(process.env.DESIGN_SERVICE_ENABLED).toBe("true");
    await gotoOnion(page, `${base()}/discover`);
    await ready(page, "nav.navbar");
    await assertDesignTokens(page, "taiga");
  });

  test("design: the front loads the design plugin through conf.json without a register link", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base()}/login`);
    await ready(page, ".auth .logo-svg");
    const config = await page.evaluate(() => ({
      plugins: window.taigaConfig.contribPlugins,
      register: window.taigaConfig.publicRegisterEnabled,
    }));
    expect(config.plugins, "conf.json must list the design plugin").toContain(PLUGIN_MANIFEST);
    expect(config.register, "conf.json must keep public registration off").toBe(false);
    await expect(page.locator(`link[rel='stylesheet'][href='${PLUGIN_SHEET}']`)).toHaveCount(1);
    await expect(page.locator("a[href*='register']")).toHaveCount(0);
  });

  test("design: public pages map the navbar frame, surfaces and text", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base()}/discover`);
    await ready(page, ".discover-header");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "nav.navbar", "background-color", "--design-frame", `taiga navbar ${mode}`);
      await assertToken(page, ".discover-header", "background-color", "--design-surface-3", `taiga discover header ${mode}`);
      await assertToken(page, ".discover-header input[type='text']", "background-color", "--design-surface-1", `taiga search ${mode}`);
      await assertToken(page, "div.master h1", "color", "--design-link", `taiga heading ${mode}`);
      await assertToken(page, "nav.navbar a.login", "color", "--design-on-frame", `taiga navbar sign-in link ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".discover-header", "taiga discover");
    await assertReadable(page, ["div.master h1", { selector: ".discover-header .project-number", optional: true }], "taiga discover");
  });

  test("design: the navbar and the sign-in page show the corporate logo", async ({ page, request }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!LOGO_URL, "no logo configured");
    await gotoOnion(page, `${base()}/discover`);
    await ready(page, "nav.navbar .nav-left .logo");
    const logo = page.locator("nav.navbar .nav-left .logo").first();
    expect(await logo.evaluate((element) => getComputedStyle(element).backgroundImage)).toContain(LOGO_URL);
    await expect(page.locator("nav.navbar .nav-left .logo svg").first()).toBeHidden();
    const box = await logo.boundingBox();
    expect(Math.abs(box.width - box.height), "the navbar logo box is square").toBeLessThanOrEqual(2);
    await gotoOnion(page, `${base()}/login`);
    await ready(page, ".auth .logo-svg");
    expect(await page.locator(".auth .logo-svg").first().evaluate((element) => getComputedStyle(element).backgroundImage)).toContain(LOGO_AUTH_URL);
    for (const url of [LOGO_URL, LOGO_AUTH_URL]) {
      const response = await apiGetOnion(request, url, { ignoreHTTPSErrors: true });
      expect(response.status(), `${url} is served`).toBe(200);
      expect(response.headers()["content-type"]).toContain("image/svg+xml");
    }
  });

  test("design: navbar focus stops draw their indicator in the frame text color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.loginToTaigaForVariant(page);
    await gotoOnion(page, `${base()}/`);
    await ready(page, "nav.navbar .nav-right");
    await assertToken(page, "nav.navbar .dropdown-project-list > a", "color", "--design-on-frame", "taiga navbar projects button");
    await page.locator("body").click({ position: { x: 600, y: 400 } });
    await assertFrameFocus(page, "nav.navbar", ".navbar-dropdown, .navbar-dropdown-notifications", "taiga navbar");
  });

  test("design: signed-in backlog maps actions, dividers and the project navigation", async ({ page, request }) => {
    skipUnlessServiceEnabled("design");
    const showcase = await ensureShowcase(request);
    await shared.loginToTaigaForVariant(page);
    await gotoOnion(page, `${base()}/project/${showcase.slug}/backlog`);
    await ready(page, ".backlog-table-body .row");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".btn-small[variant='primary']", "background-color", "--design-primary", `taiga primary ${mode}`);
      await assertToken(page, ".btn-small[variant='primary']", "color", "--design-on-primary", `taiga primary text ${mode}`);
      await assertToken(page, ".sprints .sprint-table .row", "border-bottom-color", "--design-border", `taiga sprint divider ${mode}`);
      await assertToken(page, ".backlog-table-body .row", "background-color", "--design-surface-2", `taiga backlog card ${mode}`);
      await assertToken(page, "tg-project-navigation", "background-color", "--design-frame", `taiga project navigation ${mode}`);
      await assertToken(page, "tg-project-menu", "background-color", "--design-frame", `taiga project menu ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".backlog-table-body .row", "taiga backlog");
    await assertReadable(page, [".backlog-table-body .row", { selector: ".summary .data .number", optional: true }], "taiga backlog");
  });

  test("design: the password recovery page keeps its text readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base()}/forgot-password`);
    await ready(page, ".forgot-form-container .forgot-text");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".forgot-form-container .forgot-text", "color", "--design-text", `taiga recovery text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [".forgot-form-container .forgot-text", { selector: ".auth .login-text a", optional: true }], "taiga recovery");
  });

  test("design: the comment editor on a story follows the tokens", async ({ page, request }) => {
    skipUnlessServiceEnabled("design");
    const showcase = await ensureShowcase(request);
    await shared.loginToTaigaForVariant(page);
    await gotoOnion(page, `${base()}/project/${showcase.slug}/us/${showcase.story}`);
    await ready(page, ".ck-editor__editable:visible");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".ck-editor__editable:visible", "background-color", "--design-surface-2", `taiga comment editor ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the Django admin maps its variables onto the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base()}/admin/login/`);
    await ready(page, "#login-form");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#header", "background-color", "--design-frame", `django header ${mode}`);
      await assertToken(page, "#header", "color", "--design-on-frame", `django header text ${mode}`);
      await assertToken(page, "#login-form [type='submit']", "background-color", "--design-primary", `django submit ${mode}`);
      await assertToken(page, "#login-form [type='submit']", "color", "--design-on-primary", `django submit text ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await signInDjangoAdmin(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `django body ${mode}`);
      await assertToken(page, ".module caption", "background-color", "--design-frame", `django module caption ${mode}`);
      await assertToken(page, "#content-main td, #content-main th", "border-bottom-color", "--design-border", `django table divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#content-main", "django index");
    await assertReadable(page, ["#content-main th a", ".module caption a"], "django index");
  });

  test("design: gallery", async ({ page, request, browser }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "gallery runs only with INFINITO_PLAYWRIGHT_KEEP=true");
    test.setTimeout(resolveTimeout(900_000));
    const { visitor, member } = galleryViews(await ensureShowcase(request));
    const failures = [];
    const visitorContext = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      await captureDesignGallery(await visitorContext.newPage(), visitor);
    } catch (error) {
      failures.push(error.message);
    } finally {
      await visitorContext.close();
    }
    await shared.loginToTaigaForVariant(page);
    await signInDjangoAdmin(page);
    try {
      await captureDesignGallery(page, member);
    } catch (error) {
      failures.push(error.message);
    }
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
