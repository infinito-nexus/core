const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  attachDiagnostics,
  expectNoCspViolations,
  installCspViolationObserver,
  safeIsEnabled,
} = require("./personas");

exports.register = function (shared) {
  test("biber: login -> dashboard map renders under the CSP -> logout -> gated again", async ({ page }) => {
    test.setTimeout(resolveTimeout(300_000)); // Keycloak round-trip, the dashboard boot and the SSO logout
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    const diagnostics = attachDiagnostics(page);
    await installCspViolationObserver(page);
    await shared.loginToDashboard(page, shared.env.biberUsername, shared.env.biberPassword);
    await expectNoCspViolations(page, diagnostics, "World Monitor dashboard");

    await shared.openApp(page, "/");
    await shared.expectDashboard(page, "an existing session must reach the dashboard without a prompt");
    expect(page.url(), "an existing session must not be sent to Keycloak again").not.toMatch(shared.KEYCLOAK_AUTH_RE);

    if (safeIsEnabled("sso")) {
      await shared.logout(page);
    }
  });
};
