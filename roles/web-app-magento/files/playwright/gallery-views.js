const { expect } = require("@playwright/test");

const { gotoOnion } = require("./personas");
const { SHOWCASE, SIGN_IN_FORM, USAGE_NOTICE, base, hideUsageNotice } = require("./showcase");
const { resolveTimeout } = require("./timeouts");

const DASHBOARD = "body.adminhtml-dashboard-index .dashboard-container";
const GRID_ROW = ".admin__data-grid-wrap tbody tr.data-row";
const SHOP_BUSY = ".loading-mask:visible, #checkout-loader:visible, .checkout-loader:visible";
const MENU = {
  dashboard: "menu-magento-backend-dashboard",
  products: "menu-magento-catalog-catalog-products",
  categories: "menu-magento-catalog-catalog-categories",
  orders: "menu-magento-sales-sales-order",
  customers: "menu-magento-customer-customer-manage",
  pages: "menu-magento-cms-cms-page",
  designConfiguration: "menu-magento-theme-design-config",
  configuration: "menu-magento-config-system-config",
  cache: "menu-magento-backend-system-cache",
  users: "menu-magento-user-system-acl-users",
};

async function settled(page, selector) {
  const panel = page.locator(selector).first();
  await expect(panel).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect
    .poll(
      () =>
        panel.evaluate(
          (element) =>
            element.getAnimations({ subtree: true }).every((animation) => animation.playState !== "running") &&
            getComputedStyle(element).opacity === "1",
        ),
      { timeout: resolveTimeout(30_000) },
    )
    .toBe(true);
}

function shopView(name, path, ready, prepare) {
  return {
    name,
    url: `${base}${path}`,
    prepare: async (view) => {
      const loaded = () => expect(view.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(45_000) });
      await loaded().catch(async () => {
        await gotoOnion(view, "about:blank");
        await gotoOnion(view, `${base}${path}`);
        await loaded();
      });
      await expect(view.locator(SHOP_BUSY)).toHaveCount(0, { timeout: resolveTimeout(120_000) });
      if (prepare) await prepare(view);
    },
  };
}

async function shippingStep(view) {
  await expect(view.locator("#checkout-shipping-method-load input[type='radio']").first()).toBeVisible({
    timeout: resolveTimeout(120_000),
  });
  await expect(view.locator(SHOP_BUSY)).toHaveCount(0, { timeout: resolveTimeout(120_000) });
}

async function paymentStep(view) {
  await shippingStep(view);
  await view.locator("#checkout-shipping-method-load input[type='radio']").first().check();
  await view.locator("#shipping-method-buttons-container button.continue").click();
  await expect(view.locator("#checkout-payment-method-load .payment-method").first()).toBeVisible({
    timeout: resolveTimeout(120_000),
  });
  await expect(view.locator(SHOP_BUSY)).toHaveCount(0, { timeout: resolveTimeout(120_000) });
}

async function openMiniCart(view) {
  await expect(view.locator(".minicart-wrapper .mage-dropdown-dialog")).toHaveCount(1, { timeout: resolveTimeout(60_000) });
  await expect(view.locator(".minicart-wrapper .counter.qty:not(.empty)")).toBeVisible({ timeout: resolveTimeout(60_000) });
  await view.locator(".minicart-wrapper .action.showcart").click();
  await settled(view, ".block-minicart .minicart-items .product-item");
}

async function openNavigation(view) {
  const toggle = view.locator(".nav-toggle");
  await expect(view.locator(".navigation ul.ui-menu")).toHaveCount(1, { timeout: resolveTimeout(60_000) });
  if (await toggle.isVisible()) {
    await toggle.click();
    await expect(view.locator("html.nav-open")).toHaveCount(1, { timeout: resolveTimeout(30_000) });
    await settled(view, ".nav-sections");
  } else {
    await view.locator(".navigation .level0 > a").first().hover();
  }
}

