const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled, skipUnlessServiceDisabled } = require("./service-gating");
const {
  apiGetOnion,
  attachDiagnostics,
  expectNoCspViolations,
  installCspViolationObserver,
  runGuestFlow,
  performKeycloakLoginExpectingDenial,
} = require("./personas");

exports.register = function (shared) {
  test("guest: dashboard -> login -> never authenticated", async ({ page }) => {
    await runGuestFlow(page);
  });

  test("guest: the root path and an /api/ path are gated by the Keycloak login", async ({ page, request }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // two Keycloak round-trips of the oauth2 gate
    for (const path of ["/", shared.API_PROBE_PATH]) {
      await shared.openApp(page, path);
      await shared.expectKeycloakLogin(page, `an anonymous visit to ${path} must land on the Keycloak login`);
    }
    const response = await apiGetOnion(request, `${shared.env.appBaseUrl}${shared.API_PROBE_PATH}`, {
      failOnStatusCode: false,
      maxRedirects: 0,
      timeout: resolveTimeout(30_000),
    });
    expect([302, 303, 401], "an anonymous API request must not reach the app").toContain(response.status());
  });

  test("guest: with SSO disabled the dashboard is anonymous", async ({ page }) => {
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // the dashboard boot fetches every seeded layer
    const diagnostics = attachDiagnostics(page);
    await installCspViolationObserver(page);
    await shared.openApp(page, "/");
    await shared.expectDashboard(page, "with SSO disabled the dashboard is anonymous");
    await expectNoCspViolations(page, diagnostics, "World Monitor dashboard");
  });

  test("guest: a login without an account is rejected", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000)); // Keycloak round-trip of the oauth2 gate
    await shared.openApp(page, "/");
    await shared.expectKeycloakLogin(page, "an anonymous visit must land on the Keycloak login");
    await performKeycloakLoginExpectingDenial(page, "", "", shared.env.canonicalDomain);
    await shared.openApp(page, "/");
    await shared.expectKeycloakLogin(page, "a rejected login must leave the dashboard gated");
  });
};
