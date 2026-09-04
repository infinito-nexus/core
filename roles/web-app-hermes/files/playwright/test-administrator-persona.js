const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: the API server key unlocks the OpenAI-compatible model listing", async ({ request }) => {
    test.skip(!shared.env.apiServerKey, "no Hermes API server key provisioned");

    const models = await request.get(`${shared.env.baseUrl}/v1/models`, {
      headers: { Authorization: `Bearer ${shared.env.apiServerKey}` },
      timeout: resolveTimeout(30_000),
    });
    expect(models.status(), "Expected an authenticated /v1/models listing").toBe(200);
    const body = await models.json();
    expect(body.object, "Expected an OpenAI-style list envelope").toBe("list");
    expect(
      Array.isArray(body.data) && body.data.length,
      "Expected at least one agent model entry",
    ).toBeTruthy();
  });
};
