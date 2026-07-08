const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const discourseBaseUrl = normalizeBaseUrl(process.env.DISCOURSE_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

async function signInViaOidc(page) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await page.goto(`${discourseBaseUrl}/`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s+with\s+oidc|sign\s*in\s+with\s+sso|continue\s+with\s+oidc|continue\s+with\s+sso|single\s+sign[-\s]*on|log\s*in|sign\s*up/i })
    .first();

  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click();
  } else {
    await page.goto(`${discourseBaseUrl}/auth/oidc`).catch(() => {});
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

function pluginName(plugin) {
  return String((plugin && (plugin.name || plugin.id)) || "").toLowerCase();
}

test("docker_manager: the docker_manager plugin is installed and registered on the Discourse instance", async ({ page }) => {
  skipUnlessAddonEnabled("docker_manager");

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

    const plugins = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/plugins.json`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      if (!res.ok) return { ok: false, status: res.status };
      const body = await res.json();
      return { ok: true, plugins: (body && body.plugins) || [] };
    }, discourseBaseUrl);

    expect(
      plugins.ok,
      `expected /admin/plugins.json to be reachable as admin (status ${plugins.status})`,
    ).toBe(true);

    const dockerManager = plugins.plugins.find(
      (p) => pluginName(p) === "docker_manager" || pluginName(p) === "discourse-docker-manager",
    );
    expect(
      dockerManager,
      "the docker_manager plugin must be present in /admin/plugins.json (proves the upstream plugin was cloned and registered; when docker_manager is enabled but absent the install failed — the test MUST fail here, not skip)",
    ).toBeTruthy();

    expect(
      dockerManager.enabled,
      "the docker_manager plugin must be enabled on the running instance",
    ).toBe(true);

    const upgradeResponse = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/upgrade.json`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      return { ok: res.ok, status: res.status };
    }, discourseBaseUrl);

    expect(
      upgradeResponse.ok,
      `the docker_manager upgrade surface (/admin/upgrade.json) the plugin owns must be served (status ${upgradeResponse.status})`,
    ).toBe(true);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
