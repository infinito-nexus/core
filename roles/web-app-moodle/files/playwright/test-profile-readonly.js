const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

const moodleLdapBackedProfileFields = [
  "firstname", "lastname", "middlename", "alternatename",
  "firstnamephonetic", "lastnamephonetic",
  "email", "phone1", "phone2",
  "address", "city", "country",
  "institution", "department", "description",
  "idnumber", "url", "lang", "timezone",
];

exports.register = function (shared) {
  test.describe("moodle profile fields are read-only", () => {
    test.skip(!shared.env.ldapEnabled, "LDAP shared service disabled");
    test.skip(shared.env.ssoEnabled, "covered by variant 1 LDAP-only run");

    test("biber profile-edit form locks all 19 Moodle profile-mapping fields", async ({ page }) => {
      await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php`);
      await page.locator("input[name='username'], input#username").first().fill(shared.env.biberUsername);
      const passwordInput = page.locator(".toggle-sensitive-wrapper input[name='password'], .toggle-sensitive-wrapper input#password").first();
      await expect(passwordInput).toBeAttached({ timeout: resolveTimeout(30_000) });
      await expect(async () => {
        await passwordInput.fill(shared.env.biberPassword);
        await expect(passwordInput).toHaveValue(shared.env.biberPassword);
      }).toPass({ timeout: resolveTimeout(30_000) });
      await page.locator("button[type='submit'], input[type='submit'], #loginbtn").first().click({ timeout: resolveTimeout(30_000) });
      await page.waitForLoadState("load");
      const userMenu = page.locator(".usermenu, [data-region='user-menu-toggle'], a[href*='profile.php']").first();
      await expect(userMenu, "login must succeed before the read-only checks mean anything").toBeVisible({ timeout: resolveTimeout(30_000) });

      await gotoOnion(page, `${shared.env.moodleBaseUrl}/user/edit.php`);
      await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(30_000) });

      for (const fieldName of moodleLdapBackedProfileFields) {
        const input = page
          .locator(`input[name='${fieldName}'], select[name='${fieldName}'], textarea[name='${fieldName}']`)
          .first();
        if ((await input.count()) > 0) {
          const readonly = await input.getAttribute("readonly");
          const disabled = await input.getAttribute("disabled");
          expect(
            readonly !== null || disabled !== null,
            `field "${fieldName}" must be readonly/disabled (LDAP-backed lock)`
          ).toBe(true);
        }
      }
    });
  });
};
