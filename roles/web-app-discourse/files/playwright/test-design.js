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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const READY_MS = 10_000;
const SHOWCASE_TITLE = "Corporate design showcase topic";

function env(name) {
  return decodeDotenvQuotedValue(process.env[name]);
}

function baseUrl() {
  return normalizeBaseUrl(env("DISCOURSE_BASE_URL"));
}

async function ready(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
}

async function settled(page, selector) {
  await ready(page, selector);
  await expect
    .poll(
      () =>
        page
          .locator(selector)
          .first()
          .evaluate((el) => el.getAnimations({ subtree: true }).filter((a) => a.playState === "running").length),
      { timeout: resolveTimeout(READY_MS) },
    )
    .toBe(0);
}

async function openLatest(page) {
  await gotoOnion(page, `${baseUrl()}/latest`);
  await ready(page, ".topic-list-item");
}

async function signIn(page) {
  const base = baseUrl();
  if (isServiceEnabled("sso")) {
    const issuer = normalizeBaseUrl(env("OIDC_ISSUER_URL"));
    await gotoOnion(page, `${base}/`);
    await page
      .locator("a, button")
      .filter({ hasText: /log\s*in|sign\s*in/i })
      .first()
      .click({ timeout: resolveTimeout(30_000) });
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000) })
      .toContain(`${issuer}/protocol/openid-connect/auth`);
    await performKeycloakLoginForm(page, env("ADMIN_USERNAME"), env("ADMIN_PASSWORD"));
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
    await gotoOnion(page, `${base}/latest`);
  } else {
    await gotoOnion(page, `${base}/login`);
    const name = page.locator("#login-account-name");
    const password = page.locator("#login-account-password");
    await expect(name).toBeEditable({ timeout: resolveTimeout(READY_MS) });
    await name.fill(env("ADMIN_USERNAME"));
    await expect(password).toBeEditable({ timeout: resolveTimeout(READY_MS) });
    await password.fill(env("ADMIN_PASSWORD"));
    await password.press("Enter");
  }
  await expect(page.locator(".header-dropdown-toggle.current-user")).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
}

async function seedShowcase(page) {
  return page.evaluate(
    async ({ title, admin }) => {
      const { csrf } = await (await fetch("/session/csrf.json")).json();
      const headers = { "X-CSRF-Token": csrf, "Content-Type": "application/json" };
      const own = await (await fetch(`/topics/created-by/${encodeURIComponent(admin)}.json`)).json();
      let topic = (own.topic_list?.topics || []).find((entry) => entry.title === title);
      if (!topic) {
        const categories = (await (await fetch("/categories.json")).json()).category_list.categories;
        const category = categories.find((entry) => entry.slug === "general") || categories[0];
        const created = await fetch("/posts.json", {
          method: "POST",
          headers,
          body: JSON.stringify({
            title,
            category: category.id,
            raw: "Light mode, dark mode and the mobile layout are reviewed in this topic.",
          }),
        });
        topic = { id: (await created.json()).topic_id };
      }
      const detail = await (await fetch(`/t/${topic.id}.json`)).json();
      for (let n = detail.posts_count; n < 3; n += 1) {
        await fetch("/posts.json", {
          method: "POST",
          headers,
          body: JSON.stringify({ topic_id: topic.id, raw: `Reply number ${n} shows how the post stream takes the palette.` }),
        });
      }
      return topic.id;
    },
    { title: SHOWCASE_TITLE, admin: env("ADMIN_USERNAME") },
  );
}

function signedInViews(base, admin, topicId) {
  return [
    { name: "latest", url: `${base}/latest`, ready: ".topic-list-item" },
    { name: "categories", url: `${base}/categories`, ready: "#main-outlet .category-list, #main-outlet .category-boxes" },
    { name: "top", url: `${base}/top`, ready: "#main-outlet .top-lists" },
    { name: "topic", url: `${base}/t/${topicId}`, ready: "#post_1 .cooked" },
    { name: "about", url: `${base}/about`, ready: "#main-outlet .about__main-content" },
    { name: "guidelines", url: `${base}/guidelines`, ready: "#main-outlet .body-page" },
    { name: "search", url: `${base}/search?q=showcase`, ready: ".fps-result" },
    { name: "users-directory", url: `${base}/u`, ready: ".directory-table" },
    { name: "badges", url: `${base}/badges`, ready: ".badge-groups" },
    { name: "groups", url: `${base}/g`, ready: ".groups-boxes" },
    { name: "composer", url: `${base}/new-topic`, ready: "#reply-control.open .d-editor-input", settle: "#reply-control" },
    {
      name: "user-menu",
      url: `${base}/latest`,
      ready: ".header-dropdown-toggle.current-user",
      click: ".header-dropdown-toggle.current-user button",
      settle: ".user-menu.revamped",
    },
    { name: "user-summary", url: `${base}/u/${admin}/summary`, ready: ".user-main" },
    { name: "user-activity", url: `${base}/u/${admin}/activity`, ready: "#main-outlet .user-content" },
    { name: "preferences-account", url: `${base}/u/${admin}/preferences/account`, ready: ".user-preferences" },
    { name: "preferences-profile", url: `${base}/u/${admin}/preferences/profile`, ready: ".user-preferences" },
    { name: "preferences-interface", url: `${base}/u/${admin}/preferences/interface`, ready: ".user-preferences .control-group" },
    { name: "notifications", url: `${base}/u/${admin}/notifications`, ready: ".user-notifications-list, #main-outlet .empty-state" },
    { name: "messages", url: `${base}/u/${admin}/messages`, ready: "#main-outlet .user-content" },
    { name: "admin-dashboard", url: `${base}/admin`, ready: "#main-outlet .admin-contents.dashboard" },
    { name: "admin-users", url: `${base}/admin/users/list/active`, ready: ".users-list, .directory-table" },
    { name: "admin-site-settings", url: `${base}/admin/site_settings/category/required`, ready: "#main-outlet .admin-contents.admin-site-settings" },
    { name: "admin-themes", url: `${base}/admin/config/customize/themes`, ready: ".theme-card, .themes-list" },
    { name: "admin-palettes", url: `${base}/admin/config/colors`, ready: ".color-palette, .admin-config-color-palettes" },
    { name: "admin-plugins", url: `${base}/admin/plugins`, ready: "#main-outlet .admin-plugins-list-container" },
    { name: "admin-logs", url: `${base}/admin/logs/staff_action_logs`, ready: ".staff-actions, #main-outlet table" },
    { name: "review", url: `${base}/review`, ready: ".reviewable-filters, .reviewables" },
  ];
}

