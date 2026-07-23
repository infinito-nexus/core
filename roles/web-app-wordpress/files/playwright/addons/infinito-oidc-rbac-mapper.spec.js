const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon infinito-oidc-rbac-mapper: OIDC login bridges to the Keycloak partner carrying the groups scope and lands on the role-mapping surface", async ({ browser }) => {
  skipUnlessAddonEnabled("infinito-oidc-rbac-mapper");
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("ldap");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  const wpHost = new URL(shared.env.wpBaseUrl).host;
  const keycloakHost = new URL(shared.env.keycloakBaseUrl).host;

  try {
    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-login.php`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });

    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message:
          "wp-login.php (login_type=auto) must redirect to the SSO partner's authorize endpoint — staying on WordPress means the OIDC bridge never reached Keycloak",
      })
      .toMatch(/\/protocol\/openid-connect\/auth/i);

    const authorizeUrl = new URL(page.url());
    expect(
      authorizeUrl.host,
      "the OIDC authorize request must be served by the Keycloak partner instance, not by WordPress"
    ).toBe(keycloakHost);
    expect(
      authorizeUrl.host,
      "the OIDC authorize host must differ from the WordPress host (the bridge must cross to the partner)"
    ).not.toBe(wpHost);
    expect(
      authorizeUrl.searchParams.get("response_type"),
      "the authorize redirect must use the OIDC authorization-code flow"
    ).toBe("code");
    expect(
      authorizeUrl.searchParams.get("client_id"),
      "the authorize redirect must carry the provisioned OIDC client_id (proves the WordPress OIDC client is registered on the partner)"
    ).toBeTruthy();
    const scope = authorizeUrl.searchParams.get("scope") || "";
    expect(
      scope.split(/\s+/),
      "the authorize scope must request the `groups` claim that this RBAC mapper consumes — without it the mu-plugin can never map a role"
    ).toContain("groups");

    await shared.fillKeycloakLoginForm(
      page,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: `Expected redirect back to ${shared.env.wpBaseUrl}/wp-admin after the OIDC round-trip`,
      })
      .toContain("/wp-admin");

    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/users.php`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });

    const roleSurface = page
      .locator("#the-list tr, table.users th#role, #wpbody-content .wrap")
      .first();
    await expect(
      roleSurface,
      "the wp-admin users list (RBAC role-mapping surface) must render after the group-claim-bearing OIDC login"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
