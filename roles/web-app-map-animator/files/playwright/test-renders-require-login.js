const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiGetOnion, safeIsEnabled } = require("./personas");

exports.register = function (shared) {
  test("Map Animator render API refuses requests without a session", async ({ request }) => {
    const response = await apiGetOnion(request, `${shared.env.appBaseUrl}/api/jobs`, {
      failOnStatusCode: false,
      maxRedirects: 0,
      timeout: resolveTimeout(30_000),
    });
    if (safeIsEnabled("sso")) {
      expect(response.status(), "the oauth2 gate must redirect an anonymous API call").toBe(302);
      expect(response.headers().location || "", "the redirect must start the oauth2 login").toMatch(
        /\/oauth2\/start|openid-connect\/auth/,
      );
      return;
    }
    expect(response.status(), "the job list must not be served without a session").toBe(401);
    expect(await response.json()).toEqual({ error: "Not logged in" });
  });
};
