const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
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

test("discourse-akismet: spam-filtering plugin is installed and coupled to the Akismet partner API", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-akismet");

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

    const akismetEnabled = findSetting(siteSettings.settings, "akismet_enabled");
    expect(
      akismetEnabled,
      "akismet_enabled site setting must exist (Akismet plugin installed)",
    ).toBeTruthy();
    expect(
      String(akismetEnabled.value).toLowerCase(),
      "akismet_enabled must be active (spam filtering wired up)",
    ).toBe("true");

    const antiSpamService = findSetting(siteSettings.settings, "anti_spam_service");
    expect(
      antiSpamService,
      "anti_spam_service site setting must exist (Akismet plugin installed)",
    ).toBeTruthy();
    expect(
      String(antiSpamService.value).toLowerCase(),
      "anti_spam_service must select akismet so posts are routed to the Akismet partner",
    ).toBe("akismet");

    const akismetApiKey = findSetting(siteSettings.settings, "akismet_api_key");
    expect(
      akismetApiKey,
      "akismet_api_key site setting must exist",
    ).toBeTruthy();
    expect(
      String(akismetApiKey.value).trim().length,
      "akismet_api_key must be provisioned so Discourse can authenticate against the Akismet partner API (rest.akismet.com) — without it the spam-check coupling cannot reach the partner",
    ).toBeGreaterThan(0);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
