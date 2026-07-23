const { test, expect } = require("./fixtures/onion-test");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("dashboard landing renders without unexpected console or page errors", async ({ page }) => {
    const diagnostics = shared.attachDiagnostics(page);
    const documentResponse = await gotoOnion(page,"/");
    expect(documentResponse.status()).toBeLessThan(400);

    await shared.waitForDashboardReady(page);

    shared.expectNoUnexpectedDiagnostics(diagnostics, {
      ignoreMatomoConsoleNoise: true,
    });
  });
};
