const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { signInToAdministrator } = require("./joomla-session");

const base = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

const ACTION = { timeout: resolveTimeout(30_000) };

test.use({ ignoreHTTPSErrors: true });

test("administrator: plg_authentication_ldap stays disabled while the ldap service is off", async ({ page }) => {
  skipUnlessServiceDisabled("ldap");
  test.setTimeout(resolveTimeout(120_000));
  expect(base, "JOOMLA_BASE_URL must be set").toBeTruthy();

  await signInToAdministrator(page, base, adminUsername, adminPassword);
  await gotoOnion(page, `${base}/administrator/index.php?option=com_plugins&view=plugins`);
  const search = page.locator("form#adminForm #filter_search");
  await expect(search, "Extensions: Plugins must offer its search box").toBeEditable(ACTION);
  await search.fill("LDAP");
  await search.press("Enter");

  const row = page
    .locator("#pluginList tbody tr")
    .filter({ hasText: /Authentication\s*-\s*LDAP/i })
    .first();
  await expect(row, "Extensions: Plugins must list the core LDAP authentication plugin").toBeVisible(ACTION);
  await expect(
    row.locator(".tbody-icon [class~='icon-unpublish']"),
    "tasks/10_ldap.yml must leave plg_authentication_ldap disabled when the ldap service is off",
  ).toBeVisible(ACTION);
  await expect(row.locator(".tbody-icon [class~='icon-publish']")).toHaveCount(0);
});
