const { test, expect } = require("@playwright/test");

const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("gateway: the Control UI origin is admitted and a new browser is asked for its pairing", async ({ page }) => {
    await shared.openGate(page);
    await shared.submitToken(page);
    await expect(
      page.locator(`${shared.GATE} .login-gate__failure`),
      "a browser that presents the gateway token must reach the device pairing step",
    ).toHaveAttribute("data-kind", "pairing-required", { timeout: resolveTimeout(60_000) });
  });
};
