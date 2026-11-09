const { test, expect } = require("@playwright/test");

const { SECOND_FACTOR, TWO_FACTOR_SKIP, adminPasswordSignIn, adminSignIn, twoFactorEnabled } = require("./admin");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const DASHBOARD = "body.adminhtml-dashboard-index .dashboard-container";

test("the administrator signs in with the password and reaches the dashboard", async ({ page }) => {
  test.skip(twoFactorEnabled(), TWO_FACTOR_SKIP);
  test.setTimeout(resolveTimeout(240_000));

  await adminSignIn(page);

  await expect(
    page.locator(DASHBOARD),
    "with two-factor authentication switched off the password alone must end on the admin dashboard",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
});

test("the admin asks for a second factor after the password", async ({ page }) => {
  skipUnlessServiceEnabled("two_factor");
  test.setTimeout(resolveTimeout(240_000));

  expect(
    await adminPasswordSignIn(page),
    "with two-factor authentication switched on the password alone must not open the admin",
  ).toBe(SECOND_FACTOR);
  await expect(page.locator(DASHBOARD), "the dashboard stays closed without the second factor").toHaveCount(0);
  expect(new URL(page.url()).pathname, "the password sign-in lands on a page of Magento's two-factor module").toMatch(/\/tfa\//);
});
