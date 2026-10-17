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
const { apiGetOnion, clickOidcLoginLink, decodeDotenvQuotedValue, gotoOnion, performKeycloakLogin } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { awaitSession } = require("./_shared");

const SEED_PREFIX = "Design showcase";
const WIDE_VIEWPORT = { width: 1440, height: 900 };

function baseUrl() {
  return decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
}

function roleTheme() {
  return decodeDotenvQuotedValue(process.env.DESIGN_THEME);
}

function toHex(rgb) {
  return `#${rgb
    .match(/\d+/g)
    .slice(0, 3)
    .map((part) => Number(part).toString(16).padStart(2, "0"))
    .join("")}`;
}

const LOGIN_ACTION = "#login #btn-login:visible, #login #sign-in:visible";

async function openLogin(page) {
  await gotoOnion(page, `${baseUrl()}/`);
  await expect(page.locator(LOGIN_ACTION).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function signIn(page) {
  const base = baseUrl();
  const username = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
  await gotoOnion(page, `${base}/`);
  if (isServiceEnabled("sso")) {
    const trigger = page.locator("#sign-in");
    const authPage = await clickOidcLoginLink(page, trigger, trigger);
    if (authPage) {
      await performKeycloakLogin(
        authPage,
        username,
        decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
        decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
      );
    }
    await awaitSession(
      page,
      resolveTimeout(60_000),
      "the OIDC callback must mint a session before the opener navigates away",
    );
    await gotoOnion(page, `${base}/`);
  } else {
    const password = page.locator("#field-password");
    await expect(password).toBeEditable({ timeout: resolveTimeout(30_000) });
    await page.locator("#field-userName").fill(username);
    await password.fill(
      decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD) || decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
    );
    await page.locator("#btn-login").click();
  }
  await expect(page.locator("#navbar .navbar")).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function openSignedIn(page, route, ready) {
  await gotoOnion(page, `${baseUrl()}/#${route}`);
  await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function espoApi(page, method, path, data) {
  return page.evaluate(
    async ([verb, route, body]) => {
      const key = Object.keys(localStorage).find((name) => /user-auth$/.test(name));
      const raw = key ? localStorage.getItem(key) : "";
      const auth = raw.startsWith('"') ? JSON.parse(raw) : raw;
      const response = await fetch(`api/v1/${route}`, {
        method: verb,
        headers: {
          "Content-Type": "application/json",
          "Espo-Authorization": auth,
          "Espo-Authorization-By-Token": "true",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return {
        status: response.status,
        json: response.ok ? await response.json() : null,
        error: response.ok ? "" : response.headers.get("X-Status-Reason") || (await response.text()).slice(0, 200),
      };
    },
    [method, path, data],
  );
}

async function currentUserId(page) {
  const me = await espoApi(page, "GET", "App/user");
  expect(me.status, "EspoCRM must answer App/user for the signed-in administrator").toBe(200);
  return me.json.user.id;
}

async function seed(page, entity, records) {
  const ids = [];
  for (const record of records) {
    const query = `where[0][type]=equals&where[0][attribute]=name&where[0][value]=${encodeURIComponent(record.name)}`;
    const found = await espoApi(page, "GET", `${entity}?${query}`);
    expect(found.status, `searching ${entity} ${record.name}`).toBe(200);
    if (found.json.total > 0) {
      ids.push(found.json.list[0].id);
      continue;
    }
    const created = await espoApi(page, "POST", entity, record);
    expect(created.status, `seeding ${entity} ${record.name}: ${created.error}`).toBe(200);
    ids.push(created.json.id);
  }
  return ids;
}

function readyView(name, url, ready) {
  return {
    name,
    url,
    prepare: async (current) => {
      await expect(current.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    },
  };
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLogin(page);
    await assertDesignTokens(page, "espocrm");
  });

  test("design: the corporate theme carries the login page in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openLogin(page);
    await expect(
      page.locator("link#main-stylesheet"),
      "the system theme must link the corporate theme stylesheet",
    ).toHaveAttribute("href", /\/theme\.css\?/);
    const sso = isServiceEnabled("sso");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `espocrm login ${mode}`;
      await assertToken(page, "body", "background-color", "--design-surface-1", label);
      await assertToken(page, "body", "color", "--design-text", label);
      await assertToken(page, "#login", "background-color", "--design-surface-2", label);
      await assertToken(page, "#login .panel-heading", "background-color", "--design-frame", label);
      if (sso) {
        await assertToken(page, "#sign-in", "background-color", "--design-surface-2", label);
        await assertToken(page, "#sign-in", "color", "--design-text", label);
        await assertToken(page, "#sign-in", "border-top-color", "--design-border-strong", label);
      } else {
        await assertToken(page, "#field-userName", "border-top-color", "--design-border-strong", label);
        await assertToken(page, "#btn-login", "background-color", "--design-primary", label);
        await assertToken(page, "#btn-login", "color", "--design-on-primary", label);
      }
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#login .panel-body", "espocrm login");
    await assertReadable(
      page,
      [
        "#login .panel-body",
        ...["#login label", "#field-userName", "#btn-login", "#sign-in"].map((selector) => ({
          selector,
          optional: true,
        })),
      ],
      "espocrm login",
    );
  });

  test("design: signed-in chrome follows the frame, the panels and the content divider", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await seed(page, "Account", [{ name: `${SEED_PREFIX} GmbH`, type: "Customer", industry: "Software" }]);
    await openSignedIn(page, "Account", "#main .list-container table tbody tr");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `espocrm account list ${mode}`;
      await assertToken(page, "#navbar .navbar", "background-color", "--design-frame", label);
      await assertToken(page, "#navbar .navbar ul.tabs > li.tab > a", "color", "--design-on-frame", label);
      await assertToken(page, "#main .list-container .list", "background-color", "--design-surface-2", label);
      await assertToken(page, "#main .list-container table tbody tr td", "border-top-color", "--design-border", label);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#main .list-container .list", "espocrm account list");
    await assertReadable(
      page,
      ["#navbar .navbar ul.tabs > li.tab > a", "#main .page-header", "#main .list-container table tbody a"],
      "espocrm account list",
    );
  });

  test("design: keyboard focus inside the side menu draws in the frame text color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize(WIDE_VIEWPORT);
    await signIn(page);
    await openSignedIn(page, "Account", "#main .list-container");
    const links = page.locator("#navbar .navbar ul.tabs > li.tab > a:visible");
    await expect(links.first()).toBeVisible({ timeout: resolveTimeout(30_000) });
    const stops = Math.min(await links.count(), 6);
    await page.keyboard.press("Tab");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      const onFrame = await tokenValue(page, "--design-on-frame", "outline-color");
      for (let stop = 0; stop < stops; stop += 1) {
        await links.nth(stop).focus();
        const focus = await links.nth(stop).evaluate((element) => {
          const style = getComputedStyle(element);
          return { style: style.outlineStyle, color: style.outlineColor };
        });
        expect(focus.style, `espocrm side menu focus stop ${stop} ${mode}`).not.toBe("none");
        expect(focus.color, `espocrm side menu focus stop ${stop} ${mode}`).toBe(onFrame);
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: a theme the user picks wins over the browser preference", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await page.emulateMedia({ colorScheme: "light" });
    await openSignedIn(page, "Account", "#main .list-container");
    await expect(page.locator("body")).toHaveAttribute("data-theme-name", roleTheme());
    await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");
    const userId = await currentUserId(page);
    try {
      expect((await espoApi(page, "PUT", `Preferences/${userId}`, { theme: "Dark" })).status).toBe(200);
      await gotoOnion(page, `${baseUrl()}/`);
      await expect(page.locator("body")).toHaveAttribute("data-theme-name", "Dark", { timeout: resolveTimeout(30_000) });
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
      expect(
        await tokenValue(page, "--design-surface-1", "background-color"),
        "the injected tokens must follow the dark theme the user picked",
      ).not.toBe(lightSurface);
      await expect(page.locator("link#main-stylesheet")).not.toHaveAttribute("href", /\/theme\.css\?/);
    } finally {
      expect((await espoApi(page, "PUT", `Preferences/${userId}`, { theme: null })).status).toBe(200);
    }
  });

  test("design: EspoCRM shows the corporate logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
    await openLogin(page);
    if (title) {
      await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
    if (logoUrl) {
      await page.emulateMedia({ colorScheme: "light" });
      const onFrame = toHex(await tokenValue(page, "--design-on-frame", "color"));
      const generated = await (await apiGetOnion(page.request, logoUrl)).text();
      const src = await page.locator("#login .logo-container img.logo").getAttribute("src");
      const served = await (await apiGetOnion(page.request, new URL(src, `${baseUrl()}/`).href)).text();
      expect(served, "EspoCRM must serve the generated corporate logo on the login page").toBe(generated);
      expect(served.toLowerCase(), "the logo lockup text must take the frame text color").toContain(`fill="${onFrame}"`);
      await page.setViewportSize(WIDE_VIEWPORT);
      await signIn(page);
      const box = await page
        .locator("#navbar img.logo")
        .evaluateAll((images) =>
          images
            .map((image) => image.getBoundingClientRect())
            .filter((rect) => rect.width > 0)
            .map((rect) => ({ width: rect.width, height: rect.height })),
        );
      expect(box.length, "the side menu must show the corporate logo").toBeGreaterThan(0);
      expect(box[0].width, "the side menu logo must render as a wide lockup").toBeGreaterThan(box[0].height);
    }
  });

  test("design: the Administration takes surfaces, text, dividers and the primary action from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.setViewportSize(WIDE_VIEWPORT);
    await signIn(page);
    const panel = "#main .admin-tables-container table.table-admin-panel";
    const row = `${panel} tr.admin-content-row`;
    const searchField = '#main .admin-search-container input[data-name="quick-search"]';
    const search = page.locator(searchField);
    await openSignedIn(page, "Admin", panel);
    await expect(
      page.locator("#main .admin-right-column iframe"),
      "adminPanelIframeDisabled keeps the third-party news panel of s.espocrm.com off the Administration",
    ).toHaveCount(0);
    await search.blur();
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `espocrm administration ${mode}`;
      await assertToken(page, "#navbar .navbar", "background-color", "--design-frame", label);
      await assertToken(page, panel, "background-color", "--design-surface-2", label);
      await assertToken(page, panel, "border-top-color", "--design-border", label);
      await assertToken(page, `${row} + tr.admin-content-row > td`, "border-top-color", "--design-border", label);
      await assertToken(page, `${row} > td:first-child a`, "color", "--design-text", label);
      await assertToken(page, `${row} > td:nth-child(2)`, "color", "--design-text-muted", label);
      await assertToken(page, searchField, "background-color", "--design-surface-2", label);
      await assertToken(page, searchField, "border-top-color", "--design-border-strong", label);
      await search.focus();
      await assertToken(page, searchField, "border-top-color", "--design-link", `${label} focused search`);
      await search.blur();
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, panel, "espocrm administration");
    await assertReadable(
      page,
      ["#main .page-header h3", "#main .admin-content-section > h4", `${row} > td:first-child a`, `${row} > td:nth-child(2)`],
      "espocrm administration",
    );

    const save = '#main .record .edit .detail-button-container button[data-action="save"]';
    await openSignedIn(page, "Admin/settings", save);
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `espocrm system settings ${mode}`;
      await assertToken(page, save, "background-color", "--design-primary", label);
      await assertToken(page, save, "color", "--design-on-primary", label);
      await page.locator(save).hover();
      await assertToken(page, save, "background-color", "--design-primary-hover", `${label} hovered save`);
      await assertToken(page, save, "color", "--design-on-primary", `${label} hovered save`);
      await page.mouse.move(0, 0);
      await assertToken(page, "#main .record .edit input.form-control:visible", "border-top-color", "--design-border-strong", label);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#main .record .edit .panel", "espocrm system settings");
    await assertReadable(page, [save, "#main .record .edit .panel .control-label"], "espocrm system settings");
  });

  test("design: gallery of login, CRM and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    const base = baseUrl();
    const failures = [];

    try {
      await captureDesignGallery(page, [readyView("login", `${base}/`, LOGIN_ACTION)]);
    } catch (error) {
      failures.push(error.message);
    }

    await page.setViewportSize(WIDE_VIEWPORT);
    await signIn(page);
    const [accountId] = await seed(page, "Account", [
      { name: `${SEED_PREFIX} GmbH`, type: "Customer", industry: "Software" },
      { name: `${SEED_PREFIX} Ltd`, type: "Partner", industry: "Consulting" },
      { name: `${SEED_PREFIX} Inc`, type: "Investor", industry: "Finance" },
    ]);
    const [contactId] = await seed(page, "Contact", [
      { name: `Ada ${SEED_PREFIX}`, firstName: "Ada", lastName: SEED_PREFIX, accountId },
    ]);
    await seed(page, "Lead", [
      { name: `New ${SEED_PREFIX}`, firstName: "New", lastName: SEED_PREFIX, status: "New" },
      { name: `Assigned ${SEED_PREFIX}`, firstName: "Assigned", lastName: SEED_PREFIX, status: "Assigned" },
      { name: `Dead ${SEED_PREFIX}`, firstName: "Dead", lastName: SEED_PREFIX, status: "Dead" },
    ]);
    const settings = await espoApi(page, "GET", "Settings");
    const [amountCurrency] = settings.json.currencyList;
    await seed(page, "Opportunity", [
      { name: `${SEED_PREFIX} Deal A`, accountId, stage: "Prospecting", amount: 1000, amountCurrency, closeDate: "2027-01-31" },
      { name: `${SEED_PREFIX} Deal B`, accountId, stage: "Negotiation", amount: 5000, amountCurrency, closeDate: "2027-02-28" },
    ]);
    await seed(page, "Case", [{ name: `${SEED_PREFIX} Case`, accountId, status: "New", priority: "High" }]);
    const userId = await currentUserId(page);
    await seed(page, "Task", [
      { name: `${SEED_PREFIX} Task`, status: "Not Started", priority: "Urgent", assignedUserId: userId },
    ]);

    try {
      await captureDesignGallery(page, [
        readyView("home", `${base}/#Home`, "#main .dashboard-layout, #main .dashlet"),
        readyView("account-list", `${base}/#Account`, "#main .list-container table tbody tr"),
        readyView("account-detail", `${base}/#Account/view/${accountId}`, "#main .record .detail"),
        readyView("account-edit", `${base}/#Account/edit/${accountId}`, "#main .record .edit input[data-name='name']"),
        readyView("account-create", `${base}/#Account/create`, "#main .record .edit input[data-name='name']"),
        readyView("contact-list", `${base}/#Contact`, "#main .list-container table tbody tr"),
        readyView("contact-detail", `${base}/#Contact/view/${contactId}`, "#main .record .detail"),
        readyView("lead-list", `${base}/#Lead`, "#main .list-container table tbody tr"),
        readyView("opportunity-list", `${base}/#Opportunity`, "#main .list-container table tbody tr"),
        readyView("case-list", `${base}/#Case`, "#main .list-container table tbody tr"),
        readyView("task-list", `${base}/#Task`, "#main .list-container table tbody tr"),
        readyView("calendar", `${base}/#Calendar`, "#main .fc"),
        readyView("stream", `${base}/#Stream`, "#main .list-container, #main .no-data"),
        readyView("preferences", `${base}/#Preferences/edit/${userId}`, "#main .record .edit"),
        readyView("user-detail", `${base}/#User/view/${userId}`, "#main .record .detail"),
        readyView("admin-index", `${base}/#Admin`, "#main .admin-tables-container table.table-admin-panel"),
        readyView("admin-settings", `${base}/#Admin/settings`, "#main .record .edit"),
        readyView("admin-user-interface", `${base}/#Admin/userInterface`, "#main .record .edit"),
        readyView("admin-users", `${base}/#User`, "#main .list-container table tbody tr"),
        readyView("admin-entity-manager", `${base}/#Admin/entityManager`, "#main table tbody tr"),
        readyView("admin-extensions", `${base}/#Admin/extensions`, "#main input[type='file']"),
        {
          name: "menu-open",
          url: `${base}/?menu#Account`,
          prepare: async (current) => {
            await expect(current.locator("#main .list-container")).toBeVisible({ timeout: resolveTimeout(10_000) });
            const toggle = current.locator("#navbar .navbar-toggle");
            const opened = (await toggle.isVisible())
              ? current.locator("#navbar .navbar-body.in ul.tabs").first()
              : current.locator("#nav-menu-dropdown + .dropdown-menu");
            if (!(await opened.isVisible())) {
              await ((await toggle.isVisible()) ? toggle : current.locator("#nav-menu-dropdown")).click();
            }
            await expect(opened).toBeVisible({ timeout: resolveTimeout(10_000) });
          },
        },
      ]);
    } catch (error) {
      failures.push(error.message);
    }
    expect(failures, "design gallery views failed").toEqual([]);
  });
};
