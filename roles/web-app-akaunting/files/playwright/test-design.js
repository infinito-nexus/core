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

const base = normalizeBaseUrl(requireDotenvValue(process.env.AKAUNTING_BASE_URL, "AKAUNTING_BASE_URL")).replace(/\/$/, "");
const adminEmail = decodeDotenvQuotedValue(requireDotenvValue(process.env.AKAUNTING_ADMIN_EMAIL, "AKAUNTING_ADMIN_EMAIL"));
const adminPassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.AKAUNTING_ADMIN_PASSWORD, "AKAUNTING_ADMIN_PASSWORD"));
const ssoUsername = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"));
const ssoPassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(requireDotenvValue(process.env.DESIGN_FAVICON_URL, "DESIGN_FAVICON_URL"));
const documentColor = decodeDotenvQuotedValue(process.env.DESIGN_DOCUMENT_COLOR || "");

const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const SIGN_IN_FORM = "form#auth";
const EMAIL = `${SIGN_IN_FORM} input[name="email"]`;
const PASSWORD = `${SIGN_IN_FORM} input[name="password"]`;
const SUBMIT = `${SIGN_IN_FORM} button[type="submit"]`;
const SIGN_IN_HEADING = "#app h1";
const HEADER = "#header h1";
const RAIL = ".js-menu .bg-lilac-900";
const RAIL_ICON = `${RAIL} .menu-button .material-icons-outlined, ${RAIL} .menu-button .material-icons`;
const SIDEBAR = "nav.menu-list.js-main-menu";
const LOGO = "img[src*='akaunting-logo-green.svg']";
const ROW = "table tbody tr";
const SAVE = "form#setting button[type='submit']";
const SHOWCASE = "Showcase Customer";

test.use({ ignoreHTTPSErrors: true });

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   page: Playwright page that ends on Akaunting's own sign-in form, passing Keycloak first when oauth2-proxy gates the app.
 */
async function openSignIn(page) {
  await page.context().clearCookies();
  await gotoOnion(page, `${base}/auth/login`);
  if (page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(page, ssoUsername, ssoPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(90_000) }).toContain(base);
    await gotoOnion(page, `${base}/auth/login`);
  }
  await shown(EMAIL)(page);
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the administrator the role provisions.
 */
async function signIn(page) {
  await openSignIn(page);
  await expect(page.locator(EMAIL)).toBeEditable({ timeout: resolveTimeout(10_000) });
  await page.locator(EMAIL).fill(adminEmail);
  await expect(page.locator(PASSWORD)).toBeEditable({ timeout: resolveTimeout(10_000) });
  await page.locator(PASSWORD).fill(adminPassword);
  await page.locator(SUBMIT).click({ timeout: resolveTimeout(30_000) });
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "the native sign-in must leave /auth/login" })
    .not.toContain("/auth/login");
}

/**
 * Args:
 *   page: Playwright page signed in as the administrator; creates the showcase customer, item and income through the app's own form endpoints when they are missing.
 *
 * Returns:
 *   The ids of the showcase customer, item and income.
 */
async function seedShowcase(page) {
  const call = async (method, path, data) => {
    const result = await page.evaluate(
      async ([verb, url, body]) => {
        const response = await fetch(url, {
          method: verb,
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-TOKEN": window.Laravel.csrfToken,
            "X-Requested-With": "XMLHttpRequest",
          },
          body: body ? JSON.stringify(body) : undefined,
        });
        return { status: response.status, text: await response.text() };
      },
      [method, `${base}/1/${path}`, data],
    );
    expect(result.status, `${method} /1/${path}: ${result.text.slice(0, 300)}`).toBe(200);
    return JSON.parse(result.text);
  };
  const firstId = async (path, search) => {
    const html = await page.evaluate(async (url) => (await fetch(url)).text(), `${base}/1/${path}?search=${search}`);
    const match = html.match(new RegExp(`/1/${path}/(\\d+)`));
    return match ? Number(match[1]) : 0;
  };
  const ensure = async (path, search, record) => {
    const found = await firstId(path, search);
    if (found) return found;
    await call("POST", path, record);
    const created = await firstId(path, search);
    expect(created, `the showcase record under /1/${path} must exist after it was created`).toBeGreaterThan(0);
    return created;
  };
  await gotoOnion(page, `${base}/1/banking/accounts`);
  const customer = await ensure("sales/customers", "Showcase", {
    type: "customer",
    name: SHOWCASE,
    currency_code: "USD",
    enabled: 1,
  });
  const item = await ensure("common/items", "Showcase", {
    type: "service",
    name: "Showcase consulting",
    sale_price: 120,
    purchase_price: 80,
    category_id: 5,
    enabled: 1,
  });
  const income = await ensure("banking/transactions", "TRA-SHOWCASE", {
    type: "income",
    number: "TRA-SHOWCASE",
    account_id: 1,
    paid_at: new Date().toISOString().slice(0, 10),
    amount: 80,
    currency_code: "USD",
    currency_rate: 1,
    category_id: 3,
    contact_id: customer,
    payment_method: "offline-payments.cash.1",
  });
  return { customer, item, income };
}

