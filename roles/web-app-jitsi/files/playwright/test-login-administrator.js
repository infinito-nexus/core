const { test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: app → keycloak → settings panel → logout", async ({ page }) => {
    test.setTimeout(resolveTimeout(180_000));
    await shared.runAdminFlow(page, {
      adminInteraction: async (p) => {
        await shared.reachJitsiPrejoin(p, "admin", "admin-room");
        await shared.openJitsiSettingsPanel(p, "administrator");
      },
    });
  });
};
