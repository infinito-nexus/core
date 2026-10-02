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

test("discourse-chat-integration: the chat plugin is installed and offers the Matrix and Mattermost partner providers", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-chat-integration");
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

    expect(
      settingValue(
        settings,
        "chat_integration_enabled",
        "chat_integration_enabled site setting must exist (discourse-chat-integration plugin compiled into the image)",
      ).toLowerCase(),
      "chat_integration_enabled must be active so topic notifications can leave Discourse for a chat partner",
    ).toBe("true");

    settingValue(
      settings,
      "chat_integration_matrix_homeserver",
      "chat_integration_matrix_homeserver must exist so the Matrix provider has a homeserver field to address the partner with",
    );

    settingValue(
      settings,
      "chat_integration_mattermost_webhook_url",
      "chat_integration_mattermost_webhook_url must exist so the Mattermost provider has a webhook field to address the partner with",
    );

    const providers = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/plugins/chat-integration/providers.json`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      let json;
      try {
        json = await res.json();
      } catch {
        json = null;
      }
      return { status: res.status, json };
    }, discourseBaseUrl);

    expect(
      providers.status,
      "the plugin's provider catalogue route must be served; a 404 proves the plugin did not land in the image",
    ).toBeLessThan(400);

    const catalogue = JSON.stringify(providers.json || {});
    expect(
      catalogue,
      "the provider catalogue must name the Matrix partner this deployment bridges",
    ).toMatch(/matrix/i);
    expect(
      catalogue,
      "the provider catalogue must name the Mattermost partner this deployment bridges",
    ).toMatch(/mattermost/i);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
