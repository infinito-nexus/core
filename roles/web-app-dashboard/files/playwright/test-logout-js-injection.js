const { test, expect } = require("./fixtures/onion-test");

const {
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");

const cdnBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.CDN_BASE_URL, "CDN_BASE_URL"));
const sharedJsPrefix = `${cdnBaseUrl.replace(/\/$/, "")}/_shared/js`;

exports.register = function (shared) {
  test("dashboard injects logout.js when logout service is enabled", async ({ page }) => {
    shared.skipUnlessServiceEnabled("logout");

    const diagnostics = shared.attachDiagnostics(page);
    const documentResponse = await gotoOnion(page,"/");
    expect(documentResponse.status()).toBeLessThan(400);

    const documentHtml = await documentResponse.text();
    await shared.waitForDashboardReady(page);
    await shared.waitForResourceResponse(diagnostics.responses, "/_shared/js/logout.js", "logout injector script");

    expect(documentHtml).toContain(`${sharedJsPrefix}/logout.js`);
  });
};
