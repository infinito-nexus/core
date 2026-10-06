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
const {
  apiFetchOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const FOCUS_WALK_LIMIT = 60;
const SHELL = ".main-sidebar .sidebar-menu";
const FRAME = ".main-header, .main-sidebar";
const NAVBAR = ".main-header .navbar";
const BRAND = ".main-header .logo";
const BRAND_TITLE = ".main-header .logo .logo-lg";
const SIDEBAR = ".main-sidebar";
const SELECTED_ENTRY = ".sidebar-menu > li.active > a";
const OTHER_ENTRY = ".sidebar-menu > li.menu-analysis > a";
const PANEL = "#add-group";
const PRIMARY_ACTION = "#btnAdd";
const TEXT_FIELD = "#new_name";
const TABLE_CELL = "#groupsTable tbody td";
const PASSWORD = "#current-password";
const SUBMIT = "#loginform button[type='submit']";
const SIGN_IN_BOX = ".login-box";
const MENU = ".main-header .user-menu > .dropdown-menu";
const DIALOG = "#customDisableModal";
const PICKER = ".select2-selection";
const PICKER_SEARCH = ".select2-search--dropdown .select2-search__field";
const FILE_INPUT = "input[type='file']";
const QUIET_SPOT = ".main-footer";
const SHOWCASE = "design-showcase";

const base = normalizeBaseUrl(process.env.PIHOLE_BASE_URL || "");
const issuer = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");

function admin(path) {
  return `${base}/admin/${path}`;
}

async function shellReady(page) {
  await expect(page.locator(SHELL)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function signIn(page) {
  await gotoOnion(page, admin(""));
  if (issuer) {
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: "an anonymous visit must reach the identity provider",
      })
      .toContain("openid-connect/auth");
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect
      .poll(
        () => {
          const url = new URL(page.url());
          return url.host === new URL(base).host && !url.pathname.startsWith("/oauth2/");
        },
        { timeout: resolveTimeout(90_000), message: "the sign-in must return to Pi-hole" },
      )
      .toBe(true);
    await gotoOnion(page, admin(""));
  } else {
    await page.locator(PASSWORD).fill(adminPassword);
    await page.locator(SUBMIT).click({ timeout: resolveTimeout(30_000) });
  }
  await shellReady(page);
}

async function api(page, method, path, data) {
  const csrf = await page.evaluate(() => document.querySelector("meta[name='csrf-token']")?.content || "");
  return apiFetchOnion(page.request, `${base}/api${path}`, {
    method,
    data,
    headers: csrf ? { "X-CSRF-TOKEN": csrf } : {},
    timeout: resolveTimeout(30_000),
  });
}

async function releaseSession(page) {
  if (issuer) return;
  const signedIn = await page.evaluate(() => document.body.classList.contains("logged-in")).catch(() => false);
  if (signedIn) await api(page, "DELETE", "/auth");
}

async function signedIn(page, body) {
  await signIn(page);
  try {
    test.skip(
      (await page.locator("body.default-auto").count()) === 0,
      "an administrator pinned a theme; the palette assertions cover the theme that follows the browser",
    );
    await body();
  } finally {
    await releaseSession(page).catch(() => {});
  }
}

async function open(page, path, ready) {
  await gotoOnion(page, admin(path));
  await shellReady(page);
  await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function inBothModes(page, check) {
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await check(mode);
  }
  await page.emulateMedia({ colorScheme: null });
}

async function settled(page, selector) {
  await expect
    .poll(
      () =>
        page
          .locator(selector)
          .first()
          .evaluate(
            (element) =>
              getComputedStyle(element).opacity === "1" &&
              element
                .getAnimations({ subtree: true })
                .every(
                  (animation) =>
                    animation.playState !== "running" || animation.effect?.getComputedTiming().iterations === Infinity,
                ) &&
              !window.jQuery(element).is(":animated"),
          ),
      { timeout: resolveTimeout(15_000), message: `${selector} must finish opening` },
    )
    .toBe(true);
}

async function loads(page, url) {
  return page.evaluate(
    (src) =>
      new Promise((resolve) => {
        const image = new Image();
        image.onload = () => resolve(image.naturalWidth > 0);
        image.onerror = () => resolve(false);
        image.src = src;
      }),
    url,
  );
}

async function focusStop(page) {
  return page.evaluate((frame) => {
    const element = document.activeElement;
    const style = getComputedStyle(element);
    return {
      name: [element.tagName.toLowerCase(), ...element.classList].join("."),
      framed: Boolean(element.closest(frame)) && !element.closest(".dropdown-menu"),
      color: style.outlineStyle === "none" || parseFloat(style.outlineWidth) === 0 ? "none" : style.outlineColor,
    };
  }, FRAME);
}

async function pinTheme(page, name) {
  await page.unroute("**/admin/groups");
  if (!name) return;
  await page.route("**/admin/groups", async (route) => {
    const response = await route.fetch();
    let replaced = false;
    const body = (await response.text())
      .replace(/<link[^>]+style\/themes\/[^>]+>/g, () => {
        if (replaced) return "";
        replaced = true;
        return `<link rel="stylesheet" href="/admin/style/themes/${name}.css">`;
      })
      .replace('<body class="default-auto ', `<body class="${name} `);
    await route.fulfill({ response, body });
  });
}

async function seedShowcase(page) {
  const seeds = [
    ["/groups", { name: SHOWCASE, comment: "Design showcase" }],
    ["/domains/deny/exact", { domain: `ads.${SHOWCASE}.test`, comment: "Design showcase" }],
    ["/domains/allow/exact", { domain: `ok.${SHOWCASE}.test`, comment: "Design showcase" }],
    ["/clients", { client: "192.168.52.250", comment: "Design showcase" }],
    ["/lists?type=block", { address: `https://${SHOWCASE}.test/hosts.txt`, comment: "Design showcase" }],
  ];
  for (const [path, data] of seeds) {
    const response = await api(page, "POST", path, data);
    expect(response.status(), `POST /api${path} answered ${response.status()}`).toBeLessThan(500);
  }
}

function signInViews() {
  const url = admin("login");
  const shown = async (page) => {
    await expect(page.locator(PASSWORD)).toBeVisible({ timeout: resolveTimeout(60_000) });
  };
  return [
    { name: "sign-in", url, prepare: shown },
    {
      name: "sign-in-focus",
      url,
      prepare: async (page) => {
        await shown(page);
        await page.locator(PASSWORD).fill("design-showcase");
        await page.locator(PASSWORD).focus();
      },
    },
    {
      name: "sign-in-error",
      url,
      prepare: async (page) => {
        await shown(page);
        await page.locator(PASSWORD).fill("not-the-password");
        await page.locator(SUBMIT).click({ timeout: resolveTimeout(30_000) });
        await expect(page.locator("#error-label")).toBeVisible({ timeout: resolveTimeout(30_000) });
      },
    },
  ];
}

function signedInViews() {
  const view = (name, path, ready, extra) => ({
    name,
    url: admin(path),
    prepare: async (page) => {
      await shellReady(page);
      await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
      if (extra) await extra(page);
    },
  });
  const rows = (table) => async (page) => {
    await page
      .locator(`${table} tbody td`)
      .first()
      .waitFor({ timeout: resolveTimeout(10_000) })
      .catch(() => {});
  };
  return [
    view("dashboard", "", "#queryOverTimeChart"),
    view("query-log", "queries", "#all-queries"),
    view("groups", "groups", "#groupsTable", rows("#groupsTable")),
    view("clients", "groups/clients", "#clientsTable", rows("#clientsTable")),
    view("domains", "groups/domains", "#domainsTable", rows("#domainsTable")),
    view("lists", "groups/lists", "#listsTable", rows("#listsTable")),
    view("settings-system", "settings/system", ".content .box"),
    view("settings-dns", "settings/dns", ".content .box-title"),
    view("settings-dhcp", "settings/dhcp", "#DHCPLeasesTable"),
    view("settings-web-interface", "settings/api", "[id='webserver.interface.theme']"),
    view("settings-privacy", "settings/privacy", ".content .box"),
    view("settings-teleporter", "settings/teleporter", "#GETTeleporter"),
    view("settings-dns-records", "settings/dnsrecords", "#hosts-Table"),
    {
      name: "settings-all",
      url: admin("settings/all"),
      prepare: async (page) => {
        await shellReady(page);
        await page.evaluate(() => localStorage.setItem("expert_settings", "true"));
        await gotoOnion(page, admin("settings/all"));
        await expect(page.locator("#advanced-settings-menu")).toBeVisible({ timeout: resolveTimeout(60_000) });
        await page.evaluate(() => localStorage.setItem("expert_settings", "false"));
      },
    },
    view("diagnosis", "messages", "#messages-list", rows("#messagesTable")),
    view("tail-log", "taillog?file=ftl", "#output"),
    view("gravity", "gravity", "#gravityBtn"),
    view("search-lists", "search", ".content .box"),
    view("interfaces", "interfaces", "#tree .list-group-item"),
    view("network", "network", "#network-entries", rows("#network-entries")),
    view("menu", "", "#queryOverTimeChart", async (page) => {
      await page.locator(".main-header .user-menu > a.dropdown-toggle").click();
      await expect(page.locator(MENU)).toBeVisible();
      await settled(page, MENU);
    }),
    view("navigation", "settings/dns", ".content .box-title", async (page) => {
      if (!(await page.locator(SELECTED_ENTRY).isVisible()) || page.viewportSize().width < 768) {
        await page.locator(".sidebar-toggle-svg").click();
        await expect(page.locator("body")).toHaveClass(/sidebar-open/);
      }
      await settled(page, SIDEBAR);
      await page.locator(OTHER_ENTRY).hover();
    }),
    view("disable-dialog", "", "#queryOverTimeChart", async (page) => {
      await page.evaluate((dialog) => window.jQuery(dialog).modal("show"), DIALOG);
      await expect(page.locator(`${DIALOG} .modal-content`)).toBeVisible();
      await settled(page, DIALOG);
    }),
  ];
}

exports.register = function () {
  test("design: the tokens are present and switch between light and dark", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await assertDesignTokens(page, "Pi-hole dashboard");
    });
  });

  test("design: page, panel, text, field and primary action follow the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await open(page, "groups", PRIMARY_ACTION);
      await inBothModes(page, async (mode) => {
        await page.locator(QUIET_SPOT).hover();
        await assertToken(page, ".content-wrapper", "background-color", "--design-surface-1", `page ${mode}`);
        await assertToken(page, "body", "color", "--design-text", `body text ${mode}`);
        await assertToken(page, PANEL, "background-color", "--design-surface-2", `panel ${mode}`);
        await assertToken(page, `${PANEL} .box-title`, "color", "--design-text", `panel title ${mode}`);
        await assertToken(page, TEXT_FIELD, "background-color", "--design-surface-2", `text field ${mode}`);
        await assertToken(page, TEXT_FIELD, "color", "--design-text", `text field ${mode}`);
        await assertToken(page, TEXT_FIELD, "border-top-color", "--design-border-strong", `text field ${mode}`);
        await assertToken(page, PRIMARY_ACTION, "background-color", "--design-primary", `primary action ${mode}`);
        await assertToken(page, PRIMARY_ACTION, "color", "--design-on-primary", `primary action ${mode}`);
        await page.locator(PRIMARY_ACTION).hover();
        await assertToken(
          page,
          PRIMARY_ACTION,
          "background-color",
          "--design-primary-hover",
          `hovered primary action ${mode}`,
        );
      });
    });
  });

  test("design: header and sidebar carry the frame tones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await expect(page.locator("#status i")).toBeVisible({ timeout: resolveTimeout(60_000) });
      await inBothModes(page, async (mode) => {
        await page.locator(QUIET_SPOT).hover();
        await assertToken(page, NAVBAR, "background-color", "--design-frame", `top bar ${mode}`);
        await assertToken(page, BRAND, "background-color", "--design-frame", `brand box ${mode}`);
        await assertToken(page, BRAND, "color", "--design-on-frame", `brand box ${mode}`);
        await assertToken(page, SIDEBAR, "background-color", "--design-frame", `sidebar ${mode}`);
        await assertToken(page, SELECTED_ENTRY, "background-color", "--design-frame-active", `selected entry ${mode}`);
        await assertToken(page, SELECTED_ENTRY, "color", "--design-on-frame", `selected entry ${mode}`);
        await assertToken(page, OTHER_ENTRY, "color", "--design-on-frame", `entry ${mode}`);
        await page.locator(OTHER_ENTRY).hover();
        await assertToken(page, OTHER_ENTRY, "background-color", "--design-frame-hover", `hovered entry ${mode}`);
      });
      await page.locator(QUIET_SPOT).hover();
      await assertReadable(
        page,
        [
          BRAND_TITLE,
          SELECTED_ENTRY,
          OTHER_ENTRY,
          ".sidebar-menu > li.header",
          ".user-panel > .info > p",
          "#status",
          "#status i",
          { selector: `${NAVBAR} .navbar-text code`, optional: true },
        ],
        "Pi-hole frame",
      );
    });
  });

  test("design: surfaces darken in dark mode and the core text stays readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await open(page, "groups", TABLE_CELL);
      await assertLightAndDark(page, PANEL, "Pi-hole panel");
      await assertLightAndDark(page, ".content-wrapper", "Pi-hole page");
      await assertReadable(
        page,
        [
          ".page-header h1",
          `${PANEL} .box-title`,
          `${PANEL} label`,
          PRIMARY_ACTION,
          "#groupsTable th",
          TABLE_CELL,
          ".main-footer",
          ".main-footer a",
        ],
        "Pi-hole groups",
      );
    });
  });

  test("design: status tiles draw fill and text from one status token pair", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await expect(page.locator(".small-box.bg-aqua")).toBeVisible({ timeout: resolveTimeout(60_000) });
      await inBothModes(page, async (mode) => {
        for (const [name, status] of [
          ["aqua", "info"],
          ["red", "danger"],
          ["yellow", "warning"],
          ["green", "success"],
        ]) {
          const tile = `.small-box.bg-${name}`;
          await assertToken(page, tile, "background-color", `--design-${status}`, `${status} tile ${mode}`);
          await assertToken(page, `${tile} p`, "color", `--design-on-${status}`, `${status} tile text ${mode}`);
          await assertToken(
            page,
            `${tile} .small-box-footer`,
            "color",
            `--design-on-${status}`,
            `${status} tile footer ${mode}`,
          );
        }
      });
    });
  });

  test("design: content dividers use the border token", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await open(page, "groups", TABLE_CELL);
      await inBothModes(page, async (mode) => {
        await assertToken(
          page,
          "#groups-list .box-header",
          "border-bottom-color",
          "--design-border",
          `panel header ${mode}`,
        );
        await assertToken(page, TABLE_CELL, "border-top-color", "--design-border", `table row ${mode}`);
        await expect(page.locator(TABLE_CELL).first(), `the table row divider must be drawn ${mode}`).toHaveCSS(
          "border-top-width",
          "1px",
        );
      });
    });
  });

  test("design: text on primary-filled controls follows on-primary", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await open(page, "groups", TABLE_CELL);
      for (const selector of [PRIMARY_ACTION, "#num_groups", "#groupsTable_paginate .pagination > .active > a"]) {
        await assertToken(page, selector, "background-color", "--design-primary", selector);
        await assertToken(page, selector, "color", "--design-on-primary", selector);
      }
    });
  });

  test("design: the open client picker and the file button follow the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(Boolean(issuer), "behind the identity provider the role script sends both pages to the dashboard");
    await signedIn(page, async () => {
      await open(page, "groups/clients", "#clientsTable");
      await page.locator(PICKER).first().click();
      await expect(page.locator(PICKER_SEARCH).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
      await inBothModes(page, async (mode) => {
        await assertToken(page, PICKER_SEARCH, "border-top-color", "--design-link", `picker search field ${mode}`);
      });
      await open(page, "settings/teleporter", "#GETTeleporter");
      await inBothModes(page, async (mode) => {
        const fill = await page
          .locator(FILE_INPUT)
          .first()
          .evaluate((element) => getComputedStyle(element, "::file-selector-button").backgroundColor);
        expect(fill, `file button ${mode}`).toBe(await tokenValue(page, "--design-surface-3", "background-color"));
      });
    });
  });

  test("design: every focus stop inside the frame draws its indicator in on-frame", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await inBothModes(page, async (mode) => {
        await gotoOnion(page, admin(""));
        await shellReady(page);
        const ring = await tokenValue(page, "--design-on-frame", "color");
        const stops = [];
        for (let step = 0; step < FOCUS_WALK_LIMIT; step += 1) {
          await page.keyboard.press("Tab");
          const stop = await focusStop(page);
          if (!stop.framed && stops.length > 0) break;
          if (stop.framed) {
            stops.push(stop.name);
            expect(stop.color, `keyboard stop ${stop.name} ${mode}: the focus indicator must be on-frame`).toBe(ring);
          }
        }
        expect(stops.length, `the keyboard walk must find stops inside the frame ${mode}`).toBeGreaterThan(8);
      });
    });
  });

  test("design: the interface shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await signedIn(page, async () => {
      if (title) {
        await expect(page).toHaveTitle(title);
        await expect(page.locator(BRAND_TITLE)).toHaveText(title);
        const box = await page.locator(BRAND).boundingBox();
        expect(box.width, "the brand box holds the title, so it must be wider than high").toBeGreaterThan(
          box.height * 1.5,
        );
      }
      if (logoUrl) {
        const logo = page.locator(`${SIDEBAR} .user-panel img.logo-img`);
        await expect(logo).toHaveCSS("content", `url("${logoUrl}")`);
        const box = await logo.boundingBox();
        expect(Math.abs(box.width - box.height), "the sidebar gives its logo a square box").toBeLessThanOrEqual(1);
        await assertToken(page, SIDEBAR, "background-color", "--design-frame", "the logo sits on the frame");
        await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
        for (const url of [logoUrl, faviconUrl]) {
          expect(await loads(page, url), `the page must be allowed to load ${url}`).toBe(true);
        }
      }
    });
  });

  test("design: the sign-in page carries the palette, the logo and the title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(Boolean(issuer), "behind the identity provider Pi-hole runs without a password and shows no sign-in page");
    await gotoOnion(page, admin("login"));
    await expect(page.locator(PASSWORD)).toBeVisible({ timeout: resolveTimeout(60_000) });
    await inBothModes(page, async (mode) => {
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in page ${mode}`);
      await assertToken(page, SIGN_IN_BOX, "background-color", "--design-surface-2", `sign-in box ${mode}`);
      await assertToken(page, PASSWORD, "background-color", "--design-surface-2", `password field ${mode}`);
      await assertToken(page, PASSWORD, "color", "--design-text", `password field ${mode}`);
      await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in action ${mode}`);
      await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in action ${mode}`);
    });
    await assertLightAndDark(page, SIGN_IN_BOX, "Pi-hole sign-in");
    await assertReadable(
      page,
      [".login-logo .logo-lg", SUBMIT, ".login-footer a", ".login-donate", "#forgot-pw-box .box-title"],
      "Pi-hole sign-in",
    );
    if (title) {
      await expect(page).toHaveTitle(title);
      await expect(page.locator(".login-logo .logo-lg")).toHaveText(title);
    }
    if (logoUrl) {
      const logo = page.locator("img.loginpage-logo");
      await expect(logo).toHaveCSS("content", `url("${logoUrl}")`);
      const box = await logo.boundingBox();
      expect(Math.abs(box.width - box.height), "the sign-in page gives its logo a square box").toBeLessThanOrEqual(1);
    }
  });

  test("design: a pinned theme drives the palette and a foreign theme keeps its own colors", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signedIn(page, async () => {
      await page
        .context()
        .grantPermissions(["local-network-access"])
        .catch(() => {});
      const root = page.locator("html");
      await page.emulateMedia({ colorScheme: "light" });
      await open(page, "groups", PRIMARY_ACTION);
      await expect(root, "without a pinned theme the palette follows the browser").not.toHaveAttribute(
        "data-design-theme",
        /.+/,
      );
      const light = await tokenValue(page, "--design-surface-2", "background-color");

      await pinTheme(page, "default-dark");
      await open(page, "groups", PRIMARY_ACTION);
      await expect(root).toHaveAttribute("data-design-theme", "dark");
      await assertToken(page, PANEL, "background-color", "--design-surface-2", "pinned dark theme");
      expect(await tokenValue(page, "--design-surface-2", "background-color"), "the dark palette must differ").not.toBe(
        light,
      );

      await page.emulateMedia({ colorScheme: "dark" });
      await pinTheme(page, "default-light");
      await open(page, "groups", PRIMARY_ACTION);
      await expect(root).toHaveAttribute("data-design-theme", "light");
      await assertToken(page, PANEL, "background-color", "--design-surface-2", "pinned light theme");
      expect(await tokenValue(page, "--design-surface-2", "background-color")).toBe(light);

      await pinTheme(page, "high-contrast");
      await open(page, "groups", PRIMARY_ACTION);
      const frame = await tokenValue(page, "--design-frame", "background-color");
      await expect(page.locator(NAVBAR), "a theme outside the default family keeps its own top bar").not.toHaveCSS(
        "background-color",
        frame,
      );
      await pinTheme(page, null);
      await page.emulateMedia({ colorScheme: null });
      await gotoOnion(page, admin(""));
      await shellReady(page);
    });
  });

  test("design: gallery of sign-in, dashboard, lists, settings, tools and menus", async ({ page, browser }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    const failures = [];
    if (!issuer) {
      const visitor = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        await captureDesignGallery(await visitor.newPage(), signInViews());
      } catch (error) {
        failures.push(error.message);
      }
      await visitor.close();
    }
    await signedIn(page, async () => {
      await seedShowcase(page);
      try {
        await captureDesignGallery(page, signedInViews());
      } catch (error) {
        failures.push(error.message);
      }
      await gotoOnion(page, admin(""));
      await shellReady(page);
    });
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
