const crypto = require("node:crypto");

const { expect } = require("@playwright/test");

const { USAGE_NOTICE, adminSignIn, hideUsageNotice } = require("./admin");
const { apiFetchOnion, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const adminNativePassword = requireDotenvValue(process.env.ADMIN_NATIVE_PASSWORD, "ADMIN_NATIVE_PASSWORD");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");

const ADMIN_MENU = ".menu-wrapper #nav";
const ADMIN_BUSY = [
  ".admin__data-grid-loading-mask",
  ".admin__form-loading-mask",
  ".loading-mask",
  ".popup-loading",
]
  .map((selector) => `${selector}:visible`)
  .join(", ");
const SIGN_IN_FORM = ".block-customer-login form.form-login[novalidate]";

const SHOWCASE = {
  category: "Design showcase",
  categoryPath: "/design-showcase.html",
  productPath: "/design-showcase-lamp.html",
  products: [
    { sku: "DESIGN-1", name: "Design showcase lamp", price: 119 },
    { sku: "DESIGN-2", name: "Design showcase chair", price: 238 },
    { sku: "DESIGN-3", name: "Design showcase table", price: 476 },
  ],
  customer: {
    email: `design-showcase@${canonicalDomain}`,
    password: `Dx1!${crypto.randomBytes(21).toString("hex")}`,
    firstname: "Design",
    lastname: "Showcase",
  },
  address: { street: ["Showcase 1"], city: "Berlin", postcode: "10115", country: "DE", telephone: "0300000000" },
};

async function rest(request, token, method, path, data, store = "all") {
  const response = await apiFetchOnion(request, `${base}/rest/${store}/V1${path}`, {
    method,
    headers: { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    data,
    timeout: resolveTimeout(180_000),
  });
  return { status: response.status(), body: await response.json().catch(() => null) };
}

function answered(answer, what) {
  expect(answer.status, `${what}: ${JSON.stringify(answer.body && answer.body.message)}`).toBe(200);
  return answer.body;
}

function filter(field, value) {
  return (
    `searchCriteria[filterGroups][0][filters][0][field]=${field}` +
    `&searchCriteria[filterGroups][0][filters][0][value]=${encodeURIComponent(value)}&searchCriteria[pageSize]=1`
  );
}

async function adminToken(request) {
  return answered(
    await rest(request, null, "POST", "/integration/admin/token", {
      username: adminUsername,
      password: adminNativePassword,
    }),
    "the administrator's API token",
  );
}

async function customerToken(request) {
  const answer = await rest(request, null, "POST", "/integration/customer/token", {
    username: SHOWCASE.customer.email,
    password: SHOWCASE.customer.password,
  });
  return answer.status === 200 ? answer.body : null;
}

async function ensureCustomer(request, admin) {
  const { email, password, firstname, lastname } = SHOWCASE.customer;
  const { street, city, postcode, country, telephone } = SHOWCASE.address;
  const found = answered(await rest(request, admin, "GET", `/customers/search?${filter("email", email)}`), "the customer search");
  if (found.items[0]) {
    const salt = crypto.randomBytes(16).toString("hex");
    const passwordHash = `${crypto.createHash("sha256").update(`${salt}${password}`).digest("hex")}:${salt}:1`;
    answered(
      await rest(request, admin, "PUT", `/customers/${found.items[0].id}`, { customer: found.items[0], passwordHash }),
      "the new password of the showcase customer",
    );
  } else {
    answered(
      await rest(
        request,
        null,
        "POST",
        "/customers",
        {
          customer: {
            email,
            firstname,
            lastname,
            addresses: [
              { firstname, lastname, street, city, postcode, countryId: country, telephone, defaultShipping: true, defaultBilling: true },
            ],
          },
          password,
        },
        "default",
      ),
      "the showcase customer",
    );
  }
  const token = await customerToken(request);
  expect(token, "the showcase customer signs in with the password of this run").toBeTruthy();
  return token;
}

async function ensureCatalog(request, admin) {
  const found = answered(await rest(request, admin, "GET", `/categories/list?${filter("name", SHOWCASE.category)}`), "the category search");
  const category =
    found.items[0] ||
    answered(
      await rest(request, admin, "POST", "/categories", {
        category: { parent_id: 2, name: SHOWCASE.category, is_active: true, include_in_menu: true },
      }),
      "the showcase category",
    );
  for (const product of SHOWCASE.products) {
    const existing = await rest(request, admin, "GET", `/products/${product.sku}`);
    if (existing.status === 200) continue;
    answered(
      await rest(request, admin, "POST", "/products", {
        product: {
          sku: product.sku,
          name: product.name,
          price: product.price,
          status: 1,
          visibility: 4,
          type_id: "simple",
          attribute_set_id: 4,
          weight: 1,
          extension_attributes: {
            website_ids: [1],
            category_links: [{ position: 0, category_id: String(category.id) }],
            stock_item: { qty: 250, is_in_stock: true },
          },
          custom_attributes: [
            { attribute_code: "description", value: "<p>Seeded by the design tests of the platform.</p>" },
            { attribute_code: "short_description", value: "A showcase product." },
          ],
        },
      }),
      `the showcase product ${product.sku}`,
    );
  }
}

function quoteAddress() {
  const { email, firstname, lastname } = SHOWCASE.customer;
  const { street, city, postcode, country, telephone } = SHOWCASE.address;
  return { email, firstname, lastname, street, city, postcode, country_id: country, telephone };
}

async function ensureCartItem(request, customer, sku) {
  const cart = await rest(request, customer, "GET", "/carts/mine", undefined, "default");
  if (cart.status === 200 && cart.body.items_count > 0) return;
  const quoteId = answered(await rest(request, customer, "POST", "/carts/mine", undefined, "default"), "the showcase cart");
  answered(
    await rest(request, customer, "POST", "/carts/mine/items", { cartItem: { sku, qty: 1, quote_id: String(quoteId) } }, "default"),
    "the showcase cart item (a product that is not available has not been indexed: the indexers run by schedule and need Magento's cron or bin/magento indexer:reindex)",
  );
}

async function ensureOrder(request, admin, customer) {
  const orders = answered(
    await rest(request, admin, "GET", `/orders?${filter("customer_email", SHOWCASE.customer.email)}`),
    "the order search",
  );
  if (orders.total_count > 0) return;
  await ensureCartItem(request, customer, SHOWCASE.products[1].sku);
  answered(
    await rest(
      request,
      customer,
      "POST",
      "/carts/mine/shipping-information",
      {
        addressInformation: {
          shipping_address: quoteAddress(),
          billing_address: quoteAddress(),
          shipping_carrier_code: "flatrate",
          shipping_method_code: "flatrate",
        },
      },
      "default",
    ),
    "the showcase shipping information",
  );
  answered(
    await rest(
      request,
      customer,
      "POST",
      "/carts/mine/payment-information",
      { paymentMethod: { method: "checkmo" }, billing_address: quoteAddress() },
      "default",
    ),
    "the showcase order",
  );
}

/**
 * Args:
 *   page: Playwright page that already passed the front proxy, its request context carries the cookies.
 *
 * Creates what is missing of: the showcase customer with an address, one category with three products, one order and one cart item.
 */
async function seedShowcase(page) {
  const admin = await adminToken(page.request);
  const customer = await ensureCustomer(page.request, admin);
  await ensureCatalog(page.request, admin);
  await ensureOrder(page.request, admin, customer);
  await ensureCartItem(page.request, customer, SHOWCASE.products[0].sku);
}

/**
 * Args:
 *   page: Playwright page.
 *   path: storefront path below the base URL.
 *   ready: selector that marks the loaded page.
 */
async function openShop(page, path, ready) {
  await gotoOnion(page, `${base}${path}`);
  if (page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
    await gotoOnion(page, `${base}${path}`);
  }
  await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(120_000) });
}

