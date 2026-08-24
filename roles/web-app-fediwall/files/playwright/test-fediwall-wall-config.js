const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("fediwall default slug ships its baked-in wall-config.json", async ({ request }) => {
    const response = await request.get(`${shared.env.appBaseUrl}/${shared.env.defaultSlug}/wall-config.json`, { timeout: resolveTimeout(30_000) });
    expect(
      response.status(),
      "Expected default-slug wall-config.json to be reachable for client-side bootstrap"
    ).toBeLessThan(400);
    const body = await response.json();
    expect(
      Array.isArray(body.servers),
      "wall-config.json MUST expose a servers array so Fediwall can bootstrap"
    ).toBe(true);
  });
};
