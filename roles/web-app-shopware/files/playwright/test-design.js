const crypto = require("node:crypto");

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
const { apiFetchOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { signIn, dismissFirstRunWizard } = require("./test-admin-native");

const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const designLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const designMenuLogoUrl = decodeDotenvQuotedValue(process.env.DESIGN_MENU_LOGO_URL || "");
const designTitle = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const SHOWCASE = {
  manufacturer: "d0000000000000000000000000000001",
  customer: "d0000000000000000000000000000002",
  address: "d0000000000000000000000000000003",
  products: [
    { id: "d0000000000000000000000000000011", number: "DESIGN-1", name: "Design showcase lamp", gross: 119 },
    { id: "d0000000000000000000000000000012", number: "DESIGN-2", name: "Design showcase chair", gross: 238 },
    { id: "d0000000000000000000000000000013", number: "DESIGN-3", name: "Design showcase table", gross: 476 },
  ],
  customerEmail: `design-showcase@${canonicalDomain}`,
  customerPassword: crypto.createHash("sha256").update(`design-showcase:${adminPassword}`).digest("hex"),
};
const THEME_FIELDS = [
  ["sw-color-brand-primary", "--design-primary"],
  ["sw-color-buy-button", "--design-primary"],
  ["sw-color-buy-button-text", "--design-on-primary"],
  ["sw-background-color", "--design-surface-1"],
  ["sw-text-color", "--design-text"],
  ["sw-border-color", "--design-border-strong"],
  ["sw-color-danger", "--design-danger"],
];
const INJECTED_SHEET = /\/_shared\/css\/|\/style\.css(\?|$)/;

async function adminApi(request, token, method, path, data) {
  const response = await apiFetchOnion(request, `${base}${path}`, {
    method,
    headers: { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    data,
    timeout: resolveTimeout(120_000),
  });
  if (response.status() >= 400) {
    const body = await response.json().catch(() => ({}));
    const details = (body.errors || []).map(
      (error) => `${error.source?.pointer || ""} ${error.code || ""} ${error.detail || ""}`,
    );
    expect(response.status(), `${method} ${path}: ${details.join(" | ")}`).toBeLessThan(400);
  }
  return response.status() === 204 ? {} : response.json();
}

async function adminToken(request) {
  const body = await adminApi(request, null, "POST", "/api/oauth/token", {
    client_id: "administration",
    grant_type: "password",
    scopes: "write",
    username: adminUsername,
    password: adminPassword,
  });
  return body.access_token;
}

async function storefrontTheme(request, token) {
  const themes = await adminApi(request, token, "POST", "/api/search/theme", {
    limit: 1,
    filter: [{ type: "equals", field: "technicalName", value: "Storefront" }],
  });
  return themes.data[0];
}

async function seedShowcase(request) {
  const token = await adminToken(request);
  const channels = await adminApi(request, token, "POST", "/api/search/sales-channel", {
    limit: 25,
    associations: { domains: {} },
  });
  const channel = channels.data.find((entry) =>
    (entry.domains || []).some((domain) => domain.url.includes(canonicalDomain)),
  );
  expect(channel, "a storefront sales channel must serve the canonical domain").toBeTruthy();
  const tax = (await adminApi(request, token, "POST", "/api/search/tax", { limit: 1, sort: [{ field: "position" }] }))
    .data[0];
  const theme = await storefrontTheme(request, token);
  const salutation = (
    await adminApi(request, token, "POST", "/api/search/salutation", {
      limit: 1,
      filter: [{ type: "equals", field: "salutationKey", value: "not_specified" }],
    })
  ).data[0];

  await adminApi(request, token, "POST", "/api/_action/sync", {
    "design-showcase-products": {
      entity: "product",
      action: "upsert",
      payload: SHOWCASE.products.map((product) => ({
        id: product.id,
        productNumber: product.number,
        name: product.name,
        description: "Seeded by the design gallery.",
        stock: 25,
        active: true,
        taxId: tax.id,
        manufacturer: { id: SHOWCASE.manufacturer, name: "Design showcase" },
        price: [
          {
            currencyId: channel.currencyId,
            gross: product.gross,
            net: Math.round((product.gross / (1 + tax.taxRate / 100)) * 100) / 100,
            linked: true,
          },
        ],
        categories: [{ id: channel.navigationCategoryId }],
        visibilities: [{ id: product.id, salesChannelId: channel.id, visibility: 30 }],
      })),
    },
    "design-showcase-customer": {
      entity: "customer",
      action: "upsert",
      payload: [
        {
          id: SHOWCASE.customer,
          customerNumber: "DESIGN-1",
          firstName: "Design",
          lastName: "Showcase",
          email: SHOWCASE.customerEmail,
          password: SHOWCASE.customerPassword,
          active: true,
          guest: false,
          salutationId: salutation.id,
          groupId: channel.customerGroupId,
          salesChannelId: channel.id,
          languageId: channel.languageId,
          defaultBillingAddressId: SHOWCASE.address,
          defaultShippingAddressId: SHOWCASE.address,
          addresses: [
            {
              id: SHOWCASE.address,
              salutationId: salutation.id,
              firstName: "Design",
              lastName: "Showcase",
              street: "Showcase 1",
              zipcode: "10115",
              city: "Berlin",
              countryId: channel.countryId,
            },
          ],
        },
      ],
    },
  });

  return { token, channel, theme };
}

async function openStorefront(page, path, ready) {
  await gotoOnion(page, `${base}${path}`);
  await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function openAdmin(page, hash, ready) {
  await signIn(page);
  await dismissFirstRunWizard(page);
  await gotoOnion(page, `${base}/admin#${hash}`);
  await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
}

function hexToRgb(hex) {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? value.replace(/./g, "$&$&") : value;
  return `rgb(${[0, 2, 4].map((index) => parseInt(full.slice(index, index + 2), 16)).join(", ")})`;
}

async function declineOptionalCookies(page) {
  await gotoOnion(page, `${base}/`);
  const bar = page.locator(".cookie-permission-container");
  await bar.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await bar.locator(".js-cookie-permission-button button").click({ timeout: resolveTimeout(30_000) });
  await bar.waitFor({ state: "hidden", timeout: resolveTimeout(30_000) });
}

async function signInCustomer(page) {
  await gotoOnion(page, `${base}/account/login`);
  const form = page.locator("form.login-form");
  await form.locator("input[name='username']").fill(SHOWCASE.customerEmail);
  await form.locator("input[name='password']").fill(SHOWCASE.customerPassword);
  await form.locator("input[name='password']").press("Enter");
  await expect(
    page.locator(".account-welcome"),
    "the showcase customer must reach the account overview through the storefront sign-in form",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function overlaySettled(page, selector) {
  await page.waitForFunction(
    (sel) => {
      const element = document.querySelector(sel);
      return (
        element !== null &&
        getComputedStyle(element).opacity === "1" &&
        element.getAnimations().every((animation) => animation.playState !== "running")
      );
    },
    selector,
    { timeout: resolveTimeout(10_000) },
  );
}

function galleryViews({ channel, theme, productUrl }) {
  const product = SHOWCASE.products[0].id;
  const ready = (selector) => (view) =>
    view.locator(selector).first().waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  const ensureCart = async (view) => {
    await gotoOnion(view, `${base}/checkout/cart`);
    await ready("main.content-main")(view);
    if ((await view.locator(".line-item").count()) > 0) return;
    await gotoOnion(view, productUrl);
    await view.locator(".btn-buy").first().click({ timeout: resolveTimeout(30_000) });
    await ready(".offcanvas.show .line-item")(view);
  };
  const admin = (name, hash, selector, prepare, loaded) => ({
    name,
    url: `${base}/admin#${hash}`,
    prepare: async (view) => {
      const wizard = view.locator(".sw-first-run-wizard-modal");
      const booted = () =>
        view
          .locator(`${selector}, .sw-first-run-wizard-modal`)
          .first()
          .waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
      const fresh = async () => {
        await gotoOnion(view, "about:blank");
        await gotoOnion(view, `${base}/admin#${hash}`);
      };
      if (prepare) await fresh();
      await booted().catch(async () => {
        await fresh();
        await booted();
      });
      if (await wizard.isVisible()) {
        await gotoOnion(view, `${base}/admin#${hash}`);
        await wizard.waitFor({ state: "hidden", timeout: resolveTimeout(30_000) });
      }
      await ready(selector)(view);
      if (loaded) await loaded(view);
      await expect(view.locator(".sw-loader:visible, .mt-loader:visible, .sw-skeleton:visible")).toHaveCount(0, {
        timeout: resolveTimeout(30_000),
      });
      if (prepare) await prepare(view);
    },
  });

  const guestViews = [
    { name: "storefront-sign-in", url: `${base}/account/login`, prepare: ready("form.login-form") },
    {
      name: "storefront-sign-in-error",
      url: `${base}/account/login`,
      prepare: async (view) => {
        const form = view.locator("form.login-form");
        await form.locator("input[name='username']").fill("nobody@example.org");
        await form.locator("input[name='password']").fill("wrong-on-purpose");
        await form.locator("input[name='password']").press("Enter");
        await ready(".alert-danger")(view);
      },
    },
    { name: "storefront-password-recover", url: `${base}/account/recover`, prepare: ready("main.content-main form") },
    {
      name: "storefront-checkout-register",
      url: `${base}/checkout/cart`,
      prepare: async (view) => {
        await ensureCart(view);
        await gotoOnion(view, `${base}/checkout/register`);
        await ready(".register-form")(view);
      },
    },
    { name: "admin-sign-in", url: `${base}/admin#/login`, prepare: ready(".sw-login__content input[type='password']") },
  ];

  const views = [
    { name: "storefront-home", url: `${base}/`, prepare: ready(".product-box") },
    { name: "storefront-product-detail", url: productUrl, prepare: ready(".btn-buy") },
    {
      name: "storefront-buy-button-hover",
      url: productUrl,
      prepare: async (view) => {
        await ready(".btn-buy")(view);
        await view.locator(".btn-buy").first().hover();
      },
    },
    { name: "storefront-search", url: `${base}/search?search=showcase`, prepare: ready(".product-box") },
    {
      name: "storefront-search-suggest",
      url: `${base}/`,
      prepare: async (view) => {
        const toggle = view.locator(".search-toggle-btn");
        if (await toggle.isVisible()) await toggle.click({ timeout: resolveTimeout(10_000) });
        await view.locator(".header-search-input").fill("showcase");
        await ready(".search-suggest-product")(view);
      },
    },
    {
      name: "storefront-cart-offcanvas",
      url: `${base}/checkout/cart`,
      prepare: async (view) => {
        await ensureCart(view);
        await gotoOnion(view, `${base}/`);
        await view.locator(".header-cart-btn").first().click({ timeout: resolveTimeout(30_000) });
        await ready(".offcanvas.show .line-item")(view);
        await overlaySettled(view, ".offcanvas.show");
      },
    },
    {
      name: "storefront-cart",
      url: `${base}/checkout/cart`,
      prepare: async (view) => {
        await ensureCart(view);
        await gotoOnion(view, `${base}/checkout/cart`);
        await ready(".line-item")(view);
      },
    },
    {
      name: "storefront-checkout-confirm",
      url: `${base}/checkout/cart`,
      prepare: async (view) => {
        await ensureCart(view);
        await gotoOnion(view, `${base}/checkout/confirm`);
        await ready("#confirmOrderForm")(view);
      },
    },
    { name: "storefront-account", url: `${base}/account`, prepare: ready(".account-welcome") },
    { name: "storefront-account-profile", url: `${base}/account/profile`, prepare: ready("#profilePersonalForm") },
    {
      name: "storefront-account-addresses",
      url: `${base}/account/address`,
      prepare: ready(".address-manager-list-base"),
    },
    { name: "storefront-account-orders", url: `${base}/account/order`, prepare: ready(".account-orders") },
    admin("admin-dashboard", "/sw/dashboard/index", ".sw-dashboard-index"),
    admin("admin-product-list", "/sw/product/index", ".sw-product-list .sw-data-grid__row"),
    admin("admin-product-detail", `/sw/product/detail/${product}/base`, ".sw-product-detail .mt-card", null, (view) =>
      expect(view).toHaveTitle(new RegExp(SHOWCASE.products[0].name), { timeout: resolveTimeout(30_000) }),
    ),
    admin("admin-order-list", "/sw/order/index", ".sw-order-list"),
    admin("admin-customer-list", "/sw/customer/index", ".sw-customer-list .sw-data-grid__row"),
    admin("admin-category", "/sw/category/index", ".sw-page.sw-category"),
    admin("admin-media", "/sw/media/index", ".sw-media-index"),
    admin("admin-settings", "/sw/settings/index/shop", ".sw-settings-index"),
    admin("admin-basic-information", "/sw/settings/basic/information/index", ".sw-settings-basic-information"),
    admin("admin-shipping", "/sw/settings/shipping/index", ".sw-settings-shipping-list .sw-data-grid__row"),
    admin("admin-tax", "/sw/settings/tax/index", ".sw-settings-tax-list .sw-data-grid__row"),
    admin("admin-users", "/sw/users/permissions/index", ".sw-users-permissions .sw-data-grid__row"),
    admin("admin-profile", "/sw/profile/index/general", ".sw-profile-index"),
    admin("admin-flow", "/sw/flow/index/flows", ".sw-flow-list-index .sw-data-grid__row"),
    admin("admin-theme-detail", `/sw/theme/manager/detail/${theme.id}`, ".sw-theme-manager-detail"),
    admin("admin-sales-channel", `/sw/sales/channel/detail/${channel.id}/base`, ".sw-sales-channel-detail"),
    admin("admin-user-menu-open", "/sw/dashboard/index", ".sw-dashboard-index", async (view) => {
      if (view.viewportSize().width <= 500) return;
      await view.locator(".sw-admin-menu__user-actions-toggle").click();
      await ready(".sw-admin-menu__user-actions.is--active")(view);
    }),
    admin("admin-menu-entry-expanded", "/sw/dashboard/index", ".sw-dashboard-index", async (view) => {
      if (view.viewportSize().width <= 500) return;
      await view.locator(".sw-admin-menu__navigation-list-item.sw-catalogue > .sw-admin-menu__navigation-link").click();
      await ready(".sw-admin-menu__navigation-list-item.is--entry-expanded")(view);
    }),
  ];

  return { guestViews, views };
}

async function galleryContexts(page, browser, request) {
  const seeded = await seedShowcase(request);
  const guest = await browser.newContext({ ignoreHTTPSErrors: true });
  const guestPage = await guest.newPage();
  await declineOptionalCookies(guestPage);
  await signIn(page);
  await dismissFirstRunWizard(page);
  await declineOptionalCookies(page);
  await signInCustomer(page);
  await gotoOnion(page, `${base}/detail/${SHOWCASE.products[0].id}`);
  return { ...galleryViews({ ...seeded, productUrl: page.url() }), guest, guestPage };
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await openStorefront(page, "/", "main.content-main");
  await assertDesignTokens(page, "shopware storefront");
});

test("design: the storefront takes surface, text, buy button and dividers from the tokens", async ({
  page,
  request,
}) => {
  skipUnlessServiceEnabled("design");
  await seedShowcase(request);
  await openStorefront(page, `/detail/${SHOWCASE.products[0].id}`, ".btn-buy");
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "body", "background-color", "--design-surface-1", `storefront ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `storefront ${mode}`);
    await assertToken(page, ".btn-buy", "background-color", "--design-primary", `storefront ${mode}`);
    await assertToken(page, ".btn-buy", "color", "--design-on-primary", `storefront ${mode}`);
    await assertToken(page, ".footer-main", "border-top-color", "--design-border", `storefront ${mode}`);
    await assertToken(page, ".header-search-input", "border-top-color", "--design-border-strong", `storefront ${mode}`);
  }
  await openStorefront(page, "/account/login", "form.login-form");
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, "main.content-main h1", "color", "--design-text", `storefront heading ${mode}`);
    await assertToken(page, ".login-card .card-title", "border-bottom-color", "--design-border", `storefront ${mode}`);
  }
  expect(
    await page.locator(".login-card").evaluate((card) => {
      const style = getComputedStyle(card);
      return `${style.backgroundColor} ${style.borderTopColor} ${style.boxShadow}`;
    }),
    "Shopware's cards carry no padding, so they stay flat: no fill, no border, no shadow",
  ).toBe("rgba(0, 0, 0, 0) rgba(0, 0, 0, 0) none");
  await openStorefront(page, "/", ".product-box");
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, ".product-box", "background-color", "--design-surface-2", `storefront product box ${mode}`);
    await assertToken(page, ".product-box", "border-top-color", "--design-border", `storefront product box ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: storefront text stays readable in light and dark mode", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  await seedShowcase(request);
  await openStorefront(page, `/detail/${SHOWCASE.products[0].id}`, ".btn-buy");
  await assertLightAndDark(page, "main.content-main", "shopware storefront");
  await assertReadable(
    page,
    [
      "main.content-main h1",
      ".product-detail-price",
      ".btn-buy",
      { selector: ".footer-link", optional: true },
      { selector: ".footer-column-headline", optional: true },
      { selector: ".header-cart-total", optional: true },
    ],
    "shopware storefront",
  );
});

test("design: the secondary button of the cart drawer stays a quiet surface", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  await seedShowcase(request);
  await openStorefront(page, `/detail/${SHOWCASE.products[0].id}`, ".btn-buy");
  await page.locator(".btn-buy").first().click({ timeout: resolveTimeout(30_000) });
  const close = ".offcanvas.show .offcanvas-close.btn-secondary";
  await expect(page.locator(close)).toBeVisible({ timeout: resolveTimeout(30_000) });
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, close, "background-color", "--design-surface-3", `secondary button ${mode}`);
    await assertToken(page, close, "color", "--design-text", `secondary button ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: the Storefront theme configuration holds the light palette", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  const theme = await storefrontTheme(request, await adminToken(request));
  await openStorefront(page, "/", "main.content-main");
  await page.emulateMedia({ colorScheme: "light" });
  for (const [field, token] of THEME_FIELDS) {
    expect(
      hexToRgb(String(theme.configValues?.[field]?.value)),
      `theme field ${field} must hold the light value of ${token}`,
    ).toBe(await tokenValue(page, token, "color"));
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: the compiled Storefront theme carries the light palette without the injected sheets", async ({
  page,
  request,
}) => {
  skipUnlessServiceEnabled("design");
  await seedShowcase(request);
  await openStorefront(page, `/detail/${SHOWCASE.products[0].id}`, ".btn-buy");
  await page.emulateMedia({ colorScheme: "light" });
  const expected = {
    primary: await tokenValue(page, "--design-primary", "color"),
    surface: await tokenValue(page, "--design-surface-1", "color"),
    text: await tokenValue(page, "--design-text", "color"),
  };
  const disabled = await page.evaluate((pattern) => {
    const injected = [...document.styleSheets].filter((sheet) => new RegExp(pattern).test(sheet.href || ""));
    for (const sheet of injected) sheet.disabled = true;
    return injected.length;
  }, INJECTED_SHEET.source);
  expect(disabled, "the injected design sheets must be found before they are switched off").toBeGreaterThan(1);
  const compiled = await page.evaluate(() => ({
    primary: getComputedStyle(document.querySelector(".btn-buy")).backgroundColor,
    surface: getComputedStyle(document.body).backgroundColor,
    text: getComputedStyle(document.body).color,
  }));
  expect(compiled, "theme:compile must have baked the corporate values into the Storefront stylesheet").toEqual(
    expected,
  );
  await page.emulateMedia({ colorScheme: null });
});

test("design: the storefront shows the configured logo, favicon and shop name", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await openStorefront(page, "/account/login", "form.login-form");
  const logo = page.locator("img.header-logo-main-img");
  await expect(logo).toHaveAttribute("src", designLogoUrl);
  await expect
    .poll(() => logo.evaluate((image) => image.naturalWidth), { message: "the storefront logo must load" })
    .toBeGreaterThan(0);
  const box = await logo.boundingBox();
  expect(box.width, "the storefront logo is a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
    "href",
    designLogoUrl.replace(/logo\.svg$/, "favicon.png"),
  );
  expect(await page.title(), "the page title carries the shop name of the design").toContain(designTitle);
});

test("design: the administration maps its tokens and keeps the menu on the frame", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(240_000));
  await seedShowcase(request);
  await openAdmin(page, "/sw/product/index", ".sw-product-list .sw-data-grid__row");
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, ".sw-admin-menu", "background-color", "--design-frame", `administration ${mode}`);
    await assertToken(page, ".sw-admin-menu__navigation-link", "color", "--design-on-frame", `administration ${mode}`);
    await assertToken(page, ".mt-button--primary", "background-color", "--design-primary", `administration ${mode}`);
    await assertToken(page, ".mt-button--primary", "color", "--design-on-primary", `administration ${mode}`);
    await assertToken(page, ".smart-bar__header", "color", "--design-text", `administration ${mode}`);
    await assertToken(page, ".sw-page__head-area", "background-color", "--design-surface-2", `administration ${mode}`);
    await assertToken(page, ".sw-page__head-area", "border-bottom-color", "--design-border", `administration ${mode}`);
    await assertToken(
      page,
      ".sw-data-grid__body .sw-data-grid__cell:not(.sw-data-grid__cell--selection)",
      "border-right-color",
      "--design-border",
      `administration grid divider ${mode}`,
    );
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ".sw-page__head-area", "shopware administration");
  await assertReadable(
    page,
    [
      ".smart-bar__header",
      ".sw-admin-menu__navigation-link",
      ".mt-button--primary",
      ".sw-data-grid__cell-content",
      ".sw-version__title",
    ],
    "shopware administration",
  );
  expect(
    await page.locator(".sw-admin-menu__header-logo").evaluate((element) => getComputedStyle(element).backgroundImage),
    "the menu shows the corporate logo",
  ).toContain(designMenuLogoUrl);
});

test("design: focus stops inside the administration menu draw in the frame text color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(240_000));
  await openAdmin(page, "/sw/dashboard/index", ".sw-dashboard-index");
  const onFrame = await tokenValue(page, "--design-on-frame", "color");
  await page.locator(".sw-admin-menu__navigation-link").first().focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  const stops = [];
  for (let index = 0; index < 16; index += 1) {
    const stop = await page.evaluate(() => {
      const element = document.activeElement;
      const style = getComputedStyle(element);
      return {
        inMenu: element.closest(".sw-admin-menu") !== null,
        name: `${element.tagName.toLowerCase()}.${element.className.toString().split(" ")[0]}`,
        outline: `${style.outlineStyle} ${style.outlineColor}`,
        ring: style.boxShadow,
      };
    });
    if (!stop.inMenu) break;
    stops.push(stop);
    await page.keyboard.press("Tab");
  }
  expect(stops.length, "the Tab walk must visit the menu entries").toBeGreaterThan(8);
  expect(new Set(stops.map((stop) => stop.name)).size, "the Tab walk must reach buttons besides the links").toBeGreaterThan(2);
  for (const stop of stops) {
    expect(stop.outline, `${stop.name} outlines its focus in --design-on-frame`).toBe(`solid ${onFrame}`);
    expect(stop.ring, `${stop.name} draws no page-colored focus ring on the frame`).toBe("none");
  }
});

test("design: the administration sign-in page sits on the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}/admin#/login`);
  await expect(page.locator(".sw-login__content input[type='password']")).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  for (const mode of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: mode });
    await assertToken(page, ".sw-login", "background-color", "--design-surface-3", `sign-in ${mode}`);
    await assertToken(page, ".sw-login__container", "background-color", "--design-surface-2", `sign-in ${mode}`);
    await assertToken(page, ".sw-login__image", "background-color", "--design-frame", `sign-in ${mode}`);
    await assertToken(page, ".sw-login__content-headline", "color", "--design-text", `sign-in ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  const badge = await page.locator(".sw-login__badge").evaluate((element) => getComputedStyle(element).backgroundImage);
  expect(badge, "the sign-in badge shows the corporate logo").toContain(designMenuLogoUrl);
  expect(
    await page.locator(".sw-login__image").evaluate((element) => getComputedStyle(element).backgroundImage),
    "the sign-in panel loads no vendor photo",
  ).toBe("none");
});

test("design: gallery of storefront and administration", async ({ page, browser, request }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(3_600_000));

  const { guestViews, views, guest, guestPage } = await galleryContexts(page, browser, request);
  const failures = [];
  for (const [target, group] of [
    [guestPage, guestViews],
    [page, views],
  ]) {
    await captureDesignGallery(target, group).catch((error) => failures.push(error.message));
  }
  await guest.close();
  expect(failures, failures.join("\n")).toEqual([]);
});