async function cssColor(page, value) {
  return page.evaluate((literal) => {
    const probe = document.createElement("span");
    probe.style.color = literal;
    document.body.appendChild(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  }, value);
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await openSignIn(page);
  await assertDesignTokens(page, "akaunting");
});

test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await openSignIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
    await expect(page.locator("#app").first(), `the sign-in backdrop image is dropped in ${mode} mode`).toHaveCSS("background-image", "none");
    await assertToken(page, "body", "color", "--design-text", `sign-in text ${mode}`);
    await assertToken(page, EMAIL, "background-color", "--design-surface-2", `sign-in field ${mode}`);
    await assertToken(page, EMAIL, "border-top-color", "--design-border-strong", `sign-in field ${mode}`);
    await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in button ${mode}`);
    await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in button ${mode}`);
    await page.locator(SUBMIT).hover();
    await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in button ${mode}`);
    await page.mouse.move(0, 0);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, EMAIL, "akaunting sign-in");
  await assertReadable(page, [SIGN_IN_HEADING, SUBMIT, `${SIGN_IN_FORM} a`], "akaunting sign-in");
});

test("design: the administrator reaches the dashboard instead of the setup wizard", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${base}/1`);
  await expect(page, "the setup wizard must be completed by the deploy").not.toHaveURL(/\/wizard\//);
  await shown(HEADER)(page);
});

test("design: the admin shell takes frame, surfaces, dividers and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await seedShowcase(page);
  await gotoOnion(page, `${base}/1/common/items`);
  await shown(ROW)(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-surface-1", `shell ${mode}`);
    await assertToken(page, SIDEBAR, "background-color", "--design-surface-2", `sidebar ${mode}`);
    await assertToken(page, RAIL, "background-color", "--design-frame", `rail ${mode}`);
    await assertToken(page, RAIL_ICON, "color", "--design-on-frame", `rail icon ${mode}`);
    await assertToken(page, HEADER, "color", "--design-text", `heading ${mode}`);
    await assertToken(page, ROW, "border-bottom-color", "--design-border", `row divider ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ROW, "akaunting list");
  await assertReadable(page, [HEADER, `${ROW} td`, `${SIDEBAR} li.group > a`], "akaunting shell");
});

test("design: the users list keeps its role badge and notices readable in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, `${base}/1/auth/users`);
  await shown(ROW)(page);
  await assertReadable(page, [`${ROW} span.bg-lilac-900`], "akaunting role badge");
  for (const [selector, token] of [
    [".bg-red-50", "--design-danger-subtle"],
    [".bg-orange-50", "--design-warning-subtle"],
  ]) {
    if ((await page.locator(selector).count()) === 0) continue;
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, selector, "background-color", token, `notice ${mode}`);
    }
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: every focus stop in the icon rail draws its indicator in the frame text color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, `${base}/1/settings/categories`);
  await shown(HEADER)(page);
  const expected = await tokenValue(page, "--design-on-frame", "outline-color");
  await page.locator("body").focus();
  const seen = [];
  for (let step = 0; step < 40 && seen.length < 5; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate((rail) => {
      const element = document.activeElement;
      if (!element || !element.closest(rail)) return null;
      const style = getComputedStyle(element);
      return { outline: `${style.outlineStyle} ${style.outlineColor}`, name: element.className };
    }, RAIL);
    if (stop) seen.push(stop);
  }
  expect(seen.length, "the rail must hold keyboard focus stops").toBeGreaterThan(0);
  for (const stop of seen) {
    expect(stop.outline, `focus indicator of ${stop.name}`).toBe(`solid ${expected}`);
  }
});

test("design: a settings form saves through a primary control in the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, `${base}/1/settings/company`);
  await shown(SAVE)(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, SAVE, "background-color", "--design-primary", `save ${mode}`);
    await assertToken(page, SAVE, "color", "--design-on-primary", `save ${mode}`);
    await assertToken(page, "form#setting input[name='name']", "border-top-color", "--design-border-strong", `field ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [HEADER, `${SAVE}`, "form#setting label"], "akaunting settings form");
});

test("design: invoices carry the light primary through the document color setting", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!documentColor, "the document color is not provisioned for this deployment");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, `${base}/1/settings/invoice`);
  await shown("form#setting")(page);
  await page.emulateMedia({ colorScheme: "light" });
  const stored = await page.locator("form#setting input[name='color']").first().inputValue();
  expect(await cssColor(page, stored), "invoice.color must hold the light primary").toBe(
    await tokenValue(page, "--design-primary", "color"),
  );
  await page.emulateMedia({ colorScheme: null });
});

