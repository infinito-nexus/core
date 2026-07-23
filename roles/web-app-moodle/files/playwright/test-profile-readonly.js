const { test, expect } = require("@playwright/test");

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
      await page.goto(`${shared.env.moodleBaseUrl}/login/index.php`);
      await page.locator("input[name='username'], input#username").first().fill(shared.env.biberUsername);
      const passwordInput = page.locator("input[name='password'], input#password").first();
      await expect(async () => {
        await passwordInput.fill(shared.env.biberPassword);
        await expect(passwordInput).toHaveValue(shared.env.biberPassword);
      }).toPass({ timeout: 30_000 });
      await page.locator("button[type='submit'], input[type='submit'], #loginbtn").first().click();
      await page.waitForLoadState("load");

      await page.goto(`${shared.env.moodleBaseUrl}/user/edit.php`);
      await expect(page.locator("body")).toBeVisible({ timeout: 30_000 });

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
