const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiFetchOnion } = require("./personas");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { expectPdsProxiesAppView } = require("./_appview");

exports.register = function (shared) {
  test("native: PDS proxies Following and Notifications to its configured AppView with an lxm-bound service JWT (no oauth2)", async ({ page }) => {
    skipUnlessServiceDisabled("sso");
    const { adminHandle, adminPassword, pdsBaseUrl } = shared.env;
    expect(adminHandle, "ADMIN_HANDLE must be set when oauth2 is disabled").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set when oauth2 is disabled").toBeTruthy();
    expect(pdsBaseUrl, "PDS_BASE_URL must be set when oauth2 is disabled").toBeTruthy();

    const session = await apiFetchOnion(page.request, `${pdsBaseUrl}/xrpc/com.atproto.server.createSession`, {
      method: "POST",
      data: { identifier: adminHandle, password: adminPassword },
      timeout: resolveTimeout(30_000),
    });
    expect(session.status(), `PDS createSession must return 200 (got body: ${await session.text()})`).toBe(200);
    const { accessJwt } = await session.json();

    await expectPdsProxiesAppView(page.request, pdsBaseUrl, accessJwt);
  });
};
