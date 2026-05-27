const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue } = require("./personas");

const moodleScopeName = decodeDotenvQuotedValue(process.env.MOODLE_OIDC_SCOPE_NAME || "moodle");

exports.register = function (shared) {
  test.describe("moodle keycloak scope wiring (variant 0)", () => {
    test.skip(!shared.env.oidcEnabled, "OIDC shared service disabled");

    test("Keycloak realm discovery advertises the moodle OIDC scope", async ({ request }) => {
      expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set in env").toBeTruthy();
      const r = await request.get(`${shared.env.oidcIssuerUrl}/.well-known/openid-configuration`);
      expect(r.ok(), `discovery doc must be reachable at ${shared.env.oidcIssuerUrl}`).toBeTruthy();
      const cfg = await r.json();
      expect(Array.isArray(cfg.scopes_supported), "scopes_supported must be an array").toBe(true);
      expect(
        cfg.scopes_supported.includes(moodleScopeName),
        `realm scopes_supported must contain "${moodleScopeName}"`
      ).toBe(true);
    });

    test("biber can edit middleName via Keycloak Account REST API and value persists", async ({ page }) => {
      expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set in env").toBeTruthy();
      expect(shared.env.oidcClientId, "OIDC_CLIENT_ID must be set in env").toBeTruthy();

      await page.goto(`${shared.env.oidcIssuerUrl}/.well-known/openid-configuration`);

      const probe = `MN-${Date.now()}`;
      const result = await page.evaluate(shared.setMiddleNameViaAccountRest, {
        issuer: shared.env.oidcIssuerUrl,
        clientId: shared.env.oidcClientId,
        username: shared.env.biberUsername,
        password: shared.env.biberPassword,
        middleName: probe,
        withRestore: true,
      });

      expect(
        result.stage,
        `flow must reach ok stage; got stage=${result.stage} status=${result.status} body=${(result.body || "").slice(0, 200)}`
      ).toBe("ok");
      expect(
        result.attrNames,
        "Account user-profile metadata must include the Moodle 'middleName' attribute"
      ).toContain("middleName");
      expect(
        result.verifiedMiddleName,
        "middleName value must round-trip after Account REST update"
      ).toBe(probe);
    });
  });
};
