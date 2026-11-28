const { test, expect } = require("./onion-test");

const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("gateway: the Control UI origin is admitted and a new browser is asked for its pairing", async ({ page }) => {
    await shared.openGate(page);
    await shared.connectGate(page);
    await expect(
      page.locator(`${shared.GATE} .login-gate__failure`),
      shared.env.trustedProxy
        ? "a browser the OAuth2 proxy signed in MUST reach the device pairing step without the gateway token"
        : "a browser that presents the gateway token must reach the device pairing step",
    ).toHaveAttribute("data-kind", "pairing-required", { timeout: resolveTimeout(60_000) });
  });
};
