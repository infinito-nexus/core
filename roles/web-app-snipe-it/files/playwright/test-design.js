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
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.SNIPE_IT_BASE_URL, "SNIPE_IT_BASE_URL")).replace(/\/$/, "");
const username = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const password = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const ssoEnabled = process.env.SSO_SERVICE_ENABLED === "true";
const issuer = ssoEnabled
  ? normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"))
  : "";
const ROW = "table.snipe-table tbody tr[data-index]";
const FRAME = ".main-header, .main-sidebar";
const USER_MENU = "li.user.user-menu > a.dropdown-toggle";
const READY_MS = 10_000;

test.use({ ignoreHTTPSErrors: true });

async function signIn(page) {
  await gotoOnion(page, `${base}/login`);
  if (ssoEnabled) {
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(READY_MS) })
      .toContain(`${issuer}/protocol/openid-connect/auth`);
    await performKeycloakLoginForm(page, username, password);
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(READY_MS) })
      .toContain(base.replace(/^https?:\/\//, ""));
  } else {
    const secret = page.locator("#password-field");
    await expect(secret).toBeEditable({ timeout: resolveTimeout(READY_MS) });
    await page.locator("#username").fill(username);
    await secret.fill(password);
    await page.locator("#submit").click();
    await expect.poll(() => page.url(), { timeout: resolveTimeout(READY_MS) }).not.toContain("/login");
  }
  await gotoOnion(page, `${base}/`);
  await expect(page.locator(".main-header .navbar")).toBeVisible({ timeout: resolveTimeout(READY_MS) });
}

async function seedShowcase(page) {
  return page.evaluate(async () => {
    const headers = {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-TOKEN": document.querySelector("meta[name='csrf-token']").content,
      "X-Requested-With": "XMLHttpRequest",
    };
    const api = async (method, path, body) => {
      const response = await fetch(`/api/v1/${path}`, {
        method,
        headers,
        credentials: "same-origin",
        body: body ? JSON.stringify(body) : undefined,
      });
      const json = await response.json();
      if (!response.ok || json.status === "error") {
        throw new Error(`${method} ${path}: ${response.status} ${JSON.stringify(json.messages || json).slice(0, 300)}`);
      }
      return json;
    };
    const ensure = async (path, body) => {
      const found = await api("GET", `${path}?search=${encodeURIComponent(body.name)}&limit=50`);
      const row = (found.rows || []).find((entry) => entry.name === body.name);
      return row ? row.id : (await api("POST", path, body)).payload.id;
    };
    const category = (name, type) => ensure("categories", { name, category_type: type });
    const manufacturer = await ensure("manufacturers", { name: "Showcase Manufacturing" });
    const status = await ensure("statuslabels", { name: "Showcase ready", type: "deployable" });
    await ensure("locations", { name: "Showcase headquarters" });
    const model = await ensure("models", {
      name: "Showcase notebook",
      category_id: await category("Showcase notebooks", "asset"),
      manufacturer_id: manufacturer,
    });
    const asset = await ensure("hardware", {
      name: "Showcase notebook 1",
      asset_tag: "SHOWCASE-0001",
      model_id: model,
      status_id: status,
    });
    await ensure("licenses", { name: "Showcase office suite", seats: 5, category_id: await category("Showcase software", "license") });
    await ensure("accessories", { name: "Showcase keyboard", qty: 5, category_id: await category("Showcase peripherals", "accessory") });
    await ensure("consumables", { name: "Showcase toner", qty: 10, category_id: await category("Showcase supplies", "consumable") });
    await ensure("components", { name: "Showcase memory module", qty: 8, category_id: await category("Showcase parts", "component") });
    return { asset };
  });
}

