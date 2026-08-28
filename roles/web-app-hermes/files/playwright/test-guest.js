const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("guest: Hermes API server is healthy and refuses unauthenticated model listing", async ({ request }) => {
    const health = await request.get(`${shared.env.baseUrl}/health`, { timeout: resolveTimeout(30_000) });
    expect(health.status(), "Expected the Hermes /health endpoint to answer 200").toBe(200);
    const body = await health.json();
    expect(body.status, "Expected /health to report an ok status").toBe("ok");

    const models = await request.get(`${shared.env.baseUrl}/v1/models`, { timeout: resolveTimeout(30_000) });
    expect(
      models.status(),
      "Expected /v1/models without a bearer key to be rejected",
    ).toBeGreaterThanOrEqual(400);
  });
};
