const { test, expect } = require("./fixtures/onion-test");

const {
  escapeRegex,
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");

const cdnBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.CDN_BASE_URL, "CDN_BASE_URL"));
const roleCssPrefix = `${cdnBaseUrl.replace(/\/$/, "")}/roles/web-app-dashboard/latest/css`;
const roleSheet = new RegExp(`${escapeRegex(roleCssPrefix)}/(?:[a-z]+-)?style\\.css`);

exports.register = function (shared) {
  test("dashboard CDN serves role-local stylesheet when cdn service is enabled", async ({ page }) => {
    shared.skipUnlessServiceEnabled("cdn");
    shared.skipUnlessServiceEnabled("asset");
    shared.skipUnlessServiceEnabled("design");

    const diagnostics = shared.attachDiagnostics(page);
    const documentResponse = await gotoOnion(page,"/");
    expect(documentResponse.status()).toBeLessThan(400);

    const documentHtml = await documentResponse.text();
    await shared.waitForDashboardReady(page);

    const linked = documentHtml.match(roleSheet);
    expect(linked, `the document links the role stylesheet of its network under ${roleCssPrefix}`).not.toBeNull();
    await shared.waitForResourceResponse(diagnostics.responses, new URL(linked[0]).pathname, "dashboard role CSS");
  });
};
