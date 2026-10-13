const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
} = require("./design");
const {
  apiFetchOnion,
  apiGetOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
} = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.YOURLS_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");

const MODES = ["light", "dark"];
const ADMIN = `${base}/admin/index.php`;
const TABLE = "#main_table";
const ROW = '#main_table tbody tr[id^="id-"]';
const CELL = `${ROW} td.url`;
const MENU = "ul#admin_menu";
const SIGNED_IN = "#admin_menu_logout_link";
const LOGIN_FIELD = "#login #username";
const SEED = Array.from({ length: 12 }, (_, index) => `design${String(index + 1).padStart(2, "0")}`);
const READY = 10_000;

let seeded = false;

/**
 * Args:
 *   request: APIRequestContext of the test's browser context; creates the showcase links once per worker.
 */
async function seed(request) {
  if (seeded) return;
  for (const keyword of SEED) {
    const response = await apiFetchOnion(request, `${base}/yourls-api.php`, {
      method: "POST",
      form: {
        username: adminUsername,
        password: adminPassword,
        action: "shorturl",
        url: `https://example.org/${keyword}`,
        keyword,
        title: `Design showcase ${keyword}`,
        format: "json",
      },
    });
    const body = await response.json();
    expect(
      body.status === "success" || /already exists/i.test(String(body.message)),
      `seeding ${keyword} through the API as the administrator answers ${response.status()} ${body.message}`,
    ).toBe(true);
  }
  for (const keyword of SEED.slice(0, 3)) {
    const stats = await apiFetchOnion(request, `${base}/yourls-api.php`, {
      method: "POST",
      form: { username: adminUsername, password: adminPassword, action: "url-stats", shorturl: keyword, format: "json" },
    });
    if (Number((await stats.json()).link.clicks) < 2) {
      await apiGetOnion(request, `${base}/${keyword}`, {
        maxRedirects: 0,
        headers: { Referer: "https://news.example.org/design" },
      });
    }
  }
  seeded = true;
}

/**
 * Args:
 *   page: Playwright page; fills the native YOURLS sign-in form when it is shown.
 */
async function nativeForm(page) {
  if ((await page.locator(LOGIN_FIELD).count()) === 0) return;
  const user = page.locator("#username");
  await expect(user).toBeEditable({ timeout: resolveTimeout(READY) });
  await user.fill(adminUsername);
  const password = page.locator("#password");
  await expect(password).toBeEditable({ timeout: resolveTimeout(READY) });
  await password.fill(adminPassword);
  await page.locator("#submit").click();
}

/**
 * Args:
 *   page: Playwright page; signs in as the administrator, through Keycloak when the admin path is gated.
 */
async function signIn(page) {
  await gotoOnion(page, `${base}/admin/`);
  if (oidcIssuerUrl && page.url().startsWith(oidcIssuerUrl)) {
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(`${base}/admin/`);
    await gotoOnion(page, ADMIN);
  } else {
    await nativeForm(page);
  }
  await expect(page.locator(SIGNED_IN)).toBeVisible({ timeout: resolveTimeout(READY) });
}

/**
 * Args:
 *   page: Playwright page.
 *   keyword: short URL keyword whose private stats page is opened with the native sign-in.
 */
async function openStats(page, keyword) {
  await gotoOnion(page, `${base}/${keyword}+`);
  await nativeForm(page);
  await expect(page.locator("#tabs")).toBeVisible({ timeout: resolveTimeout(READY) });
}

async function openIndex(page) {
  await signIn(page);
  await gotoOnion(page, ADMIN);
  await indexReady(page);
}

async function indexReady(page) {
  await expect(page.locator(ROW).first()).toBeVisible({ timeout: resolveTimeout(READY) });
}

async function jqueryIdle(page) {
  await page.waitForFunction(() => window.jQuery && window.jQuery(":animated").length === 0, null, {
    timeout: resolveTimeout(READY),
  });
}

