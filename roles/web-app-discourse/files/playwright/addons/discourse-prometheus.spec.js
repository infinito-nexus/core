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

async function readAdminPlugins(page) {
  const result = await page.evaluate(async (base) => {
    const res = await fetch(`${base}/admin/plugins.json`, {
      headers: { Accept: "application/json" },
      credentials: "include",
    });
    if (!res.ok) return { ok: false, status: res.status };
    const body = await res.json();
    return { ok: true, plugins: (body && body.plugins) || [] };
  }, discourseBaseUrl);

  expect(
    result.ok,
    `expected /admin/plugins.json to be reachable as admin (status ${result.status})`,
  ).toBe(true);

  return result.plugins;
}

function pluginName(plugin) {
  return String((plugin && (plugin.name || plugin.id)) || "").toLowerCase();
}

async function readMetricsSurface(page) {
  return await page.evaluate(async (base) => {
    const res = await fetch(`${base}/metrics`, {
      headers: { Accept: "text/plain" },
      credentials: "include",
    });
    if (!res.ok) return `status ${res.status}`;
    return (await res.text()).slice(0, 4096);
  }, discourseBaseUrl);
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

    const plugins = await readAdminPlugins(page);

    const exporter = plugins.find((p) => pluginName(p) === "discourse-prometheus");
    expect(
      exporter,
      "discourse-prometheus must be listed in /admin/plugins.json (proves the upstream plugin was cloned into the image and registered)",
    ).toBeTruthy();

    expect(
      exporter.enabled,
      "discourse-prometheus must be enabled on the running instance",
    ).toBe(true);

    await expect
      .poll(() => readMetricsSurface(page), {
        timeout: resolveTimeout(60_000),
        message:
          "the /metrics middleware the plugin installs must serve Prometheus exposition to an admin session; a status line instead of exposition means 404 when the plugin is not loaded and 5xx when the collector demon is not listening on prometheus_collector_port",
      })
      .toMatch(/^#\s*(HELP|TYPE)\s/m);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
