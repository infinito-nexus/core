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

test("docker_manager: the docker_manager plugin is installed and registered on the Discourse instance", async ({ page }) => {
  skipUnlessAddonEnabled("docker_manager");
  skipUnlessServiceEnabled("sso");

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

    const adminApi = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/plugins.json`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      return { ok: res.ok, status: res.status };
    }, discourseBaseUrl);

    expect(
      adminApi.ok,
      `expected /admin/plugins.json to be reachable as admin (status ${adminApi.status})`,
    ).toBe(true);

    const progress = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/docker/progress`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      if (!res.ok) return { ok: false, status: res.status };
      const body = await res.json();
      return { ok: true, hasProgress: !!(body && body.progress) };
    }, discourseBaseUrl);

    expect(
      progress.ok,
      `/admin/docker/progress is routed by the docker_manager engine alone, so a non-2xx status proves the upstream plugin was not cloned and registered; when docker_manager is enabled but its routes are absent the install failed and the test MUST fail here, not skip (status ${progress.status})`,
    ).toBe(true);

    expect(
      progress.hasProgress,
      "the upgrade surface the docker_manager plugin owns must answer with its progress payload",
    ).toBe(true);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
