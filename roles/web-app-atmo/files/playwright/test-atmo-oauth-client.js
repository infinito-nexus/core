const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("atmo publishes its AT Protocol OAuth client under the canonical origin", async ({ request }) => {
    const origin = new URL(shared.env.appBaseUrl).origin;
    const metadataResponse = await request.get(`${origin}/oauth-client-metadata.json`, {
      timeout: resolveTimeout(30_000),
    });
    expect(metadataResponse.status(), "Expected the OAuth client metadata to answer 200").toBe(200);
    const metadata = await metadataResponse.json();
    expect(metadata.client_id, "Expected the client id to be the metadata URL on the canonical origin").toBe(
      `${origin}/oauth-client-metadata.json`
    );
    expect(metadata.redirect_uris, "Expected the OAuth callback on the canonical origin").toContain(
      `${origin}/oauth/callback`
    );
    expect(metadata.token_endpoint_auth_method, "Expected a confidential client").toBe("private_key_jwt");
    expect(metadata.jwks_uri, "Expected the JWKS on the canonical origin").toBe(`${origin}/oauth/jwks.json`);

    const jwksResponse = await request.get(metadata.jwks_uri, { timeout: resolveTimeout(30_000) });
    expect(jwksResponse.status(), "Expected the JWKS to answer 200").toBe(200);
    const jwks = await jwksResponse.json();
    expect(jwks.keys, "Expected exactly one client assertion key").toHaveLength(1);
    const [key] = jwks.keys;
    expect(key.kty, "Expected an EC client assertion key").toBe("EC");
    expect(key.crv, "Expected a P-256 client assertion key").toBe("P-256");
    expect(key.d, "Expected the JWKS to withhold the private scalar").toBeUndefined();
  });
};
