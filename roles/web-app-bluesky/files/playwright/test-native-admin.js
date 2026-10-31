const { test, expect } = require("@playwright/test");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("native: broker bypassed and PDS createSession accepts the deployed administrator (no oauth2)", async ({ page, playwright }) => {
    test.skip(
      process.env.SSO_SERVICE_ENABLED === "true",
      "Native login path only exists when oauth2 is disabled — when oauth2 is on, the broker owns provisioning and the OIDC test covers the journey.",
    );
    const { baseUrl, adminEmail, adminHandle, adminHandleReserved, adminPassword, pdsBaseUrl } = shared.env;
    expect(adminEmail, "ADMIN_EMAIL must be set when oauth2 is disabled").toBeTruthy();
    expect(adminHandle, "ADMIN_HANDLE must be set when oauth2 is disabled").toBeTruthy();
    expect(adminHandleReserved, "ADMIN_HANDLE_RESERVED must be set when oauth2 is disabled").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set when oauth2 is disabled").toBeTruthy();
    expect(pdsBaseUrl, "PDS_BASE_URL must be set when oauth2 is disabled").toBeTruthy();

    const expectedBaseUrl = baseUrl.replace(/\/$/, "");
    const landing = await gotoOnion(page, `${expectedBaseUrl}/`);
    expect(landing, "Expected bluesky landing response").toBeTruthy();
    const landingBody = await landing.text();
    expect(
      landingBody.includes("Refusing handoff"),
      "broker bypass: the front-proxy MUST NOT route through the login-broker when oauth2 is disabled",
    ).toBe(false);
    expect(
      /<meta name="generator" content="bskyweb">/.test(landingBody),
      "broker bypass: the front-proxy MUST route to the stock social-app (expected the bskyweb generator meta in the landing body)",
    ).toBe(true);

    const apiContext = await playwright.request.newContext({ ignoreHTTPSErrors: true });
    const sessionResp = await apiContext.post(
      `${pdsBaseUrl}/xrpc/com.atproto.server.createSession`,
      {
        headers: { "Content-Type": "application/json" },
        data: { identifier: adminEmail, password: adminPassword },
      },
    );
    const sessionText = await sessionResp.text();
    expect(sessionResp.status(), `PDS createSession must return 200 for the deployed administrator (got body: ${sessionText})`).toBe(200);
    const sessionJson = JSON.parse(sessionText);
    expect(
      [adminHandle, adminHandleReserved],
      "createSession must echo the administrator handle, without prefix or with i8- for a reserved name",
    ).toContain(sessionJson.handle);
    expect(typeof sessionJson.accessJwt, "createSession response must include an accessJwt").toBe("string");
    await apiContext.dispose();
  });
};
