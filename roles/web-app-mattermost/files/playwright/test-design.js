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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const frameLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_FRAME_URL || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const TEAM = "main";
const SHOWCASE = "design-showcase";
const WIDE = 769;
const ONYX_SURFACE = "rgb(25, 27, 31)";
const LOGIN_ID = "#input_loginId";
const PASSWORD = "#input_password-input";
const SUBMIT = "#saveSetting";
const SIGN_IN_LOGO = ".hfroute-header .header-logo-link > svg";
const EDITOR = "#post-create";
const POSTS = "#post-list";
const POST = `${POSTS} .post:not(.post--system)`;
const CONTENT = "#app-content";
const HEADER = "#global-header";
const HEADER_LOGO = `${HEADER} [aria-controls='product-switcher-menu'] > span > svg`;
const SIDEBAR = "#SidebarContainer";
const SETTINGS = "#accountSettingsModal";
const THEMES = "#premadeThemesSection";
const BACKSTAGE = ".backstage-body";
const HEADER_FOOTER = ".signup-team__container";
const CONSOLE = "#adminConsoleWrapper";
const CONSOLE_NAV = ".admin-sidebar";
const CONSOLE_SECTION = `${CONSOLE_NAV} .sidebar-section-title`;
const USER_CARD = ".AdminUserCard__header";
const PERMISSION_ROW = ".permissions-tree .permission-group-row";
const SIGN_IN_BACKDROP = ".header-footer-route-container";
const TRANSPARENT = "rgba(0, 0, 0, 0)";
const LOADING_SCREEN = "#initialPageLoadingScreen";
const FIRST_RUN = [
  ["onboarding_task_list", "onboarding_task_list_show", "false"],
  ["onboarding_task_list", "onboarding_task_list_open", "false"],
];

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(page.locator(LOADING_SCREEN)).toBeHidden({ timeout: resolveTimeout(30_000) });
  };
}

function loaded(selector) {
  return async (page) => {
    await shown(selector)(page);
    await page.waitForLoadState("networkidle", { timeout: resolveTimeout(5_000) }).catch(() => {});
  };
}

/**
 * Args:
 *   page: Playwright page.
 *   selector: panel that opens with an animation; returns once it is visible, runs no finite animation and is opaque.
 */
async function settled(page, selector) {
  const panel = page.locator(selector).first();
  await expect(panel).toBeVisible({ timeout: resolveTimeout(15_000) });
  await expect
    .poll(
      () =>
        panel.evaluate(
          (element) =>
            element
              .getAnimations({ subtree: true })
              .filter((animation) => animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity).length,
        ),
      { message: `${selector} must have finished its opening animation`, timeout: resolveTimeout(10_000) },
    )
    .toBe(0);
  await expect(panel).toHaveCSS("opacity", "1");
}

function hex(color) {
  const channels = color.match(/\d+/g).slice(0, 3);
  return `#${channels.map((value) => Number(value).toString(16).padStart(2, "0")).join("")}`;
}

