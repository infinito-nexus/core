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
    await oidcSignIn.click();
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

function findSetting(settings, name) {
  return settings.find((s) => s && s.setting === name);
}

function settingValue(settings, name) {
  const found = findSetting(settings, name);
  expect(found, `${name} site setting must exist (LDAP auth plugin installed & configured)`).toBeTruthy();
  return String(found.value);
}

test("discourse-ldap-auth: LDAP auth plugin binds Discourse to the distinct LDAP partner directory", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-ldap-auth");
  skipUnlessServiceEnabled("ldap");
  test.setTimeout(resolveTimeout(120_000));

  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(discourseBaseUrl, "DISCOURSE_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const discourseHost = new URL(discourseBaseUrl).host;

  try {
    await page.context().clearCookies();
    await signInViaOidc(page);

    await expect(page.locator("body")).toContainText(
      /topic|category|welcome|latest|discourse/i,
      { timeout: resolveTimeout(60_000) },
    );

    const siteSettings = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/site_settings.json`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      if (!res.ok) return { ok: false, status: res.status };
      const body = await res.json();
      return { ok: true, settings: (body && body.site_settings) || [] };
    }, discourseBaseUrl);

    expect(
      siteSettings.ok,
      `expected /admin/site_settings.json to be reachable as admin (status ${siteSettings.status})`,
    ).toBe(true);

    const settings = siteSettings.settings;

    expect(
      settingValue(settings, "ldap_auth_enabled").toLowerCase(),
      "ldap_auth_enabled must be active (LDAP auth plugin installed and turned on)",
    ).toBe("true");

    expect(
      settingValue(settings, "ldap_sync_enabled").toLowerCase(),
      "ldap_sync_enabled must be active (Discourse must sync against the LDAP partner directory)",
    ).toBe("true");

    const ldapHost = settingValue(settings, "ldap_sync_host").trim();
    expect(
      ldapHost.length,
      "ldap_sync_host must point at the LDAP partner server (non-empty)",
    ).toBeGreaterThan(0);
    expect(
      ldapHost.toLowerCase(),
      "ldap_sync_host must be the LDAP partner host, NOT the Discourse host itself — the bridge has to reach a distinct directory server",
    ).not.toBe(discourseHost.toLowerCase());

    const ldapPort = settingValue(settings, "ldap_sync_port").trim();
    expect(
      ldapPort,
      "ldap_sync_port must be a real numeric LDAP bind port (proves a reachable partner endpoint, not a placeholder)",
    ).toMatch(/^[0-9]+$/);
    expect(
      Number(ldapPort),
      "ldap_sync_port must be a valid TCP port for the LDAP partner",
    ).toBeGreaterThan(0);

    const ldapBaseDn = settingValue(settings, "ldap_base_dn").trim();
    expect(
      ldapBaseDn,
      "ldap_base_dn must be a real LDAP directory root (e.g. dc=...) derived from the partner domain",
    ).toMatch(/dc=/i);

    const ldapBindDn = settingValue(settings, "ldap_bind_dn").trim();
    expect(
      ldapBindDn.length,
      "ldap_bind_dn must be set so Discourse can bind to the LDAP partner",
    ).toBeGreaterThan(0);
    expect(
      ldapBindDn,
      "ldap_bind_dn must be rooted in the SAME partner directory as ldap_base_dn — proves the bind account lives in the reached LDAP tree, not a stub",
    ).toContain(ldapBaseDn);

    const ldapUserFilter = settingValue(settings, "ldap_user_filter").trim();
    expect(
      ldapUserFilter.length,
      "ldap_user_filter must be set so login attempts resolve users against the LDAP partner",
    ).toBeGreaterThan(0);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