function guestViews() {
  return [
    shopView("storefront-home", "/", ".page-footer"),
    shopView("storefront-category", SHOWCASE.categoryPath, ".products-grid .product-item"),
    shopView("storefront-product", SHOWCASE.productPath, "#product-addtocart-button"),
    shopView("storefront-search", "/catalogsearch/result/?q=showcase", ".search.results .product-item"),
    shopView("storefront-sign-in", "/customer/account/login/", SIGN_IN_FORM),
    shopView("storefront-sign-in-invalid", "/customer/account/login/", SIGN_IN_FORM, async (view) => {
      await view.locator(`${SIGN_IN_FORM} button.action.login`).click();
      await expect(view.locator(`${SIGN_IN_FORM} div.mage-error`).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
    }),
    shopView("storefront-register", "/customer/account/create/", "form.form-create-account"),
    shopView("storefront-forgot-password", "/customer/account/forgotpassword/", "form.password.forget"),
    shopView("storefront-contact", "/contact/", "#contact-form"),
    shopView("storefront-not-found", "/design-showcase-missing", ".page-title"),
    shopView("admin-sign-in", "/admin", "#login-form"),
  ];
}

/**
 * Args:
 *   nav: admin navigator of the page that captures the views.
 *   usageNotice: whether the dashboard opens the usage data dialog, which then gets a view of its own.
 */
function memberViews(nav, usageNotice) {
  const admin = (name, open, prepare) => ({
    name,
    url: "about:blank",
    prepare: async (view) => {
      await open(view);
      await hideUsageNotice(view);
      if (prepare) await prepare(view);
    },
  });
  const listed = (name, entry, ready) => admin(name, (view) => nav.open(view, entry, ready));
  const dashboard = (view) => nav.open(view, MENU.dashboard, DASHBOARD);
  const notice = {
    name: "admin-usage-notice",
    url: "about:blank",
    prepare: async (view) => {
      await dashboard(view);
      await settled(view, `${USAGE_NOTICE}._show .modal-inner-wrap`);
    },
  };
  return [
    shopView("storefront-account", "/customer/account/", ".block-dashboard-info"),
    shopView("storefront-account-edit", "/customer/account/edit/", "form.form-edit-account"),
    shopView("storefront-orders", "/sales/order/history/", "#my-orders-table"),
    shopView("storefront-minicart-open", SHOWCASE.productPath, "#product-addtocart-button", openMiniCart),
    shopView("storefront-cart", "/checkout/cart/", "#shopping-cart-table"),
    shopView("storefront-checkout-shipping", "/checkout/", "#checkout-step-shipping", shippingStep),
    shopView("storefront-checkout-payment", "/checkout/", "#checkout-step-shipping", paymentStep),
    shopView("storefront-navigation", "/", ".page-footer", openNavigation),
    admin("admin-dashboard", dashboard),
    ...(usageNotice ? [notice] : []),
    admin("admin-menu-open", dashboard, async (view) => {
      await view.locator("#menu-magento-catalog-catalog > a").click();
      await settled(view, "#menu-magento-catalog-catalog._show > .submenu");
    }),
    listed("admin-products", MENU.products, GRID_ROW),
    admin("admin-product-edit", (view) =>
      nav.openLinked(view, MENU.products, GRID_ROW, `${GRID_ROW} a[href*='/catalog/product/edit/']`, "#save-button"),
    ),
    listed("admin-categories", MENU.categories, ".tree-holder"),
    listed("admin-orders", MENU.orders, GRID_ROW),
    admin("admin-order-view", (view) =>
      nav.openLinked(view, MENU.orders, GRID_ROW, `${GRID_ROW} a[href*='/sales/order/view/']`, ".order-account-information"),
    ),
    listed("admin-customers", MENU.customers, GRID_ROW),
    listed("admin-cms-pages", MENU.pages, GRID_ROW),
    admin(
      "admin-design-configuration",
      (view) =>
        nav.openLinked(
          view,
          MENU.designConfiguration,
          GRID_ROW,
          `${GRID_ROW} a[href*='/theme/design_config/edit/scope/default/']`,
          ".fieldset-wrapper[data-index='header']",
        ),
      async (view) => {
        await view.locator(".fieldset-wrapper[data-index='header'] > .fieldset-wrapper-title").click();
        await settled(view, ".fieldset-wrapper[data-index='header'] [data-index='header_logo_alt']");
      },
    ),
    listed("admin-configuration", MENU.configuration, "#system_config_tabs"),
    listed("admin-cache", MENU.cache, "#cache_grid_table"),
    listed("admin-users", MENU.users, "#permissionsUserGrid_table"),
    admin("admin-user-menu-open", dashboard, async (view) => {
      await view.locator(".admin-user .admin__action-dropdown").click();
      await settled(view, ".admin-user .admin__action-dropdown-menu");
    }),
  ];
}

/**
 * Args:
 *   page: Playwright page.
 *   nav: admin navigator of that page.
 *
 * Returns whether the dashboard opens the usage data dialog for this installation.
 */
async function usageNoticeShows(page, nav) {
  await nav.open(page, MENU.dashboard, DASHBOARD);
  return page
    .locator(`${USAGE_NOTICE}._show`)
    .waitFor({ state: "visible", timeout: resolveTimeout(15_000) })
    .then(() => true)
    .catch(() => false);
}

module.exports = { DASHBOARD, MENU, guestViews, memberViews, usageNoticeShows };