async function prepareView(page, view) {
  await ready(page, view.ready);
  await expect(page.locator("#main-outlet .spinner")).toHaveCount(0, { timeout: resolveTimeout(READY_MS) });
  if (view.click) await page.locator(view.click).first().click({ timeout: resolveTimeout(READY_MS) });
  if (view.settle) await settled(page, view.settle);
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLatest(page);
    await assertDesignTokens(page, "discourse");
  });

  test("design: the default theme carries the corporate palettes in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLatest(page);
    await expect(page.locator("link.light-scheme[data-scheme-id]")).toHaveCount(1);
    await expect(page.locator("link.dark-scheme[data-scheme-id]")).toHaveCount(1);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `discourse ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `discourse ${mode}`);
      await assertToken(page, ".d-header", "background-color", "--design-frame", `discourse ${mode}`);
      await assertToken(page, ".topic-list-item .title", "color", "--design-text", `discourse ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#main-outlet", "discourse");
    await assertReadable(
      page,
      [
        "body",
        ".topic-list-item .title",
        ".nav-pills > li > a",
        { selector: ".topic-list-item .badge-category__name", optional: true },
        { selector: ".topic-list-item .activity", optional: true },
      ],
      "discourse",
    );
  });

  test("design: the palettes Discourse compiles equal the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLatest(page);
    const compiled = await page.evaluate(async () => {
      const read = async (selector) => {
        const href = document.querySelector(selector)?.href;
        return href ? (await fetch(href)).text() : "";
      };
      return { light: await read("link.light-scheme"), dark: await read("link.dark-scheme") };
    });
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      for (const [name, token] of [
        ["--secondary", "--design-surface-1"],
        ["--primary", "--design-text"],
        ["--tertiary", "--design-link"],
        ["--header_background", "--design-frame"],
      ]) {
        const literal = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{3,8})`).exec(compiled[mode]);
        expect(literal, `discourse ${mode}: the compiled palette defines ${name}`).not.toBeNull();
        const asToken = await page.evaluate((hex) => {
          const probe = document.createElement("span");
          probe.style.color = hex;
          document.body.appendChild(probe);
          const value = getComputedStyle(probe).color;
          probe.remove();
          return value;
        }, literal[1]);
        expect(asToken, `discourse ${mode}: compiled ${name} equals ${token}`).toBe(await tokenValue(page, token, "color"));
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: primary action, dividers and header focus follow the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${baseUrl()}/latest`);
    await ready(page, "#create-topic");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#create-topic", "background-color", "--design-primary", `discourse new topic ${mode}`);
      await assertToken(page, "#create-topic", "color", "--design-on-primary", `discourse new topic ${mode}`);
      await assertToken(page, ".topic-list-item", "border-bottom-color", "--design-border", `discourse rows ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    const onFrame = await tokenValue(page, "--design-on-frame", "outline-color");
    await page.locator("body").focus();
    let checked = 0;
    for (let stop = 0; stop < 8; stop += 1) {
      await page.keyboard.press("Tab");
      const sample = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || !el.closest(".d-header") || el.closest(".menu-panel")) return null;
        const style = getComputedStyle(el);
        return { outline: style.outlineColor, style: style.outlineStyle };
      });
      if (sample === null) continue;
      checked += 1;
      expect(sample.style, "a focus stop inside the header draws an outline").not.toBe("none");
      expect(sample.outline, "focus inside the header draws in --design-on-frame").toBe(onFrame);
    }
    expect(checked, "the Tab walk reached the header").toBeGreaterThan(0);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      for (const icon of [".d-header .btn-sidebar-toggle .d-icon", ".d-header .header-dropdown-toggle .d-icon"]) {
        await assertToken(page, icon, "color", "--design-on-frame", `discourse header icon ${mode}`);
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the admin sidebar marks the active entry from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${baseUrl()}/admin`);
    const active = ".admin-panel .sidebar-section-link.active";
    await ready(page, active);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".admin-panel", "background-color", "--design-surface-3", `discourse admin sidebar ${mode}`);
      await assertToken(page, active, "background-color", "--design-surface-active", `discourse admin sidebar ${mode}`);
      await assertToken(page, active, "color", "--design-text", `discourse admin sidebar ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [active, ".admin-panel .sidebar-section-link:not(.active)"], "discourse admin sidebar");
  });

  test("design: signed-in pages carry no profiler badge that floods the request limit", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const profiled = [];
    page.on("request", (request) => {
      if (request.url().includes("/mini-profiler-resources/")) profiled.push(new URL(request.url()).pathname);
    });
    await signIn(page);
    await gotoOnion(page, `${baseUrl()}/admin`);
    await ready(page, "#main-outlet .admin-contents.dashboard");
    await expect(page.locator(".profiler-results")).toHaveCount(0);
    expect(profiled, "no request goes to the mini profiler").toEqual([]);
  });

  test("design: the sign-in page keeps the logo on the frame and paints its buttons from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(isServiceEnabled("sso"), "the sign-in page is the identity provider's");
    await gotoOnion(page, `${baseUrl()}/login`);
    await ready(page, "#login-account-name");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, ".d-header", "background-color", "--design-frame", `discourse login header ${mode}`);
      await assertToken(page, "#login-button", "background-color", "--design-primary", `discourse login ${mode}`);
      await assertToken(page, "#login-button", "color", "--design-on-primary", `discourse login ${mode}`);
      if ((await page.locator(".btn-social").count()) > 0) {
        await assertToken(page, ".btn-social", "background-color", "--design-surface-2", `discourse login ${mode}`);
        await assertToken(page, ".btn-social", "color", "--design-text", `discourse login ${mode}`);
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: a forced Discourse color mode switches the tokens with it", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = baseUrl();
    await page.emulateMedia({ colorScheme: "light" });
    await openLatest(page);
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");
    await page.context().addCookies([{ name: "forced_color_mode", value: "dark", url: base }]);
    await openLatest(page);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    expect(await tokenValue(page, "--design-surface-1", "background-color")).not.toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "discourse forced dark");
    await page.emulateMedia({ colorScheme: "dark" });
    await page.context().addCookies([{ name: "forced_color_mode", value: "light", url: base }]);
    await openLatest(page);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
    expect(await tokenValue(page, "--design-surface-1", "background-color")).toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "discourse forced light");
  });

  test("design: Discourse shows the corporate logo and title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await openLatest(page);
    if (title) {
      await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
    if (!logoUrl) return;
    const logo = page.locator(".d-header #site-logo").first();
    await expect(logo).toBeVisible({ timeout: resolveTimeout(READY_MS) });
    const box = await logo.boundingBox();
    expect(box.width, "the header logo is a wide lockup").toBeGreaterThan(box.height * 1.5);
    const src = await logo.evaluate((img) => img.currentSrc);
    expect(src, "the header logo is an upload the role made").toContain("/uploads/");
    expect((await apiGetOnion(page.request, src)).ok(), "Discourse serves the uploaded logo").toBe(true);
    const sizes = await logo.evaluate(async (img, rendered) => {
      const probe = new Image();
      probe.src = rendered;
      await probe.decode();
      return { served: [img.naturalWidth, img.naturalHeight], rendered: [probe.naturalWidth, probe.naturalHeight] };
    }, logoUrl.replace(/\.svg$/, ".png"));
    expect(sizes.served, "the header logo has the size of the rendered corporate lockup").toEqual(sizes.rendered);
    const svg = await (await apiGetOnion(page.request, logoUrl)).text();
    const onFrame = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue("--design-on-frame").trim().toLowerCase(),
    );
    expect(svg.toLowerCase(), "the lockup text on the header takes --design-on-frame").toContain(`fill="${onFrame}"`);
  });

  test("design: the palette lives in Discourse, not in a role stylesheet", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLatest(page);
    await expect(page.locator('link[href*="/roles/web-app-discourse/"][href*="style.css"]')).toHaveCount(0);
    await expect(page.locator('link[href*="/stylesheets/"][data-theme-id]').first()).toBeAttached();
  });

  test("design: gallery of forum, user and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    const base = baseUrl();
    const failures = [];
    await captureDesignGallery(page, [
      { name: "login", url: `${base}/login`, prepare: (v) => ready(v, "#login-account-name") },
      { name: "signup", url: `${base}/signup`, prepare: (v) => ready(v, "body.signup-page input:visible") },
    ]).catch((error) => failures.push(error.message));
    await signIn(page);
    const topicId = await seedShowcase(page);
    const views = signedInViews(base, env("ADMIN_USERNAME"), topicId).map((view) => ({
      name: view.name,
      url: view.url,
      prepare: (v) => prepareView(v, view),
    }));
    await captureDesignGallery(page, views).catch((error) => failures.push(error.message));
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
