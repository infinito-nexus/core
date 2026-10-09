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

test("discourse-prometheus: the exporter plugin is installed and its scrape collector is addressable", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-prometheus");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(discourseBaseUrl, "DISCOURSE_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  try {
    await page.context().clearCookies();
    await signInViaOidc(page);

    await expect(page.locator("body")).toContainText(
      /topic|category|welcome|latest|discourse/i,
      { timeout: resolveTimeout(60_000) },
    );

    const settings = await readSiteSettings(page);

    const collectorPort = settingValue(
      settings,
      "prometheus_collector_port",
      "prometheus_collector_port site setting must exist (discourse-prometheus plugin compiled into the image)",
    ).trim();

    expect(
      collectorPort,
      "prometheus_collector_port must be a numeric TCP port; without it the Prometheus partner has nothing to scrape",
    ).toMatch(/^[0-9]+$/);
    expect(
      Number(collectorPort),
      "prometheus_collector_port must be a valid TCP port",
    ).toBeGreaterThan(0);

    expect(
      settingValue(
        settings,
        "prometheus_trusted_ip_allowlist_regex",
        "prometheus_trusted_ip_allowlist_regex site setting must exist so the metrics surface can be opened to the Prometheus partner only",
      ),
      "the allowlist setting must be a string the plugin can match scrape sources against",
    ).not.toBeNull();
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
