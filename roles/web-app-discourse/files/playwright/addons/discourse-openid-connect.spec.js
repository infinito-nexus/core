const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm, gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const discourseBaseUrl = normalizeBaseUrl(process.env.DISCOURSE_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

async function signInViaOidc(page) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${discourseBaseUrl}/`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s+with\s+oidc|sign\s*in\s+with\s+sso|continue\s+with\s+oidc|continue\s+with\s+sso|single\s+sign[-\s]*on|log\s*in|sign\s*up/i })
    .first();

  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click({ timeout: resolveTimeout(30_000) });
  } else {
    await gotoOnion(page, `${discourseBaseUrl}/auth/oidc`).catch(() => {});
  }

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect back to discourse at ${discourseBaseUrl}`,
    })
    .toContain(discourseBaseUrl);
}

async function readSiteSettings(page) {
  const result = await page.evaluate(async (base) => {
    const res = await fetch(`${base}/admin/site_settings.json`, {
      headers: { Accept: "application/json" },
      credentials: "include",
    });
    if (!res.ok) return { ok: false, status: res.status };
    const body = await res.json();
    return { ok: true, settings: (body && body.site_settings) || [] };
  }, discourseBaseUrl);

  expect(
    result.ok,
    `expected /admin/site_settings.json to be reachable as admin (status ${result.status})`,
  ).toBe(true);

  return result.settings;
}

function settingValue(settings, name, why) {
  const found = settings.find((s) => s && s.setting === name);
  expect(found, why).toBeTruthy();
  return String(found.value);
}

test("discourse-openid-connect: the OIDC plugin drives login against the distinct Keycloak partner", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-openid-connect");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(discourseBaseUrl, "DISCOURSE_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const discourseHost = new URL(discourseBaseUrl).host;
  const issuerHost = new URL(oidcIssuerUrl).host;

  try {
    await page.context().clearCookies();
    await signInViaOidc(page);

    await expect(page.locator("body")).toContainText(
      /topic|category|welcome|latest|discourse/i,
      { timeout: resolveTimeout(60_000) },
    );

    const settings = await readSiteSettings(page);

    expect(
      settingValue(
        settings,
        "openid_connect_enabled",
        "openid_connect_enabled site setting must exist (the bundled OIDC plugin is part of the Discourse image)",
      ).toLowerCase(),
      "openid_connect_enabled must be active whenever the sso service is part of the deployment",
    ).toBe("true");

    const discovery = settingValue(
      settings,
      "openid_connect_discovery_document",
      "openid_connect_discovery_document site setting must exist so the plugin can resolve the partner's endpoints",
    ).trim();

    expect(
      discovery,
      "the discovery document must be an absolute URL of the identity partner",
    ).toMatch(/^https?:\/\//i);
    expect(
      new URL(discovery).host.toLowerCase(),
      "the discovery document must point at the Keycloak partner host, NOT at Discourse itself",
    ).not.toBe(discourseHost.toLowerCase());
    expect(
      new URL(discovery).host.toLowerCase(),
      "the discovery document must point at the very issuer the login redirect went through, proving one identity partner rather than two unrelated configurations",
    ).toBe(issuerHost.toLowerCase());

    expect(
      settingValue(
        settings,
        "openid_connect_client_id",
        "openid_connect_client_id site setting must exist",
      ).trim().length,
      "openid_connect_client_id must be provisioned; an empty client id makes every authorization request fail at the partner",
    ).toBeGreaterThan(0);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
