const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiGetOnion,
  assertCspResponseHeader,
  attachDiagnostics,
  expectNoCspViolations,
  installCspViolationObserver,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const GATE_SESSION_COOKIE_RE = /^_oauth2_proxy/;

function cspPolicies(headers) {
  return headers
    .filter(({ name }) => name.toLowerCase() === "content-security-policy")
    .flatMap(({ value }) => value.split(/[\n,]/))
    .map((policy) => policy.trim())
    .filter(Boolean);
}

function recordAuthorizationHops(page, authorizationRe) {
  const statuses = [];
  page.on("response", (response) => {
    if (response.request().isNavigationRequest() && authorizationRe.test(response.url())) {
      statuses.push(response.status());
    }
  });
  return statuses;
}

exports.register = function (shared) {
  test("biber: login -> dashboard map renders under the CSP -> logout -> gated again", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000)); // Keycloak round-trip, the dashboard boot and the SSO logout
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    const diagnostics = attachDiagnostics(page);
    await installCspViolationObserver(page);
    await shared.loginToDashboard(page, shared.env.biberUsername, shared.env.biberPassword);
    await expectNoCspViolations(page, diagnostics, "World Monitor dashboard");

    const surface = await apiGetOnion(page.request, `${shared.env.appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
    expect(surface.status(), "the canonical surface must serve the dashboard to the session").toBe(200);
    expect(
      cspPolicies(surface.headersArray()),
      "the canonical surface must answer with exactly one Content-Security-Policy",
    ).toHaveLength(1);
    assertCspResponseHeader(surface, "World Monitor canonical surface");

    await shared.openApp(page, "/");
    await shared.expectDashboard(page, "an existing session must reach the dashboard without a prompt");
    expect(page.url(), "an existing session must not be sent to Keycloak again").not.toMatch(shared.KEYCLOAK_AUTH_RE);

    await shared.logout(page);
  });

  test("biber: an existing Keycloak session reaches the dashboard without an interactive login", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000));
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await shared.loginToDashboard(page, shared.env.biberUsername, shared.env.biberPassword);
    await page.context().clearCookies({ name: GATE_SESSION_COOKIE_RE });

    const authorizationHops = recordAuthorizationHops(page, shared.KEYCLOAK_AUTH_RE);
    await shared.openApp(page, "/");
    await shared.expectDashboard(page, "the Keycloak session alone must reach the dashboard");
    expect(authorizationHops.length, "without its own session cookie the oauth2 gate must ask Keycloak").toBeGreaterThan(0);
    expect(
      authorizationHops.filter((status) => status < 300 || status >= 400),
      "Keycloak must answer from its session by redirect, never with its login form",
    ).toEqual([]);

    await shared.logout(page);
  });
};
