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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLogin } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { isSplitRealmOidc, resolveTimeout } = require("./timeouts");

const READY_MS = 10_000;
const MODES = ["light", "dark"];
const LIST_CELL = "table.listingTable > tbody > tr td";

function env(name) {
  return decodeDotenvQuotedValue(process.env[name] || "");
}

function base() {
  return normalizeBaseUrl(process.env.FUSIONDIRECTORY_BASE_URL || "").replace(/\/$/, "");
}

async function ready(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
}

async function restMouse(page) {
  await page.mouse.move(1, page.viewportSize().height - 1);
}

async function openLogin(page) {
  test.skip(isServiceEnabled("sso") && isSplitRealmOidc(), "split-realm OIDC");
  await gotoOnion(page, `${base()}/index.php`);
  if (isServiceEnabled("sso") && (await page.locator("#kc-form-login").isVisible())) {
    await performKeycloakLogin(page, env("ADMIN_USERNAME"), env("ADMIN_PASSWORD"), env("CANONICAL_DOMAIN"));
    await gotoOnion(page, `${base()}/index.php`);
  }
  await ready(page, "#loginform input#username");
}

async function submitLogin(page, username, password) {
  await openLogin(page);
  const user = page.locator("#loginform input#username");
  const secret = page.locator("#loginform input#password");
  await expect(user).toBeEditable({ timeout: resolveTimeout(READY_MS) });
  await user.fill(username);
  await expect(secret).toBeEditable({ timeout: resolveTimeout(READY_MS) });
  await secret.fill(password);
  await page.locator('#loginform input[name="login"]').click();
  await page.waitForLoadState("domcontentloaded");
}

async function signIn(page) {
  await submitLogin(page, env("ADMIN_USERNAME"), env("ADMIN_PASSWORD"));
  await expect(page, "the administrator must land on the signed-in frame").toHaveURL(/main\.php/, {
    timeout: resolveTimeout(READY_MS),
  });
  await ready(page, "div.plugin-window");
}

async function ensureSignedIn(page) {
  await gotoOnion(page, `${base()}/main.php?reset=1`);
  if (await page.locator("div.plugin-window").first().isVisible()) return;
  await signIn(page);
}

async function pluginUrl(page, label) {
  await gotoOnion(page, `${base()}/main.php?reset=1`);
  await ready(page, "div.plugin-window");
  const href = await page.locator('a[href*="plug="]', { hasText: label }).first().getAttribute("href");
  expect(href, `the menu must carry the entry ${label}`).toBeTruthy();
  return new URL(href, `${base()}/`).href;
}

async function openPlugin(page, label, selector) {
  await ensureSignedIn(page);
  await gotoOnion(page, await pluginUrl(page, label));
  await ready(page, selector);
}

async function assertBoth(page, checks) {
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    for (const [selector, property, token] of checks) {
      await assertToken(page, selector, property, token, `fusiondirectory ${mode}`);
    }
  }
  await page.emulateMedia({ colorScheme: null });
}

async function openActionsMenu(page) {
  await page.locator("#pulldown ul.level1 > li > a").first().hover();
  const menu = page.locator("#pulldown ul.level2").first();
  await expect(menu).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  return menu;
}