test("design: a document head painted with the provisioned color follows the primary token in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!documentColor, "the document color is not provisioned for this deployment");
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, `${base}/1/settings/invoice`);
  await shown("form#setting")(page);
  const stored = await page.locator("form#setting input[name='color']").first().inputValue();
  await page.evaluate((color) => {
    const table = document.createElement("table");
    table.className = "lines";
    table.innerHTML = `<thead style="background-color:${color} !important;"><tr><th class="text-white">Item</th></tr></thead>`;
    document.querySelector("#app").appendChild(table);
  }, stored);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "table.lines thead", "background-color", "--design-primary", `document head ${mode}`);
    await assertToken(page, "table.lines thead th", "color", "--design-on-primary", `document head text ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: sign-in page and sidebar show the generated logo and favicon", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl, "logo replacement is disabled for this role");
  await openSignIn(page);
  await expect(page.locator(LOGO).first()).toHaveCSS("content", `url("${logoUrl}")`);
  await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
  await page.setViewportSize(DESKTOP);
  await signIn(page);
  await gotoOnion(page, `${base}/1/settings/categories`);
  await shown(HEADER)(page);
  const sidebarLogo = page.locator(`.js-menu ${LOGO}`).first();
  await expect(sidebarLogo).toHaveCSS("content", `url("${logoUrl}")`);
  const box = await sidebarLogo.boundingBox();
  expect(box && Math.round(box.width), "the sidebar keeps its square logo box").toBe(box && Math.round(box.height));
  await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
  await expect(page).toHaveTitle(/ - .+$/);
});

function signInViews() {
  const login = `${base}/auth/login`;
  return [
    { name: "sign-in", url: login, prepare: shown(EMAIL) },
    {
      name: "sign-in-focus",
      url: login,
      prepare: async (page) => {
        await shown(EMAIL)(page);
        await page.locator(EMAIL).focus();
      },
    },
    { name: "forgot-password", url: `${base}/auth/forgot`, prepare: shown("#app input[name='email']") },
  ];
}

function signedInViews(seed) {
  const view = (name, path, selector) => ({
    name,
    url: path ? `${base}/1/${path}` : `${base}/1`,
    prepare: shown(selector),
  });
  const drawer = (name, button, panel) => ({
    name,
    url: `${base}/1/common/items`,
    prepare: async (page) => {
      await shown(HEADER)(page);
      if (!(await page.locator(`${button}:visible`).count())) {
        await page.locator(".js-hamburger-menu:visible").first().dispatchEvent("click");
        await expect(page.locator(".js-menu").first()).toHaveClass(/left-0/, { timeout: resolveTimeout(10_000) });
        await page.waitForTimeout(resolveTimeout(600));
      }
      await page.locator(button).first().dispatchEvent("click");
      await expect(page.locator(panel)).toHaveClass(/left-14/, { timeout: resolveTimeout(10_000) });
      await page.waitForTimeout(resolveTimeout(600));
    },
  });
  return [
    view("wizard-company", "wizard/companies", "form"),
    view("dashboard", "", HEADER),
    view("items", "common/items", ROW),
    view("item-edit", `common/items/${seed.item}/edit`, "form input[name='name']"),
    view("customers", "sales/customers", ROW),
    view("customer-detail", `sales/customers/${seed.customer}`, HEADER),
    view("customer-edit", `sales/customers/${seed.customer}/edit`, "form input[name='name']"),
    view("invoices-empty", "sales/invoices", "#app"),
    view("vendors-empty", "purchases/vendors", "#app"),
    view("transactions", "banking/transactions", ROW),
    view("transaction-detail", `banking/transactions/${seed.income}`, HEADER),
    view("accounts", "banking/accounts", ROW),
    view("account-detail", "banking/accounts/1", HEADER),
    view("reports", "common/reports", HEADER),
    view("settings-company", "settings/company", SAVE),
    view("settings-invoice", "settings/invoice", "form#setting"),
    view("settings-localisation", "settings/localisation", "form#setting"),
    view("categories", "settings/categories", ROW),
    view("currencies", "settings/currencies", ROW),
    view("users", "auth/users", ROW),
    view("profile", "auth/profile/1/edit", "form input[name='email']"),
    drawer("settings-menu", "button.settings-item", ".settings-menu"),
    drawer("new-menu", "button.add-item", ".add-new-menu"),
  ];
}

test("design: gallery of sign-in, wizard, sales, banking, reports and settings", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(1_500_000));
  const failures = [];
  await captureDesignGallery(page, signInViews()).catch((error) => failures.push(error.message));
  await signIn(page);
  const seed = await seedShowcase(page);
  await captureDesignGallery(page, signedInViews(seed)).catch((error) => failures.push(error.message));
  expect(failures, "design gallery captures").toEqual([]);
});
