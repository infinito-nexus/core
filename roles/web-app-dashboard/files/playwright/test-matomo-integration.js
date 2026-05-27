const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("dashboard integrates matomo tracking assets", async ({ page }) => {
    shared.skipUnlessServiceEnabled("matomo");

    const diagnostics = shared.attachDiagnostics(page);
    const documentResponse = await page.goto("/");

    expect(documentResponse, "Expected the dashboard document response to exist").toBeTruthy();
    expect(documentResponse.status(), "Expected the dashboard document response to be successful").toBeLessThan(400);

    const documentHtml = await documentResponse.text();

    await shared.waitForDashboardReady(page);
    await shared.waitForResourceResponse(diagnostics.responses, `${shared.env.matomoBaseUrl}/matomo.js`, "Matomo tracking script");

    expect(documentHtml).toContain("matomo.js");
    expect(documentHtml).toContain("matomo.php?idsite=");
  });
};