function galleryViews() {
  const b = base();
  const plugin = (name, label, selector, extra) => ({
    name,
    url: `${b}/main.php?reset=1`,
    prepare: async (p) => {
      await openPlugin(p, label, selector);
      if (extra) await extra(p);
      await restMouse(p);
    },
  });
  const openRow = (text) => async (p) => {
    await p.locator(`${LIST_CELL} > a`, { hasText: text }).first().click();
    await ready(p, "table.tabs-header");
  };
  const create = (entry, field) => async (p) => {
    await openActionsMenu(p);
    await p.locator("li#actionmenu_new > a").hover();
    const item = p.locator(`li#actionmenu_new li${entry} > a`).first();
    await expect(item).toBeVisible({ timeout: resolveTimeout(READY_MS) });
    await item.click({ timeout: resolveTimeout(READY_MS) });
    await ready(p, field);
  };
  return [
    {
      name: "login",
      url: `${b}/index.php`,
      prepare: async (p) => {
        await p.context().clearCookies();
        await openLogin(p);
      },
    },
    {
      name: "login-error",
      url: `${b}/index.php`,
      prepare: async (p) => {
        await p.context().clearCookies();
        await submitLogin(p, `nobody${Date.now()}`, `wrong-${Date.now()}-${Math.random().toString(36).slice(2)}`);
        await ready(p, "div#window-footer");
      },
    },
    {
      name: "recovery",
      url: `${b}/recovery.php`,
      prepare: async (p) => {
        await p.context().clearCookies();
        await gotoOnion(p, `${b}/recovery.php`);
        await ready(p, "body > *");
      },
    },
    {
      name: "main",
      url: `${b}/main.php?reset=1`,
      prepare: async (p) => {
        await ensureSignedIn(p);
        await restMouse(p);
      },
    },
    plugin("users-list", /^Users$/, LIST_CELL),
    plugin("users-row-hover", /^Users$/, LIST_CELL, async (p) => {
      await p.locator("table.listingTable > tbody > tr").first().hover();
    }),
    plugin("user-detail", /^Users$/, LIST_CELL, openRow(env("ADMIN_USERNAME"))),
    plugin("user-new", /^Users$/, "table.listingTable", create("#actionmenu_new_USER", 'input[name="givenName"]')),
    plugin("actions-menu-open", /^Users$/, "table.listingTable", async (p) => {
      const menu = await openActionsMenu(p);
      await menu.locator("li#actionmenu_edit > a").hover();
    }),
    plugin("groups-list", /^Groups and roles$/, "table.listingTable"),
    plugin("departments", /^Departments$/, "table.listingTable"),
    plugin("department-new", /^Departments$/, "table.listingTable", create("#actionmenu_new_DEPARTMENT", 'input[name="ou"]')),
    plugin("acl-roles", /^ACL roles$/, LIST_CELL),
    plugin("acl-role-detail", /^ACL roles$/, LIST_CELL, openRow(/^admin$/)),
    plugin("acl-assignments", /^ACL assignments$/, LIST_CELL),
    plugin("acl-assignment-detail", /^ACL assignments$/, LIST_CELL, async (p) => {
      await p.locator(`${LIST_CELL} > a`).first().click();
      await ready(p, "table.tabs-header");
    }),
    plugin("mail-templates", /^Mail Template$/, "table.listingTable"),
    plugin("tasks", /^Tasks$/, "table.listingTable"),
    plugin("tasks-dashboard", /^Tasks Dashboard$/, "div.plugin-window"),
    plugin("plugins", /^Plugins$/, "div.plugin-window"),
    plugin("configuration", /^Configuration$/, "div.plugin-window"),
    plugin("configuration-edit", /^Configuration$/, 'input[type="submit"]', async (p) => {
      await p.locator('input[type="submit"][name="edit"]').click();
      await ready(p, 'input[name="edit_cancel"]');
    }),
    plugin("subscription", /^Subscription$/, "div.plugin-window"),
    plugin("my-account", /^User$/, "div.plugin-window"),
  ];
}

