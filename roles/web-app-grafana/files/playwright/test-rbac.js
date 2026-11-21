const { test, expect } = require("@playwright/test");
const { gotoOnion, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("rbac: biber without a Grafana role group is refused", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));
  await page.context().clearCookies();
  await gotoOnion(page, `${shared.env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected Grafana to redirect to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginForm(page, shared.env.biberUsername, shared.env.biberPassword);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Grafana MUST send biber back to its login page after the role mapping refused him",
    })
    .toMatch(new RegExp(`^${shared.env.appBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/login`));
  expect(
    await shared.hasGrafanaSession(page),
    "Grafana MUST NOT mint a session for an account outside the administrator and auditor role groups",
  ).toBe(false);
  const probe = await page.request.get(`${shared.env.appBaseUrl}/api/user`, { failOnStatusCode: false });
  expect(probe.status(), "the Grafana API MUST refuse biber").toBe(401);
});
