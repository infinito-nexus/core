const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("dashboard landing renders without unexpected console or page errors", async ({ page }) => {
    const diagnostics = shared.attachDiagnostics(page);
    const documentResponse = await page.goto("/");
    expect(documentResponse.status()).toBeLessThan(400);

    await shared.waitForDashboardReady(page);

    shared.expectNoUnexpectedDiagnostics(diagnostics, {
      ignoreMatomoConsoleNoise: true,
    });
  });
};