exports.register = function () {
  test("admin-rights: the administrator signs in natively and reaches the user and ACL management", async ({
    page,
  }) => {
    await signIn(page);
    await gotoOnion(page, `${base()}/main.php?reset=1`);
    await ready(page, "div.plugin-window");
    for (const label of [/^Users$/, /^ACL assignments$/, /^ACL roles$/, /^Configuration$/]) {
      await expect(
        page.locator('a[href*="plug="]', { hasText: label }),
        `the administrator must see the ${label} menu entry`,
      ).not.toHaveCount(0);
    }
  });

  test("csp: the inline event handlers of the login and the signed-in frame run", async ({ page }) => {
    const blocked = [];
    page.on("console", (message) => {
      if (message.type() === "error" && message.text().includes("script-src-attr")) blocked.push(message.text());
    });
    await signIn(page);
    await gotoOnion(page, `${base()}/main.php?reset=1`);
    await ready(page, "div.plugin-window");
    expect(blocked, "the CSP must not block FusionDirectory's inline onSubmit, onLoad and onclick handlers").toEqual([]);
  });

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    expect(process.env.DESIGN_SERVICE_ENABLED).toBe("true");
    await openLogin(page);
    await assertDesignTokens(page, "fusiondirectory");
  });

  test("design: the in-house theme.css carries the palette on the login page", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLogin(page);
    const sheet = await apiGetOnion(page.request, `${base()}/themes/breezy/theme.css`);
    expect(await sheet.text(), "the mounted theme.css must carry the token mapping").toContain("var(--design-surface-1)");
    await assertBoth(page, [
      ["body", "background-color", "--design-surface-1"],
      ["body", "color", "--design-text"],
      ["div#window-div", "background-color", "--design-surface-2"],
      ["div#window-titlebar", "border-bottom-color", "--design-border"],
      ['#loginform input[name="login"]', "background-color", "--design-primary"],
      ['#loginform input[name="login"]', "color", "--design-on-primary"],
    ]);
    await assertLightAndDark(page, "div#window-div", "fusiondirectory login box");
    await assertReadable(page, ["div#window-content", "div#window-content a"], "fusiondirectory login");
  });

  test("design: the login box and the header show the corporate logo", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logo = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
    test.skip(!logo, "the logo replacement is disabled");
    await openLogin(page);
    const login = page.locator("div#window-titlebar img#fd-logo");
    expect(await login.evaluate((img) => getComputedStyle(img).content)).toContain(logo);
    const served = await apiGetOnion(page.request, logo);
    expect(`${served.status()} ${served.headers()["content-type"]}`).toMatch(/^200 image\/svg/);
    const loginBox = await login.boundingBox();
    expect(loginBox.width, "the login lockup must be wider than high").toBeGreaterThan(loginBox.height * 2);
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);
    const header = page.locator("div#header-left img#fd-logo");
    expect(await header.evaluate((img) => getComputedStyle(img).content)).toContain(logo);
    const headerBox = await header.boundingBox();
    expect(headerBox.width, "the header lockup must be wider than high").toBeGreaterThan(headerBox.height * 2);
    await expect(page).toHaveTitle(/FusionDirectory/);
  });

  test("design: every image the theme sheet references is served", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLogin(page);
    const sheet = `${base()}/themes/breezy/theme.css`;
    const css = await (await apiGetOnion(page.request, sheet)).text();
    const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
      .filter((target) => !target.startsWith("data:"))
      .map((target) => new URL(target, sheet).href);
    expect(targets.length, "the theme sheet references images").toBeGreaterThan(0);
    for (const target of targets) {
      const served = await apiGetOnion(page.request, target);
      expect(`${served.status()} ${served.headers()["content-type"]}`, `${target} must be served as an image`).toMatch(
        /^200 image\//,
      );
    }
  });

  test("design: the signed-in frame, menu, list and dividers follow the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await openPlugin(page, /^Users$/, LIST_CELL);
    await restMouse(page);
    await assertBoth(page, [
      ["table.framework td#maincell", "background-color", "--design-surface-1"],
      [".plugin-window", "background-color", "--design-surface-2"],
      ["table.listingTable > thead > tr > th", "background-color", "--design-surface-3"],
      ["table.listingTable > thead > tr > th", "border-bottom-color", "--design-border"],
      [LIST_CELL, "border-right-color", "--design-border"],
      ["ul.menu > li", "border-top-color", "--design-border"],
      ["fieldset", "border-top-color", "--design-border"],
      [".menuitem.menucurrent", "background-color", "--design-surface-active"],
      [`${LIST_CELL} > a`, "color", "--design-link"],
    ]);
    expect(
      await page.locator(".menuitem.menucurrent").evaluate((el) => getComputedStyle(el).boxShadow),
      "the selected menu entry carries the primary inline-start bar",
    ).toContain(await tokenValue(page, "--design-primary", "color"));
    await page.emulateMedia({ colorScheme: "dark" });
    await assertToken(
      page,
      `${LIST_CELL} > input[type="image"]`,
      "background-color",
      "--design-text-muted",
      "fusiondirectory dark action icons sit on a light chip",
    );
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".plugin-window", "fusiondirectory list");
    await assertReadable(
      page,
      [LIST_CELL, `${LIST_CELL} > a`, ".menuitem.menucurrent a", "ul.menu > li > a"],
      "fusiondirectory list",
    );
  });

  test("design: hovered rows, open menus and secondary buttons stay readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize({ width: 1440, height: 900 });
    await openPlugin(page, /^Users$/, LIST_CELL);
    await page.locator("table.listingTable > tbody > tr").first().hover();
    await assertBoth(page, [["table.listingTable > tbody > tr", "background-color", "--design-surface-hover"]]);
    await assertReadable(page, [LIST_CELL], "fusiondirectory hovered row");
    const menu = await openActionsMenu(page);
    await assertBoth(page, [["#pulldown ul.level2", "background-color", "--design-surface-2"]]);
    await menu.locator("li#actionmenu_edit > a").hover();
    await assertBoth(page, [["li#actionmenu_edit > a", "background-color", "--design-surface-hover"]]);
    await assertReadable(page, ["li#actionmenu_edit > a"], "fusiondirectory actions menu");
    await gotoOnion(page, await pluginUrl(page, /^Configuration$/));
    await ready(page, 'input[type="submit"]');
    await assertBoth(page, [
      ['.plugbottom input[type="submit"]', "background-color", "--design-surface-3"],
      ['.plugbottom input[type="submit"]', "border-top-color", "--design-border-strong"],
      ['div[style*="rgb(170,170,170)"]', "border-top-color", "--design-border"],
    ]);
    await assertReadable(page, ['.plugbottom input[type="submit"]'], "fusiondirectory secondary button");
  });

  test("design: gallery", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "gallery runs only with INFINITO_PLAYWRIGHT_KEEP=true");
    test.setTimeout(resolveTimeout(900_000));
    await captureDesignGallery(page, galleryViews());
  });
};
