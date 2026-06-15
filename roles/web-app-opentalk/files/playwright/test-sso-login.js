const { test, expect } = require("@playwright/test");

const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  adminUsername,
  adminPassword,
  biberUsername,
  biberPassword,
  ssoLoginAndAssertDashboard,
} = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("opentalk sso login (administrator) lands on dashboard", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(adminUsername, "LOGIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "LOGIN_PASSWORD must be set").toBeTruthy();

  await ssoLoginAndAssertDashboard(page, adminUsername, adminPassword);
});

test("opentalk sso login (biber) lands on dashboard", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  try {
    await ssoLoginAndAssertDashboard(page, biberUsername, biberPassword);
  } finally {
    await context.close();
  }
});