function ready(selector) {
  return async (p) => {
    await expect(p.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  };
}

function visitorViews() {
  return ssoEnabled
    ? []
    : [
        { name: "login", url: `${base}/login`, prepare: ready("#username") },
        { name: "password-reset", url: `${base}/password/reset`, prepare: ready("header.basic-page-header") },
      ];
}

function signedInViews(seeded) {
  const signedIn = [
    ["dashboard", "/", ".small-box"],
    ["asset-list", "/hardware", ROW],
    ["asset-detail", `/hardware/${seeded.asset}`, ".nav-tabs-custom"],
    ["asset-create", "/hardware/create", "#main form"],
    ["license-list", "/licenses", ROW],
    ["accessory-list", "/accessories", ROW],
    ["consumable-list", "/consumables", ROW],
    ["component-list", "/components", ROW],
    ["user-list", "/users", ROW],
    ["user-create", "/users/create", "#main form"],
    ["model-list", "/models", ROW],
    ["category-list", "/categories", ROW],
    ["statuslabel-list", "/statuslabels", ROW],
    ["location-list", "/locations", ROW],
    ["report-activity", "/reports/activity", ROW],
    ["report-custom", "/reports/custom", "#main form"],
    ["calendar", "/calendar", ".fc"],
    ["import", "/import", "h1.pagetitle"],
    ["account-profile", "/account/profile", "#main form"],
    ["account-api", "/account/api", "h1.pagetitle"],
    ["admin-index", "/admin", "#main .box"],
    ["admin-general", "/admin/settings", "#main form"],
    ["admin-branding", "/admin/branding", "#main form"],
    ["admin-security", "/admin/security", "#main form"],
    ["admin-localization", "/admin/localization", "#main form"],
    ["admin-notifications", "/admin/notifications", "#main form"],
    ["admin-groups", "/admin/groups", "h1.pagetitle"],
    ["admin-backups", "/admin/backups", "h1.pagetitle"],
  ].map(([name, path, selector]) => ({ name, url: `${base}${path}`, prepare: ready(selector) }));
  signedIn.push({
    name: "user-menu-open",
    url: `${base}/`,
    prepare: async (p) => {
      await p.locator(USER_MENU).click();
      const menu = p.locator("li.user.user-menu.open .dropdown-menu");
      await expect(menu).toBeVisible({ timeout: resolveTimeout(READY_MS) });
      await expect.poll(() => menu.evaluate((el) => getComputedStyle(el).opacity)).toBe("1");
    },
  });
  return signedIn;
}

function hexToRgb(hex) {
  const value = hex.trim().replace(/^#/, "");
  return `rgb(${[0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16)).join(", ")})`;
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "snipe-it");
});

test("design: surfaces, text and the frame carry the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${base}/admin/branding`);
  await expect(page.locator("#main .box").first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  await assertToken(page, ".content-wrapper", "background-color", "--design-surface-1", "snipe-it");
  await assertToken(page, "#main .box", "background-color", "--design-surface-2", "snipe-it");
  await assertToken(page, "#main .box label", "color", "--design-text", "snipe-it");
  await assertToken(page, ".main-header .navbar", "background-color", "--design-frame", "snipe-it");
  await assertToken(page, ".main-sidebar", "background-color", "--design-frame", "snipe-it");
  await assertToken(page, ".sidebar-menu > li > a", "color", "--design-on-frame", "snipe-it");
  await assertLightAndDark(page, "#main .box label", "snipe-it");
  await assertReadable(
    page,
    ["#main .box label", "#main .box-title", ".main-footer", ".sidebar-menu > li > a", "h1.pagetitle"],
    "snipe-it",
  );
});

test("design: the app's own theme color follows the frame token in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${base}/admin/branding`);
  await expect(page.locator("#main .box").first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await expect(page.locator("html")).toHaveAttribute("data-theme", mode);
    await assertToken(page, ".main-header .navbar", "background-color", "--design-frame", `snipe-it ${mode}`);
    await assertToken(page, "#main .box", "background-color", "--design-surface-2", `snipe-it ${mode}`);
  }
  await page.emulateMedia({ colorScheme: "light" });
  const baked = await page.locator("meta[name='theme-color']").getAttribute("content");
  expect(hexToRgb(baked), "the header color setting carries the light frame token").toBe(
    await tokenValue(page, "--design-frame", "color"),
  );
  await page.emulateMedia({ colorScheme: null });
});

