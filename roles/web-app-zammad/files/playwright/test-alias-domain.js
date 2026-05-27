const { test, expect, request } = require("@playwright/test");

exports.register = function (shared) {
  test("zammad alias domain serves the same vhost (true server-name alias, no 301)", async () => {
    const baseUrl = shared.env.zammadBaseUrl;
    expect(baseUrl, "ZAMMAD_BASE_URL must be set").toBeTruthy();

    const aliasHost = baseUrl
      .replace(/^https?:\/\//, "")
      .replace(/\/$/, "")
      .replace(/^helpdesk\./, "zammad.helpdesk.");

    if (aliasHost === baseUrl.replace(/^https?:\/\//, "").replace(/\/$/, "")) {
      test.skip(true, "Alias hostname matches the canonical; nothing to assert.");
    }

    const aliasUrl = baseUrl.replace(/\/\/[^/]+/, `//${aliasHost}`);
    const api = await request.newContext({ ignoreHTTPSErrors: true, maxRedirects: 0 });

    const aliasResp = await api.get(aliasUrl, { maxRedirects: 0 }).catch((err) => err);
    expect(
      aliasResp.status && aliasResp.status() < 300,
      `Expected alias ${aliasUrl} to serve a 2xx response directly (true vhost alias, NOT 30x redirect). Got: ${aliasResp.status?.() ?? aliasResp.message}`
    ).toBe(true);

    await api.dispose();
  });
};
