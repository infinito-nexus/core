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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, performKeycloakLogin, readEnv } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const SHOWCASE_SHORTNAME = "design-showcase";
const SHOWCASE_FULLNAME = "Corporate design showcase";
const SHOWCASE_ACTIVITIES = [
  { module: "forum", name: "Design questions" },
  { module: "assign", name: "Palette review" },
];
const USER_MENU = "#user-menu-toggle";
const PRIMARY_NAVIGATION = ".primarynav-navbar > .moremenu";
const MODE_TOGGLE = "#colourmode-menu-toggle";
const COLOUR_MODE_PREFERENCE = "/api/rest/v2/user/current/preferences/theme_boost_colourmode";
const PRIMARY_DRAWER = ".drawer.drawer-primary";
const USER_TOUR = '[data-role="flexitour-step"]';
const MODES = ["light", "dark"];
const BOOST_SHEET = 'link[rel="stylesheet"][href*="/theme/styles.php/boost/"]';

const designTitle = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
const logoEnabled = process.env.DESIGN_LOGO_ENABLED === "true";
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD);

async function fillSecret(field, secret) {
  await expect(async () => {
    await expect(field).toBeEditable();
    await field.fill(secret);
    expect(await field.evaluate((element, expected) => element.value === expected, secret)).toBe(true);
  }).toPass({ timeout: resolveTimeout(30_000) });
}

async function endUserTour(page) {
  if (!(await page.content()).includes('"startTour":true')) return;
  const end = page.locator(`${USER_TOUR} [data-role="end"]`).first();
  const shown = await end.waitFor({ timeout: resolveTimeout(10_000) }).then(
    () => true,
    () => false,
  );
  if (!shown) return;
  await end.click();
  await expect(page.locator("[data-flexitour]")).toHaveCount(0);
}

async function signIn(page, shared) {
  const base = shared.env.moodleBaseUrl;
  if (shared.env.ssoEnabled) {
    await gotoOnion(page, `${base}/auth/oidc/?source=loginpage`);
    await performKeycloakLogin(page, shared.env.adminUsername, shared.env.adminPassword, readEnv("CANONICAL_DOMAIN"));
  } else {
    await gotoOnion(page, `${base}/login/index.php`);
    await page.waitForLoadState("load");
    await page.locator("#username").fill(shared.env.adminUsername);
    await fillSecret(page.locator("#password"), adminNativePassword);
    await page.locator("#loginbtn").click();
  }
  await expect(page.locator(USER_MENU)).toBeVisible({ timeout: resolveTimeout(60_000) });
  await endUserTour(page);
}

async function pageReady(page) {
  await endUserTour(page);
  await expect(page.locator(`${PRIMARY_NAVIGATION}:not(.observed):visible`)).toHaveCount(0, {
    timeout: resolveTimeout(10_000),
  });
  await expect(page.locator(".bg-pulse-grey:visible")).toHaveCount(0, { timeout: resolveTimeout(10_000) });
}

async function openSignedIn(page, shared, path, selector) {
  await signIn(page, shared);
  await gotoOnion(page, `${shared.env.moodleBaseUrl}${path}`);
  await page.locator(selector).first().waitFor();
  await pageReady(page);
}

async function pickMode(page, mode) {
  const saved = page.waitForResponse(
    (response) => response.url().endsWith(COLOUR_MODE_PREFERENCE) && response.request().method() === "POST",
    { timeout: resolveTimeout(10_000) },
  );
  await expect(async () => {
    await page.locator(`[data-action="set-colourmode"][data-colourmode="${mode}"]`).dispatchEvent("click");
    await expect(page.locator("html")).toHaveAttribute("data-colourmode", mode, { timeout: resolveTimeout(1_000) });
  }).toPass({ timeout: resolveTimeout(10_000) });
  expect((await saved).ok(), `Moodle stores the colour mode "${mode}" on the account`).toBe(true);
}

async function settled(locator) {
  await expect
    .poll(() => locator.evaluate((element) => element.getAnimations({ subtree: true }).length), {
      timeout: resolveTimeout(10_000),
    })
    .toBe(0);
}

async function openDropdown(page, toggleSelector) {
  const toggle = page.locator(toggleSelector);
  const menu = page.locator(`#${await toggle.getAttribute("aria-controls")}`);
  await expect(async () => {
    if (!(await menu.isVisible())) await toggle.click();
    await expect(menu).toBeVisible({ timeout: resolveTimeout(1_000) });
  }).toPass({ timeout: resolveTimeout(10_000) });
  await settled(menu);
  return menu;
}