test("design: text on filled controls follows the on-color of its fill", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${base}/admin/branding`);
  await expect(page.locator("#main .box").first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  await assertToken(page, ".content-wrapper .btn-primary", "background-color", "--design-primary", "snipe-it");
  await assertToken(page, ".content-wrapper .btn-primary", "color", "--design-on-primary", "snipe-it");
  await assertToken(page, ".content-wrapper .btn-success", "background-color", "--design-success", "snipe-it");
  await assertToken(page, ".content-wrapper .btn-success", "color", "--design-on-success", "snipe-it");
  await assertToken(page, ".content-wrapper .btn-theme", "background-color", "--design-frame", "snipe-it");
  await assertToken(page, ".content-wrapper .btn-theme", "color", "--design-on-frame", "snipe-it");
});

test("design: panels are bordered by --design-border", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${base}/admin/branding`);
  const panel = page.locator("#main .box").first();
  await expect(panel).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  expect(
    await panel.evaluate((el) => getComputedStyle(el).borderTopWidth),
    "the panel draws its top border",
  ).not.toBe("0px");
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await expect(page.locator("html")).toHaveAttribute("data-theme", mode);
    await assertToken(page, "#main .box", "border-top-color", "--design-border", `snipe-it ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: dashboard tiles and form fields stay on the palette in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await expect(page.locator(".small-box").first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  await assertReadable(page, [".small-box h3", ".small-box p"], "snipe-it");
  await gotoOnion(page, `${base}/users`);
  await expect(page.locator(".fixed-table-toolbar input.search-input").first()).toBeVisible({
    timeout: resolveTimeout(READY_MS),
  });
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await expect(page.locator("html")).toHaveAttribute("data-theme", mode);
    await assertToken(
      page,
      ".fixed-table-toolbar input.search-input",
      "background-color",
      "--design-surface-2",
      `snipe-it ${mode}`,
    );
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: notices keep body text on their status tint", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${base}/account/api`);
  await expect(page.locator(".content-wrapper .alert").first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  await assertToken(page, ".content-wrapper .alert", "color", "--design-text", "snipe-it");
  await assertReadable(page, [".content-wrapper .alert"], "snipe-it");
});

test("design: the top bar menu stays on the frame at the mobile width", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  await page.locator(USER_MENU).click();
  await expect(page.locator("li.user.user-menu.open > .dropdown-menu")).toBeVisible();
  await assertToken(page, "li.user.user-menu > .dropdown-menu", "background-color", "--design-frame", "snipe-it");
});

test("design: logo and title are the configured ones", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  expect(title, "the lockup title only carries glyphs of the lockup font").toMatch(/^[ -~]+$/);
  await signIn(page);
  await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  const logo = page.locator(".main-header img.navbar-brand-img");
  await expect(logo).toBeVisible();
  await expect(logo).toHaveAttribute("src", /design-logo-[0-9a-f]{12}\.png/);
  await expect
    .poll(() => logo.evaluate((img) => img.naturalWidth), { message: "the logo is served" })
    .toBeGreaterThan(0);
  const box = await logo.boundingBox();
  expect(box.width, "the logo box in the top bar is wider than high").toBeGreaterThan(box.height);
  await expect(page.locator("link[rel='shortcut icon']")).toHaveAttribute(
    "href",
    /design-favicon-[0-9a-f]{12}\.png/,
  );
});

test("design: the native theme switch drives the tokens", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.emulateMedia({ colorScheme: "light" });
  await signIn(page);
  await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
  const light = await tokenValue(page, "--design-surface-1", "color");
  await page.locator(USER_MENU).click();
  await page.locator(".user-menu [data-theme-toggle]").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
  expect(await tokenValue(page, "--design-surface-1", "color")).not.toBe(light);
  await page.evaluate(() => localStorage.removeItem("theme"));
  await gotoOnion(page, page.url());
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await tokenValue(page, "--design-surface-1", "color")).toBe(light);
  await page.emulateMedia({ colorScheme: null });
});

test("design: focus stops inside the frame draw their indicator in --design-on-frame", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  const expected = await tokenValue(page, "--design-on-frame", "color");
  await page.locator(".main-header a[href]").first().focus();
  const stops = [];
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate((frame) => {
      const el = document.activeElement;
      if (!el || !el.closest(frame)) return null;
      const style = getComputedStyle(el);
      return { tag: el.tagName, style: style.outlineStyle, color: style.outlineColor };
    }, FRAME);
    if (stop) stops.push(stop);
  }
  expect(stops.length, "the Tab walk reaches focus stops inside the frame").toBeGreaterThan(2);
  for (const stop of stops) {
    expect(stop.style, `${stop.tag} draws a focus outline`).not.toBe("none");
    expect(stop.color, `${stop.tag} draws its focus outline in --design-on-frame`).toBe(expected);
  }
});

test("design: gallery of user and administration views", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(1_800_000));

  const failures = [];
  await captureDesignGallery(page, visitorViews()).catch((error) => failures.push(error.message));
  await signIn(page);
  const signedIn = signedInViews(await seedShowcase(page));
  await captureDesignGallery(page, signedIn).catch((error) => failures.push(error.message));
  expect(failures, failures.join("\n")).toEqual([]);
});