async function customerSignIn(page) {
  const form = page.locator(SIGN_IN_FORM);
  const password = form.locator("input[name='login[password]']");
  await openShop(page, "/customer/account/login/", SIGN_IN_FORM);
  await form.locator("input[name='login[username]']").fill(SHOWCASE.customer.email);
  // A fill that times out prints its value into the call log, so the field has to be editable first.
  await expect(password).toBeEditable({ timeout: resolveTimeout(60_000) });
  await password.fill(SHOWCASE.customer.password);
  await form.locator("button.action.login").click();
  await expect(
    page.locator(".block-dashboard-info"),
    "the showcase customer reaches the account page through the storefront sign-in form",
  ).toBeVisible({ timeout: resolveTimeout(120_000) });
  // Magento keeps the sections a guest loaded for an hour; without them the next page loads the customer's cart.
  await page.evaluate(() => localStorage.removeItem("mage-cache-storage"));
}

async function adminIdle(page) {
  await expect(page.locator(ADMIN_BUSY)).toHaveCount(0, { timeout: resolveTimeout(120_000) });
}

function adminNavigator() {
  const links = new Map();

  async function refresh(page) {
    await gotoOnion(page, `${base}/admin`);
    if (!page.url().includes("openid-connect/auth")) {
      await expect(page.locator(`${ADMIN_MENU}, #login-form`).first()).toBeVisible({ timeout: resolveTimeout(120_000) });
    }
    if (!(await page.locator(ADMIN_MENU).isVisible())) await adminSignIn(page);
    const entries = await page
      .locator(`${ADMIN_MENU} li[data-ui-id] > a[href]`)
      .evaluateAll((anchors) => anchors.map((anchor) => [anchor.parentElement.getAttribute("data-ui-id"), anchor.href]));
    links.clear();
    for (const [id, href] of entries) links.set(id, href);
  }

  /**
   * Args:
   *   page: Playwright page.
   *   entry: data-ui-id of the menu entry whose page is opened.
   *   ready: selector that marks the loaded page.
   */
  async function open(page, entry, ready) {
    if (links.has(entry)) {
      await gotoOnion(page, links.get(entry));
      await expect(
        page.locator(`${ready}, #login-form, body.adminhtml-dashboard-index .dashboard-container`).first(),
      ).toBeVisible({ timeout: resolveTimeout(120_000) });
    }
    if (!links.has(entry) || !(await page.locator(ready).first().isVisible())) {
      await refresh(page);
      expect(links.has(entry), `the admin menu holds the entry ${entry}`).toBe(true);
      await gotoOnion(page, links.get(entry));
    }
    await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(120_000) });
    await adminIdle(page);
  }

  /**
   * Args:
   *   page: Playwright page.
   *   entry: data-ui-id of the menu entry whose page holds the link.
   *   listed: selector that marks the loaded list page.
   *   link: selector of the anchor to follow.
   *   ready: selector that marks the loaded target page.
   */
  async function openLinked(page, entry, listed, link, ready) {
    await open(page, entry, listed);
    const href = await page.locator(link).first().evaluate((anchor) => anchor.href);
    await gotoOnion(page, href);
    await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(120_000) });
    await adminIdle(page);
  }

  return { open, openLinked };
}

module.exports = {
  ADMIN_MENU,
  SHOWCASE,
  SIGN_IN_FORM,
  USAGE_NOTICE,
  adminIdle,
  adminNavigator,
  base,
  customerSignIn,
  hideUsageNotice,
  openShop,
  seedShowcase,
};