async function hideSignature(page) {
  await page.addStyleTag({ content: "#wrap code, #wrap pre, #wrap tt { visibility: hidden !important; }" });
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await assertDesignTokens(page, "yourls");
  });

  test("design: admin page, panel, links, fields, button and table take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await seed(page.request);
    await openIndex(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `text ${mode}`);
      await assertToken(page, "#wrap", "background-color", "--design-surface-2", `panel ${mode}`);
      await assertToken(page, `${MENU} a`, "color", "--design-link", `menu link ${mode}`);
      await assertToken(page, "#add-url", "background-color", "--design-surface-2", `url field ${mode}`);
      await assertToken(page, "#add-url", "border-top-color", "--design-border-strong", `url field border ${mode}`);
      await assertToken(page, "#add-button", "background-color", "--design-surface-2", `primary action ${mode}`);
      await assertToken(page, "#add-button", "color", "--design-text", `primary action text ${mode}`);
      await assertToken(page, "#add-button", "border-top-color", "--design-border-strong", `primary action border ${mode}`);
      await assertToken(page, `${TABLE}.tblSorter`, "background-color", "--design-border", `table divider ${mode}`);
      await assertToken(page, `${TABLE} thead th`, "background-color", "--design-surface-3", `table head ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#wrap", "yourls admin panel");
    await assertReadable(
      page,
      [`${MENU} li`, `${MENU} a`, "#new_url label", "#add-button", `${TABLE} thead th`, CELL, `${ROW} td.clicks`, "#footer p"],
      "yourls admin index",
    );
    await page.locator(ROW).first().hover();
    await assertToken(page, `${ROW} >> nth=0 >> td.url`, "background-color", "--design-surface-hover", "hovered row");
    await assertReadable(page, [CELL], "yourls hovered row");
  });

  test("design: dialog and notify bar stay readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await seed(page.request);
    await openIndex(page);
    await page.locator("#add-url").fill(`https://example.org/${SEED[0]}`);
    await page.locator("#add-keyword").fill(SEED[0]);
    await page.locator("#add-button").click();
    const bar = page.locator(".jquery-notify-bar");
    await expect(bar).toBeVisible({ timeout: resolveTimeout(READY) });
    await jqueryIdle(page);
    await assertReadable(page, [".jquery-notify-bar"], "yourls notify bar");
    await gotoOnion(page, ADMIN);
    await indexReady(page);
    await page.locator(ROW).first().hover();
    await page.locator(`${ROW} td.actions .button_delete`).first().click();
    await expect(page.locator("#delete-confirm-dialog")).toHaveAttribute("open", "", { timeout: resolveTimeout(READY) });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#delete-confirm-dialog", "background-color", "--design-surface-2", `dialog ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(
      page,
      ['#delete-confirm-dialog > div[name="dialog_title"]', "#delete-confirm-dialog div.confirm-message"],
      "yourls dialog",
    );
  });

  test("design: the administrator signs in natively on the private stats page and its tabs take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await seed(page.request);
    await openStats(page, SEED[0]);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "#tabs ul#headers li a.selected", "background-color", "--design-surface-2", `selected tab ${mode}`);
      await assertToken(page, "#tabs ul#headers li a:not(.selected)", "background-color", "--design-surface-3", `tab ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(
      page,
      ["#tabs ul#headers li a", "#stat_tab_stats h3", "#historical_clicks li:nth-child(2)"],
      "yourls stats tabs and the zebra row the app paints inline",
    );
  });

  test("design: every image the role stylesheet references is served", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    const sheet = await page.locator("link[href*='/roles/web-app-yourls/'][href*='style.css']").first().getAttribute("href");
    const css = await (await apiGetOnion(page.request, sheet)).text();
    const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
      .filter((target) => !target.startsWith("data:"))
      .map((target) => new URL(target, sheet).href);
    expect(targets.length, "the role stylesheet references images").toBeGreaterThan(0);
    for (const target of targets) {
      const served = await apiGetOnion(page.request, target);
      expect(
        `${served.status()} ${served.headers()["content-type"]}`,
        `${target} must be served as an image; a relative url() resolves against the stylesheet on the CDN`,
      ).toMatch(/^200 image\//);
    }
  });

  test("design: logo, favicon and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!faviconUrl && !title && !logoUrl, "logo and title replacement are disabled for this role");
    await signIn(page);
    if (title) {
      await expect.poll(() => page.title(), { message: "the admin page carries the configured title" }).toContain(title);
    }
    if (faviconUrl) {
      await expect(page.locator("link[rel~='icon']"), "the get_favicon_url filter serves the configured favicon").toHaveAttribute(
        "href",
        faviconUrl,
      );
    }
    if (logoUrl) {
      const logo = page.locator("#yourls-logo");
      await expect(logo).toHaveCSS("content", `url("${logoUrl}")`);
      const box = await logo.boundingBox();
      expect(box.width, "the logo box is a wide lockup").toBeGreaterThan(box.height);
    }
  });

  function galleryViews() {
    const signedIn = (name, url, prepare) => ({
      name,
      url,
      prepare: async (page) => {
        if ((await page.locator(LOGIN_FIELD).count()) > 0) {
          await signIn(page);
          await gotoOnion(page, url);
        }
        if (prepare) await prepare(page);
      },
    });
    const index = (name, then) =>
      signedIn(name, ADMIN, async (page) => {
        await indexReady(page);
        if (then) await then(page);
      });
    const stats = (name, tab) => ({
      name,
      url: `${base}/${SEED[0]}+`,
      prepare: async (page) => {
        await nativeForm(page);
        await expect(page.locator("#tabs")).toBeVisible({ timeout: resolveTimeout(READY) });
        if (tab) {
          await page.locator(`#tabs ul#headers a[href="#${tab}"]`).click();
          await expect(page.locator(`#${tab}`)).toBeVisible({ timeout: resolveTimeout(READY) });
        }
      },
    });
    return [
      index("admin-index"),
      index("admin-row-hover", (page) => page.locator(ROW).first().hover()),
      index("admin-add-focus", async (page) => {
        await page.keyboard.press("Tab");
        await page.locator("#add-url").focus();
      }),
      index("admin-add-duplicate", async (page) => {
        await page.locator("#add-url").fill(`https://example.org/${SEED[0]}`);
        await page.locator("#add-keyword").fill(SEED[0]);
        await page.locator("#add-button").click();
        await expect(page.locator(".jquery-notify-bar")).toBeVisible({ timeout: resolveTimeout(READY) });
        await jqueryIdle(page);
      }),
      index("admin-share", async (page) => {
        await page.locator(ROW).first().hover();
        await page.locator(`${ROW} td.actions .button_share`).first().click();
        await expect(page.locator("#shareboxes")).toBeVisible({ timeout: resolveTimeout(READY) });
        await jqueryIdle(page);
      }),
      index("admin-edit-row", async (page) => {
        await page.locator(ROW).first().hover();
        await page.locator(`${ROW} td.actions .button_edit`).first().click();
        await expect(page.locator("tr.edit-row")).toBeVisible({ timeout: resolveTimeout(READY) });
        await jqueryIdle(page);
      }),
      index("admin-delete-dialog", async (page) => {
        await page.locator(ROW).first().hover();
        await page.locator(`${ROW} td.actions .button_delete`).first().click();
        await expect(page.locator("#delete-confirm-dialog")).toHaveAttribute("open", "", { timeout: resolveTimeout(READY) });
      }),
      signedIn("admin-search", `${ADMIN}?search=design0&search_in=keyword`, indexReady),
      signedIn("admin-no-results", `${ADMIN}?search=zz-no-match&search_in=all`, async (page) => {
        await expect(page.locator("#nourl_found")).toBeVisible({ timeout: resolveTimeout(READY) });
      }),
      index("admin-sorted", async (page) => {
        await page.locator("th#main_table_head_clicks").click();
        await expect(page.locator("th#main_table_head_clicks")).toHaveClass(/tablesorter-header(Asc|Desc)/, {
          timeout: resolveTimeout(READY),
        });
      }),
      signedIn("admin-pagination", `${ADMIN}?perpage=5`, async (page) => {
        await expect(page.locator("#pagination .navigation")).toBeVisible({ timeout: resolveTimeout(READY) });
      }),
      index("admin-date-picker", async (page) => {
        await page.locator("#date_first").click();
        await expect(page.locator(".datepicker")).toBeVisible({ timeout: resolveTimeout(READY) });
        await jqueryIdle(page);
      }),
      index("admin-menu-hover", (page) => page.locator("#admin_menu_tools_link a").hover()),
      signedIn("tools", `${base}/admin/tools.php`, async (page) => {
        await hideSignature(page);
        await expect(page.locator("a.bookmarklet").first()).toBeVisible({ timeout: resolveTimeout(READY) });
      }),
      signedIn("tools-bookmarklet-hover", `${base}/admin/tools.php`, async (page) => {
        await hideSignature(page);
        await page.locator("a.bookmarklet").first().hover();
      }),
      signedIn("plugins", `${base}/admin/plugins.php`, async (page) => {
        await expect(page.locator("tr.plugin").first()).toBeVisible({ timeout: resolveTimeout(READY) });
      }),
      signedIn("plugins-row-hover", `${base}/admin/plugins.php`, (page) => page.locator("tr.plugin").first().hover()),
      stats("stats"),
      stats("stats-location", "stat_tab_location"),
      stats("stats-sources", "stat_tab_sources"),
      stats("stats-share", "stat_tab_share"),
    ];
  }

  function visitorViews() {
    if (isServiceEnabled("sso")) return [];
    const login = async (page) => {
      await expect(page.locator(LOGIN_FIELD)).toBeVisible({ timeout: resolveTimeout(READY) });
    };
    return [
      { name: "login", url: `${base}/admin/`, prepare: login },
      {
        name: "login-error",
        url: `${base}/admin/`,
        prepare: async (page) => {
          await login(page);
          await expect(page.locator("#username")).toBeEditable({ timeout: resolveTimeout(READY) });
          await page.locator("#username").fill(adminUsername);
          await expect(page.locator("#password")).toBeEditable({ timeout: resolveTimeout(READY) });
          await page.locator("#password").fill(`wrong-${Date.now()}-${Math.random().toString(36).slice(2)}`);
          await page.locator("#submit").click();
          await expect(page.locator("#error-message")).toBeVisible({ timeout: resolveTimeout(READY) });
        },
      },
    ];
  }

  test("design: gallery of sign-in, admin, tools, plugins and stats", async ({ browser, page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_800_000));
    await seed(page.request);
    const failures = [];
    const visitor = await browser.newPage({ ignoreHTTPSErrors: true });
    try {
      await captureDesignGallery(visitor, visitorViews());
    } catch (error) {
      failures.push(error.message);
    }
    await visitor.close();
    await signIn(page);
    try {
      await captureDesignGallery(page, galleryViews());
    } catch (error) {
      failures.push(error.message);
    }
    expect(failures, "design gallery views failed").toEqual([]);
  });
};
