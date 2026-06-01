const { test, expect } = require("@playwright/test");

const { assertCspMetaParity, assertCspResponseHeader } = require("./personas");

exports.register = function (shared) {
  test("zammad landing serves Content-Security-Policy headers", async ({ page }) => {
    const response = await page.goto(`${shared.env.zammadBaseUrl}/`);
    expect(response, "Expected zammad landing response").toBeTruthy();
    expect(response.status(), "Expected zammad landing status to be < 400").toBeLessThan(400);

    const directives = assertCspResponseHeader(response, "zammad landing");
    await assertCspMetaParity(page, directives, "zammad landing");
  });
};
