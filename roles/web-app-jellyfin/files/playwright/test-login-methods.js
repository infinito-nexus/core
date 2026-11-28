const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const SSO_ENTRY = "#loginPage .loginDisclaimer .button-submit";
const FORM_ENTRIES = [
  "#loginPage .manualLoginForm",
  "#loginPage .visualLoginForm",
  "#loginPage .btnManual",
  "#loginPage .btnQuick",
  "#loginPage .btnForgotPassword",
];

exports.register = function (shared) {
  test("login methods: with SSO on the sign-in page offers the SSO entry and none of the disabled ones", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(60_000));
    await shared.gotoLogin(page);

    if (shared.env.loginMethodSso) {
      await expect(page.locator(SSO_ENTRY), "the SSO entry must render on the Jellyfin sign-in page").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
    }
    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              !document.querySelector("#loginPage .manualLoginForm")?.classList.contains("hide") ||
              (document.querySelector("#loginPage #divUsers")?.children.length || 0) > 0,
          ),
        {
          timeout: resolveTimeout(30_000),
          message: "the Jellyfin sign-in page must have chosen between the user picker and the form",
        },
      )
      .toBe(true);

    if (!shared.env.loginFormShown) {
      for (const selector of FORM_ENTRIES) {
        await expect(page.locator(selector), `${selector} must stay hidden while native and LDAP sign-in are off`).toBeHidden({
          timeout: resolveTimeout(30_000),
        });
      }
    }
  });
};
