const { test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("biber: app → keycloak → join Jitsi room → logout", async ({ page }) => {
    test.setTimeout(resolveTimeout(180_000));
    await shared.runBiberFlow(page, {
      biberInteraction: async (p) => {
        await shared.reachJitsiPrejoin(p, "biber", "biber-room");
      },
    });
  });
};