exports.register = function (shared) {
  const base = shared.expectedMattermostBaseUrl();

  async function seenLanding(page) {
    await page.addInitScript(() => {
      try {
        localStorage.setItem("__landingPageSeen__", "true");
      } catch {}
    });
  }

  async function openSignIn(page) {
    await seenLanding(page);
    await gotoOnion(page, `${base}/login`);
    await shown(LOGIN_ID)(page);
  }

  /**
   * Args:
   *   page: signed-in Playwright page; the request carries its session cookie and the CSRF token the app expects.
   *   method: HTTP verb.
   *   path: path below `/api/v4`.
   *   payload: JSON body, omitted for a request without one.
   *
   * Returns:
   *   The HTTP status and the parsed answer.
   */
  async function api(page, method, path, payload) {
    return page.evaluate(
      async ([verb, url, body]) => {
        const csrf = (document.cookie.match(/(?:^|; )MMCSRF=([^;]+)/) || [])[1] || "";
        const response = await fetch(url, {
          method: verb,
          headers: { "content-type": "application/json", "x-csrf-token": csrf, "x-requested-with": "XMLHttpRequest" },
          body: body === null ? undefined : JSON.stringify(body),
        });
        return { status: response.status, data: await response.json().catch(() => null) };
      },
      [method, `/api/v4${path}`, payload === undefined ? null : payload],
    );
  }

  /**
   * Args:
   *   page: Playwright page that ends signed in as the administrator on the default channel, through Keycloak when `sso` is on and through the app's own form otherwise, with the first-run checklist of that account closed.
   *
   * Returns:
   *   The administrator's user record.
   */
  async function signIn(page) {
    if (shared.oidcEnabled) {
      await shared.startMattermostSsoFlow(page, base);
      await performKeycloakLoginForm(page, shared.env.adminUsername, shared.env.adminPassword);
    } else {
      await openSignIn(page);
      await page.locator(LOGIN_ID).fill(shared.env.adminUsername);
      await page.locator(PASSWORD).fill(shared.env.adminPassword);
      await page.locator(SUBMIT).click();
    }
    await expect(page.locator(EDITOR)).toBeVisible({ timeout: resolveTimeout(60_000) });
    const me = await api(page, "GET", "/users/me");
    expect(me.status, "the signed-in API must answer").toBe(200);
    const saved = await api(
      page,
      "PUT",
      `/users/${me.data.id}/preferences`,
      FIRST_RUN.map(([category, name, value]) => ({ user_id: me.data.id, category, name, value })),
    );
    expect(saved.status, "closing the first-run checklist").toBe(200);
    return me.data;
  }

  /**
   * Args:
   *   page: signed-in Playwright page; a public channel with one rich post and one reply gets created when it is missing.
   *
   * Returns:
   *   The id of the rich post.
   */
  async function seedShowcase(page) {
    const team = await api(page, "GET", `/teams/name/${TEAM}`);
    expect(team.status, "the default team must exist").toBe(200);
    let channel = await api(page, "GET", `/teams/${team.data.id}/channels/name/${SHOWCASE}`);
    if (channel.status === 404) {
      channel = await api(page, "POST", "/channels", {
        team_id: team.data.id,
        name: SHOWCASE,
        display_name: "Design showcase",
        type: "O",
      });
    }
    expect(channel.status, "the showcase channel").toBeLessThan(300);
    const posts = await api(page, "GET", `/channels/${channel.data.id}/posts?per_page=30`);
    expect(posts.status, "reading the showcase channel").toBe(200);
    const existing = posts.data.order.find((id) => posts.data.posts[id].root_id === "" && posts.data.posts[id].type === "");
    if (existing) return existing;
    const root = await api(page, "POST", "/posts", {
      channel_id: channel.data.id,
      message:
        "## Design showcase\n\n| Token | Use |\n|---|---|\n| surface | page |\n| primary | action |\n\n> A quote\n\n```js\nconst answer = 42;\n```\n\n[A link](https://example.org), `inline code` and a mention of @all.",
    });
    expect(root.status, "seeding the showcase post").toBeLessThan(300);
    const reply = await api(page, "POST", "/posts", {
      channel_id: channel.data.id,
      root_id: root.data.id,
      message: "A reply for the thread view.",
    });
    expect(reply.status, "seeding the showcase reply").toBeLessThan(300);
    return root.data.id;
  }

  /**
   * Args:
   *   page: signed-in Playwright page on the app's origin; its session is dropped without leaving the "session expired" notice for the next sign-in page.
   *
   * Returns:
   *   The cookies of the dropped session.
   */
  async function signOutQuietly(page) {
    const session = await page.context().cookies();
    await page.context().clearCookies();
    await page.evaluate(() => {
      for (const key of Object.keys(localStorage)) {
        if (key.includes("was_logged_in")) localStorage.setItem(key, "false");
      }
    });
    return session;
  }

  async function openShowcase(page) {
    await gotoOnion(page, `${base}/${TEAM}/channels/${SHOWCASE}`);
    await loaded(`${POSTS} table`)(page);
  }

  async function openSettings(page) {
    await loaded(EDITOR)(page);
    await page.keyboard.press("Control+Shift+A");
    await settled(page, SETTINGS);
  }

  async function openThemes(page) {
    await openSettings(page);
    await page.locator("#displayButton").click();
    await page.locator("#themeEdit").click();
    await shown(THEMES)(page);
  }

  function publicViews() {
    return [
      { name: "sign-in", url: `${base}/login`, prepare: shown(LOGIN_ID) },
      {
        name: "sign-in-error",
        url: `${base}/login`,
        prepare: async (page) => {
          await shown(LOGIN_ID)(page);
          await page.locator(LOGIN_ID).fill(SHOWCASE);
          await page.locator(PASSWORD).fill("wrong-on-purpose");
          await page.locator(SUBMIT).click();
          await shown(".login-body-card .AlertBanner")(page);
        },
      },
      { name: "password-reset", url: `${base}/reset_password`, prepare: shown(HEADER_FOOTER) },
      { name: "landing", url: `${base}/landing#/login`, prepare: shown(".get-app__dialog") },
    ];
  }

  function signedInViews(user, postId) {
    const view = (name, path, prepare) => ({ name, url: `${base}${path}`, prepare });
    const showcase = `/${TEAM}/channels/${SHOWCASE}`;
    return [
      view("channel", `/${TEAM}/channels/town-square`, loaded(EDITOR)),
      view("channel-rich-post", showcase, loaded(`${POSTS} table`)),
      view("channel-post-hover", showcase, async (page) => {
        await loaded(`${POSTS} table`)(page);
        await page.locator(POST).first().hover();
      }),
      view("thread", `/${TEAM}/threads/${postId}`, loaded(".ThreadPane")),
      view("navigation", showcase, async (page) => {
        await loaded(EDITOR)(page);
        if (page.viewportSize().width < WIDE) {
          await page.locator("#navbar .navbar-toggle").first().click();
          await settled(page, SIDEBAR);
        } else {
          await page.locator("#product_switch_menu").click();
          await settled(page, "#product-switcher-menu-dropdown");
        }
      }),
      view("settings-notifications", showcase, openSettings),
      view("settings-theme", showcase, openThemes),
      view("emoji-picker", showcase, async (page) => {
        await loaded(EDITOR)(page);
        await page.locator("#emojiPickerButton").click();
        await settled(page, "#emojiGifPicker");
      }),
      view("integrations", `/${TEAM}/integrations`, loaded(BACKSTAGE)),
      view("incoming-webhook-add", `/${TEAM}/integrations/incoming_webhooks/add`, loaded(`${BACKSTAGE} .backstage-form`)),
      view("custom-emoji", `/${TEAM}/emoji`, loaded(BACKSTAGE)),
      view("select-team", "/select_team", loaded(HEADER_FOOTER)),
      view("create-team", "/create_team", loaded(HEADER_FOOTER)),
      view("console-users", "/admin_console/user_management/users", loaded(`${CONSOLE} table tbody tr`)),
      view("console-user", `/admin_console/user_management/user/${user.id}`, loaded(`${CONSOLE} .admin-console__wrapper`)),
      view("console-teams", "/admin_console/user_management/teams", loaded(`${CONSOLE} .DataGrid`)),
      view("console-permissions", "/admin_console/user_management/permissions/system_scheme", loaded(`${CONSOLE} .admin-console__wrapper`)),
      view("console-customization", "/admin_console/site_config/customization", loaded(`${CONSOLE} .admin-console__wrapper`)),
      view("console-statistics", "/admin_console/reporting/system_analytics", loaded(`${CONSOLE} .admin-console__wrapper`)),
      view("console-plugins", "/admin_console/plugins/plugin_management", loaded(`${CONSOLE} .admin-console__wrapper`)),
    ];
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openSignIn(page);
    await assertDesignTokens(page, "Mattermost");
  });

  test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openSignIn(page);
      await assertToken(page, ".login-body-card", "background-color", "--design-surface-1", `sign-in card ${mode}`);
      await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
      await assertToken(page, ".login-body-message-title", "color", "--design-text", `sign-in ${mode}`);
      await expect(page.locator(SIGN_IN_BACKDROP), `sign-in backdrop ${mode}`).toHaveCSS("background-image", "none");
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".login-body-card", "Mattermost sign-in");
    await assertReadable(page, [".login-body-message-title", ".login-body-card-title", SUBMIT, LOGIN_ID], "Mattermost sign-in");
  });

  test("design: the signed-in interface takes surfaces, frame, primary action and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await seedShowcase(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await openShowcase(page);
      await assertToken(page, CONTENT, "background-color", "--design-surface-1", `content ${mode}`);
      await assertToken(page, `${POST} .post-message__text`, "color", "--design-text", `post ${mode}`);
      await assertToken(page, `${POST} .post-message__text a`, "color", "--design-link", `post link ${mode}`);
      await assertToken(page, "body", "background-color", "--design-frame", `frame ${mode}`);
      await assertToken(page, ".main-wrapper", "background-color", "--design-frame", `sidebar ${mode}`);
      await assertToken(page, ".main-wrapper", "border-left-color", "--design-frame-active", `frame outline ${mode}`);
      await assertToken(page, ".sidebarHeaderContainer", "color", "--design-on-frame", `sidebar header ${mode}`);
      await assertToken(page, "#introTextInvite", "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, "#introTextInvite", "color", "--design-on-primary", `primary action ${mode}`);
      await assertToken(page, "#channel-header", "border-bottom-color", "--design-border", `channel header divider ${mode}`);
      await assertToken(page, `${POSTS} table td`, "border-bottom-color", "--design-border", `table divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, CONTENT, "Mattermost content");
    await assertReadable(
      page,
      [`${POST} .post-message__text`, `${POST} .post-message__text a`, ".mention--highlight", `${POSTS} .post-code code`, `${SIDEBAR} .SidebarChannel:not(.active) .SidebarLink`, `${SIDEBAR} .SidebarChannel.active .SidebarLink`, ".channel-header__title"],
      "Mattermost shell",
    );
  });

  test("design: focus stops inside the frame draw their indicator in the on-frame tone", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await gotoOnion(page, `${base}/${TEAM}/channels/town-square`);
    await loaded(EDITOR)(page);
    const onFrame = await tokenValue(page, "--design-on-frame", "color");
    const seen = [];
    await page.locator(`${HEADER} #product_switch_menu`).focus();
    for (let step = 0; step < 24; step += 1) {
      await page.keyboard.press("Tab");
      const stop = await page.evaluate(
        ([header, sidebar]) => {
          const element = document.activeElement;
          if (!element || !element.closest(`${header}, ${sidebar}`) || element.closest("[role='menu'], input")) return null;
          const style = getComputedStyle(element);
          return { name: `${element.tagName.toLowerCase()}#${element.id}`, indicator: [style.outlineColor, style.boxShadow, style.borderTopColor].join(" ") };
        },
        [HEADER, SIDEBAR],
      );
      if (stop) seen.push(stop);
    }
    expect(seen.length, "the Tab walk must reach focus stops inside the frame").toBeGreaterThan(3);
    for (const stop of seen) {
      expect(stop.indicator, `focus indicator of ${stop.name} inside the frame`).toContain(onFrame);
    }
  });

  test("design: the System Console takes surface, frame and text from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const user = await signIn(page);
    await gotoOnion(page, `${base}/admin_console/user_management/permissions/system_scheme`);
    await loaded(PERMISSION_ROW)(page);
    await expect(page.locator(PERMISSION_ROW).first(), "a permission row keeps its transparent border").toHaveCSS("border-top-color", TRANSPARENT);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, `${base}/admin_console/user_management/user/${user.id}`);
      await loaded(USER_CARD)(page);
      await assertToken(page, USER_CARD, "background-color", "--design-frame", `user card ${mode}`);
      await assertToken(page, ".AdminUserCard__user-id", "color", "--design-on-frame", `user card text ${mode}`);
      await gotoOnion(page, `${base}/admin_console/user_management/users`);
      await loaded(`${CONSOLE} table tbody tr`)(page);
      await assertToken(page, CONSOLE_NAV, "background-color", "--design-frame", `console navigation ${mode}`);
      await assertToken(page, ".admin-console__header", "color", "--design-text", `console header ${mode}`);
      await assertToken(page, `${CONSOLE} table tbody td`, "border-bottom-color", "--design-border", `console table divider ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".admin-console__header", "Mattermost System Console");
    await assertReadable(
      page,
      [".admin-console__header", `${CONSOLE} table tbody td`, `${CONSOLE} table thead th`, CONSOLE_SECTION, `${CONSOLE_NAV} a[href$='/user_management/users']`, `${CONSOLE_NAV} a[href$='/user_management/teams']`],
      "System Console",
    );
  });

  test("design: a theme picked in the settings is respected and mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await signIn(page);
    await openShowcase(page);
    const html = page.locator("html");
    await expect(html, "the default theme hands the mode to the browser preference").not.toHaveAttribute("data-design-theme");
    await expect(html).toHaveAttribute("data-design-app-theme", "default");
    await assertToken(page, CONTENT, "background-color", "--design-surface-1", "default theme");
    await openThemes(page);
    await page.locator("#premadeThemeOnyx").click();
    await expect(html, "a dark theme picked in Mattermost must switch the tokens").toHaveAttribute("data-design-theme", "dark");
    await expect(html).toHaveAttribute("data-design-app-theme", "custom");
    await expect(page.locator(CONTENT), "a picked theme keeps its own surface").toHaveCSS("background-color", ONYX_SURFACE);
    await page.locator("#premadeThemeDenim").click();
    await expect(html, "the default theme hands the mode back to the browser").not.toHaveAttribute("data-design-theme");
    await assertToken(page, CONTENT, "background-color", "--design-surface-1", "default theme again");
  });

  test("design: sign-in page and global header show the generated logo and the configured site name", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await openSignIn(page);
    if (logoUrl) {
      await expect(page.locator(SIGN_IN_LOGO)).toHaveCSS("background-image", `url("${logoUrl}")`);
      const box = await page.locator(SIGN_IN_LOGO).boundingBox();
      expect(box.width, "the sign-in logo box must be wider than high").toBeGreaterThan(box.height * 1.5);
    }
    const user = await signIn(page);
    expect(user.roles, "the administrator must be signed in").toContain("system_admin");
    if (title) {
      const client = await page.evaluate(async () => (await (await fetch("/api/v4/config/client?format=old")).json()).SiteName);
      expect(client, "the site name the app hands to its client").toBe(title);
      const environment = await api(page, "GET", "/config/environment");
      expect(environment.status, "reading the environment overrides").toBe(200);
      expect(environment.data.TeamSettings.SiteName, "the site name must come from the role, not from the stored configuration").toBe(true);
      await expect.poll(() => page.title(), { timeout: resolveTimeout(15_000) }).toContain(title);
    }
    if (logoUrl && page.viewportSize().width >= WIDE) {
      expect(
        frameLogoUrl,
        "DESIGN_LOGO_FRAME_URL must accompany DESIGN_LOGO_URL; empty would assert the header against url(\"\")",
      ).toBeTruthy();
      await expect(page.locator(HEADER_LOGO)).toHaveCSS("background-image", `url("${frameLogoUrl}")`);
      const box = await page.locator(HEADER_LOGO).boundingBox();
      expect(box.width, "the header logo box must be wider than high").toBeGreaterThan(box.height * 1.5);
      const onFrame = hex(await tokenValue(page, "--design-on-frame", "color"));
      const served = await apiGetOnion(page.request, frameLogoUrl);
      expect(served.status(), "the frame logo must be served").toBe(200);
      const svg = (await served.text()).toLowerCase();
      if (svg.includes("<text")) expect(svg, "the lockup text on the frame").toContain(`fill="${onFrame}"`);
    }
  });

  test("design: gallery of sign-in, channels, settings, integrations and System Console", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    const user = await signIn(page);
    const postId = await seedShowcase(page);
    const session = await signOutQuietly(page);
    const failures = [];
    await captureDesignGallery(page, publicViews()).catch((error) => failures.push(error.message));
    await page.context().addCookies(session);
    await captureDesignGallery(page, signedInViews(user, postId)).catch((error) => failures.push(error.message));
    expect(failures, "every gallery view must be captured").toEqual([]);
  });
};
