const { test, expect } = require("@playwright/test");

const { assertCspMetaParity, assertCspResponseHeader } = require("./personas");

exports.register = function (shared) {
  test("n8n landing serves Content-Security-Policy headers", async ({ page }) => {
    const response = await page.goto(`${shared.env.n8nBaseUrl}/`);
    expect(response, "Expected n8n landing response").toBeTruthy();
    expect(response.status(), "Expected n8n landing status to be < 400").toBeLessThan(400);

    const directives = assertCspResponseHeader(response, "n8n landing");
    await assertCspMetaParity(page, directives, "n8n landing");
  });
};
