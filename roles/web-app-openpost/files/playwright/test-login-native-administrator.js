const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: break-glass password login reaches the instance administration", async ({ page }) => {
    test.setTimeout(resolveTimeout(90_000)); // cold SvelteKit bundle plus the instance settings fetch
    expect(shared.env.breakglassEmail, "BREAKGLASS_EMAIL must be set").toBeTruthy();
    expect(shared.env.breakglassPassword, "BREAKGLASS_PASSWORD must be set").toBeTruthy();

    await shared.signInViaLocal(page, shared.env.breakglassEmail, shared.env.breakglassPassword, "administrator-native");
    await shared.openInstanceAdministration(page, "administrator-native");
    await shared.logout(page, "administrator-native");
  });
};