async function openDrawer(page) {
  const drawer = page.locator(PRIMARY_DRAWER);
  await page.locator(".navbar-toggler").first().click();
  await expect(drawer).toHaveClass(/\bshow\b/, { timeout: resolveTimeout(10_000) });
  await settled(drawer);
  await expect
    .poll(() => drawer.evaluate((element) => Math.round(element.getBoundingClientRect().left)), {
      timeout: resolveTimeout(10_000),
    })
    .toBeGreaterThanOrEqual(0);
}

async function seedShowcaseCourse(page, base) {
  await gotoOnion(page, `${base}/course/search.php?search=${SHOWCASE_SHORTNAME}`);
  await page.locator("#region-main").waitFor();
  const existing = page.locator('#region-main a[href*="/course/view.php?id="]').first();
  let course;
  if ((await existing.count()) > 0) {
    course = new URL(await existing.getAttribute("href")).searchParams.get("id");
  } else {
    await gotoOnion(page, `${base}/course/edit.php?category=1`);
    await pageReady(page);
    await page.locator("#id_fullname").fill(SHOWCASE_FULLNAME);
    await page.locator("#id_shortname").fill(SHOWCASE_SHORTNAME);
    await page.locator("#id_saveanddisplay").click();
    await page.waitForURL(/[?&]id=\d+/, { timeout: resolveTimeout(60_000) });
    course = new URL(page.url()).searchParams.get("id");
  }
  const activities = {};
  for (const { module, name } of SHOWCASE_ACTIVITIES) {
    const link = page.locator(`.activity a[href*="/mod/${module}/view.php?id="]`).first();
    await gotoOnion(page, `${base}/course/view.php?id=${course}`);
    await page.locator("#region-main").waitFor();
    if ((await link.count()) === 0) {
      await gotoOnion(page, `${base}/course/modedit.php?add=${module}&course=${course}&section=1&return=0`);
      await pageReady(page);
      await page.locator("#id_name").fill(name);
      await page.locator("#id_submitbutton2").click();
      await link.waitFor({ state: "attached", timeout: resolveTimeout(60_000) });
    }
    activities[module] = await link.getAttribute("href");
  }
  return { course, activities };
}

