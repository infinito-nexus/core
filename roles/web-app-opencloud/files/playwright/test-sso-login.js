const { test, expect } = require("@playwright/test");

const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  adminUsername,
  adminPassword,
  biberUsername,
  biberPassword,
  ssoLoginAndAssertUsername,
} = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("opencloud sso login (administrator) lands on files view", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(adminUsername, "LOGIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "LOGIN_PASSWORD must be set").toBeTruthy();

  await ssoLoginAndAssertUsername(page, adminUsername, adminPassword);
});

test("opencloud sso login (biber) lands on files view", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  await ssoLoginAndAssertUsername(page, biberUsername, biberPassword);
});
