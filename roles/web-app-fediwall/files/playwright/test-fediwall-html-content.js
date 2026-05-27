const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("fediwall default slug returns HTML content", async ({ request }) => {
    const response = await request.get(`${shared.env.appBaseUrl}/${shared.env.defaultSlug}/`);
    expect(response.status(), "Expected default-slug status < 400").toBeLessThan(400);
    const contentType = response.headers()["content-type"] || "";
    expect(
      contentType.includes("text/html"),
      `Expected HTML content-type, got "${contentType}"`
    ).toBe(true);
  });
};