exports.register = function (shared) {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignedIn(page, shared, "/my/", "#region-main");
    await assertDesignTokens(page, "moodle");
  });

  test("design: the Boost theme carries page, panel, text and primary action", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignedIn(page, shared, "/user/edit.php", "#id_submitbutton");

    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("html")).toHaveAttribute("data-bs-theme", mode);
      await assertToken(page, "body", "background-color", "--design-surface-1", `moodle ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `moodle ${mode}`);
      await assertToken(page, "#id_submitbutton", "background-color", "--design-primary", `moodle ${mode}`);
      await assertToken(page, "#id_submitbutton", "color", "--design-on-primary", `moodle ${mode}`);
      await assertToken(page, "#id_cancel", "background-color", "--design-surface-3", `moodle ${mode}`);
      await assertToken(page, "#id_cancel", "color", "--design-text", `moodle ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#region-main", "moodle");
    await assertReadable(
      page,
      ["body", "#region-main", "#region-main a", "#id_submitbutton", "#id_cancel", ".navbar.fixed-top .nav-link"],
      "moodle",
    );
  });

  test("design: a table divider takes the border token in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignedIn(page, shared, "/admin/tool/task/scheduledtasks.php", "table.generaltable td");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("html")).toHaveAttribute("data-bs-theme", mode);
      await assertToken(page, "table.generaltable td", "border-bottom-color", "--design-border", `moodle ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: tinted chips stay readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignedIn(page, shared, "/admin/tool/task/scheduledtasks.php", "table.generaltable td");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("html")).toHaveAttribute("data-bs-theme", mode);
      await assertToken(page, ".badge.bg-secondary", "background-color", "--design-surface-3", `moodle chip ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(
      page,
      [{ selector: ".badge.bg-secondary", optional: true }, "table.generaltable td"],
      "moodle chips",
    );
  });

  test("design: tinted regions keep the panels inside them light", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = shared.env.moodleBaseUrl;
    await signIn(page, shared);
    const { course } = await seedShowcaseCourse(page, base);
    await gotoOnion(page, `${base}/user/index.php?id=${course}`);
    await page.locator("#region-main").waitFor();
    await pageReady(page);
    const tone = await tokenValue(page, "--design-text", "background-color");
    const painted = await page.locator("#region-main *").evaluateAll(
      (nodes, text) =>
        nodes
          .filter((node) => node.getBoundingClientRect().width > 300 && getComputedStyle(node).backgroundColor === text)
          .map((node) => String(node.className).slice(0, 80)),
      tone,
    );
    expect(painted, "no wide region of the participants page is painted in the text tone").toEqual([]);
  });

  test("design: the compiled theme sheet carries the token mapping", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php?noredirect=1`);
    const href = await page.locator(BOOST_SHEET).first().getAttribute("href");
    const sheet = await apiGetOnion(page.request, href);
    expect(sheet.ok(), "Moodle serves the compiled Boost sheet").toBe(true);
    expect(
      await sheet.text(),
      "a raw SCSS that fails to compile makes Moodle serve its precompiled sheet without the mapping",
    ).toContain("var(--design-surface-1)");
  });

  test("design: the sign-in page shows the frame panel and a primary button in the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php?noredirect=1`);
    await page.locator("#loginbtn").waitFor();
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("html")).toHaveAttribute("data-bs-theme", mode);
      await assertToken(page, ".login-layout-left", "background-color", "--design-frame", `moodle ${mode}`);
      await assertToken(page, ".login-layout-left-content", "color", "--design-on-frame", `moodle ${mode}`);
      await assertToken(page, "#loginbtn", "background-color", "--design-primary", `moodle ${mode}`);
      await assertToken(page, "#loginbtn", "color", "--design-on-primary", `moodle ${mode}`);
      await assertToken(page, "#page", "background-color", "--design-surface-2", `moodle ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    expect(
      await page.locator(".login-layout-left").evaluate((panel) => getComputedStyle(panel).backgroundImage),
      "the frame panel shows no stock photograph while no login background image is configured",
    ).toBe("none");
    await assertReadable(page, [".login-layout-left-content h1", ".loginform h1", "#loginbtn"], "moodle sign-in");
  });

  test("design: the colour mode a user picks overrides the browser preference", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await openSignedIn(page, shared, "/user/preferences.php", "#region-main");
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");
    try {
      await pickMode(page, "dark");
      await expect(page.locator("html")).toHaveAttribute("data-bs-theme", "dark");
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
      expect(
        await tokenValue(page, "--design-surface-1", "background-color"),
        "the dark colour mode must switch the tokens while the browser prefers light",
      ).not.toBe(lightSurface);
      await assertToken(page, "body", "background-color", "--design-surface-1", "moodle dark colour mode");

      await page.emulateMedia({ colorScheme: "dark" });
      await pickMode(page, "light");
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
      expect(
        await tokenValue(page, "--design-surface-1", "background-color"),
        "the light colour mode must keep the light tokens while the browser prefers dark",
      ).toBe(lightSurface);
    } finally {
      await pickMode(page, "auto");
      await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
      await gotoOnion(page, page.url());
      await expect(page.locator("html"), "the account is back on the site default").toHaveAttribute("data-colourmode", "auto");
    }
  });

  test("design: the mobile navigation drawer carries the served lockup", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoEnabled, "no logo is configured for this deployment");
    await page.setViewportSize({ width: 390, height: 844 });
    await openSignedIn(page, shared, "/my/", "#region-main");
    const logo = page.locator(".drawer-primary img.logo");
    await expect(logo).toHaveAttribute("src", /\/core_admin\/logocompact\//);
    const served = await apiGetOnion(page.request, await logo.getAttribute("src"));
    expect(served.ok(), "Moodle serves the drawer logo").toBe(true);
    expect(served.headers()["content-type"], "the drawer logo is the generated PNG").toContain("image/png");
    await openDrawer(page);
    const box = await logo.boundingBox();
    expect(box.width, "the drawer logo is a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
    expect(box.x + box.width, "the drawer logo fits the viewport").toBeLessThanOrEqual(390);
  });

  test("design: open menus show hover and selection in the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignedIn(page, shared, "/user/preferences.php", "#region-main");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator("html")).toHaveAttribute("data-bs-theme", mode);
      await openDropdown(page, USER_MENU);
      const entry = "#user-action-menu a.dropdown-item";
      await page.locator(entry).first().hover();
      await assertToken(page, `${entry}:hover`, "background-color", "--design-surface-3", `moodle hovered entry ${mode}`);
      await assertToken(page, `${entry}:hover`, "color", "--design-text", `moodle hovered entry ${mode}`);
      await page.keyboard.press("Escape");
      await openDropdown(page, MODE_TOGGLE);
      const active = "#colourmode-action-menu .dropdown-item.active";
      await assertToken(page, active, "background-color", "--design-primary", `moodle selected mode ${mode}`);
      await assertToken(page, active, "color", "--design-on-primary", `moodle selected mode ${mode}`);
      await page.keyboard.press("Escape");
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: every page title carries the configured site name", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php?noredirect=1`);
    await page.locator("#loginbtn").waitFor();
    await expect(page).toHaveTitle(new RegExp(designTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  test("design: Moodle serves the generated logos and the favicon", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoEnabled, "no logo is configured for this deployment");
    const base = shared.env.moodleBaseUrl;
    await gotoOnion(page, `${base}/login/index.php?noredirect=1`);
    await page.locator("#loginbtn").waitFor();
    await expect(page.locator("#logoimage")).toHaveAttribute("src", /\/core_admin\/logo\//);
    await expect(page.locator('link[rel="shortcut icon"]')).toHaveAttribute("href", /\/core_admin\/favicon\//);
    await expect
      .poll(() => page.locator("#logoimage").evaluate((image) => image.complete && image.naturalWidth > 0))
      .toBe(true);

    await signIn(page, shared);
    await gotoOnion(page, `${base}/my/`);
    await pageReady(page);
    const logo = page.locator(".navbar-brand img.logo");
    await expect(logo).toHaveAttribute("src", /\/core_admin\/logocompact\//);
    await expect.poll(() => logo.evaluate((image) => image.complete && image.naturalWidth > 0)).toBe(true);
    const box = await logo.boundingBox();
    expect(box.width, "the navigation logo is a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
  });

  test("design: gallery of sign-in, user and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(840_000));
    const base = shared.env.moodleBaseUrl;
    const failures = [];
    const capture = async (views) => {
      try {
        await captureDesignGallery(page, views);
      } catch (error) {
        failures.push(error.message);
      }
    };
    const view = (name, url, open) => ({
      name,
      url: url.startsWith("http") ? url : `${base}${url}`,
      prepare: async (opened) => {
        await pageReady(opened);
        if (open) await open(opened);
      },
    });

    await capture([view("login", "/login/index.php?noredirect=1"), view("forgot-password", "/login/forgot_password.php")]);

    await signIn(page, shared);
    const { course, activities } = await seedShowcaseCourse(page, base);

    await capture([
      view("dashboard", "/my/"),
      view("course-categories", "/course/index.php"),
      view("course-view", `/course/view.php?id=${course}`),
      view("forum-view", activities.forum),
      view("assignment-view", activities.assign),
      view("course-settings", `/course/edit.php?id=${course}`),
      view("course-participants", `/user/index.php?id=${course}`),
      view("course-grades", `/grade/report/grader/index.php?id=${course}`),
      view("calendar-month", "/calendar/view.php?view=month"),
      view("profile", "/user/profile.php"),
      view("profile-edit", "/user/edit.php"),
      view("preferences", "/user/preferences.php"),
      view("notification-preferences", "/message/notificationpreferences.php"),
      view("messages", "/message/index.php"),
      view("user-menu", "/user/preferences.php", (opened) => openDropdown(opened, USER_MENU)),
      view("colour-mode-menu", "/user/preferences.php", (opened) => openDropdown(opened, MODE_TOGGLE)),
      view("admin-overview", "/admin/search.php"),
      view("admin-notifications", "/admin/index.php"),
      view("admin-users", "/admin/user.php"),
      view("admin-user-create", "/user/editadvanced.php?id=-1"),
      view("admin-roles", "/admin/roles/manage.php"),
      view("admin-plugins", "/admin/plugins.php"),
      view("admin-scheduled-tasks", "/admin/tool/task/scheduledtasks.php"),
      view("admin-course-management", "/course/management.php"),
      view("admin-theme-boost", "/admin/settings.php?section=themesettingboost"),
      view("admin-logos", "/admin/settings.php?section=logos"),
    ]);

    expect(failures, failures.join("\n")).toEqual([]);
  });
};
