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

test("discourse-bbb: the BigBlueButton plugin is installed and points at the distinct conferencing partner", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-bbb");
  skipUnlessServiceEnabled("sso");
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

    const settings = await readSiteSettings(page);

    expect(
      settingValue(
        settings,
        "bbb_enabled",
        "bbb_enabled site setting must exist (discourse-bbb plugin compiled into the image)",
      ).toLowerCase(),
      "bbb_enabled must be active so composer posts can embed a conference",
    ).toBe("true");

    const endpoint = settingValue(
      settings,
      "bbb_endpoint",
      "bbb_endpoint site setting must exist (discourse-bbb plugin installed)",
    ).trim();

    expect(
      endpoint,
      "bbb_endpoint must be an absolute URL of the BigBlueButton API so the plugin can create meetings",
    ).toMatch(/^https?:\/\//i);
    expect(
      new URL(endpoint).host.toLowerCase(),
      "bbb_endpoint must target the BigBlueButton partner host, NOT Discourse itself — otherwise no conference server is reached",
    ).not.toBe(discourseHost.toLowerCase());

    expect(
      settingValue(
        settings,
        "bbb_secret",
        "bbb_secret site setting must exist (discourse-bbb plugin installed)",
      ).trim().length,
      "bbb_secret must be provisioned so the plugin can sign BigBlueButton API calls; an empty secret makes every create/join call fail",
    ).toBeGreaterThan(0);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
