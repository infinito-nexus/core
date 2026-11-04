const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("atmo refuses an ingest cycle without the cron secret", async ({ request }) => {
    const origin = new URL(shared.env.appBaseUrl).origin;
    const response = await request.post(`${origin}/api/cron`, {
      headers: { "Content-Type": "application/json", "X-Cron-Secret": "not-the-secret" },
      data: "{}",
      timeout: resolveTimeout(30_000),
    });
    expect(response.status(), "Expected /api/cron to reject a wrong secret").toBe(401);
  });
};
