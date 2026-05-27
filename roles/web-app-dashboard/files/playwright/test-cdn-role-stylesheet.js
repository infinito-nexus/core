const { test, expect } = require("@playwright/test");

const { normalizeBaseUrl } = require("./personas");

const cdnBaseUrl = normalizeBaseUrl(process.env.CDN_BASE_URL || "");
const roleCssPrefix = `${cdnBaseUrl.replace(/\/$/, "")}/roles/web-app-dashboard/latest/css`;

exports.register = function (shared) {
  test("dashboard CDN serves role-local stylesheet when cdn service is enabled", async ({ page }) => {
    shared.skipUnlessServiceEnabled("cdn");
    shared.skipUnlessServiceEnabled("asset");
    shared.skipUnlessServiceEnabled("css");

    const diagnostics = shared.attachDiagnostics(page);
    const documentResponse = await page.goto("/");
    expect(documentResponse.status()).toBeLessThan(400);

    const documentHtml = await documentResponse.text();
    await shared.waitForDashboardReady(page);
    await shared.waitForResourceResponse(diagnostics.responses, "/roles/web-app-dashboard/latest/css/style.css", "dashboard role CSS");

    expect(documentHtml).toContain(`${roleCssPrefix}/style.css`);
  });
};
