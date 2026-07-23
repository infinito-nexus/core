const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow, safeSkipUnlessEnabled } = require("./personas");
test.use({
  ignoreHTTPSErrors: true
});

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl      = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const prometheusBaseUrl  = decodeDotenvQuotedValue(process.env.PROMETHEUS_BASE_URL);
const canonicalDomain    = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername      = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword      = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername      = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword      = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

// Log out via the universal logout endpoint.
async function prometheusLogout(page, baseUrl) {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/logout`, { waitUntil: "commit" }).catch(() => {});
}

test.beforeEach(() => {
  expect(oidcIssuerUrl,     "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(prometheusBaseUrl, "PROMETHEUS_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(canonicalDomain,   "CANONICAL_DOMAIN must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername,     "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword,     "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername,     "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword,     "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
});

// Scenario I: /metricz exposes prometheus-format metrics — no auth required.
//
// /metricz is the central nginx metrics endpoint scraped by prometheus once for all apps.
// It must be accessible without authentication (prometheus scrapes it without bearer tokens).
// If this returns 401/403 the nginx ACL whitelist for /metricz is misconfigured.
// If it returns HTML the location = /metricz block is missing from the nginx vhost config.
//
// The body is also asserted to carry an `app="<role_id>"` label for every consumer role
// declared in `roles_with_service('prometheus')`. lua-resty-prometheus tags each request
// with the vhost's role id, so a missing label means that role's vhost is not registered
// in the shared metrics dict. This subsumes the per-app metricz-label spot checks that
// used to live in each consumer role's own playwright.spec.js.
test("metricz endpoint is accessible and returns prometheus text format", async ({ request }) => {
  const metriczUrl = `${prometheusBaseUrl.replace(/\/$/, "")}/metricz`;

  for (const target of prometheusTargetRoles) {
    const base = String(target.canonical_url || "").replace(/\/$/, "");
    if (!base) continue;
    await request.get(`${base}/healthz/ready`, { failOnStatusCode: false }).catch(() => {});
  }

  const response = await request.get(metriczUrl);

  expect(
    response.status(),
    `/metricz must return 200 without auth — got ${response.status()}. ` +
    "If 401/403 the nginx ACL whitelist is misconfigured. If 200 with HTML, the location block is missing."
  ).toBe(200);

  const body = await response.text();

  expect(
    body,
    "/metricz response must be prometheus text format (lines starting with #) — got HTML or empty"
  ).toMatch(/^#/m);

  expect(
    body,
    "/metricz must expose nginx_http_requests_total — lua-resty-prometheus metric not found"
  ).toContain("nginx_http_requests_total");

  for (const target of prometheusTargetRoles) {
    await expect
      .poll(
        async () => {
          const base = String(target.canonical_url || "").replace(/\/$/, "");
          if (base) {
            await request.get(`${base}/healthz/ready`, { failOnStatusCode: false }).catch(() => {});
          }
          const scrape = await request.get(metriczUrl);
          return (await scrape.text()).includes(`app="${target.id}"`);
        },
        {
          timeout: 60_000,
          message:
            `/metricz must contain metrics labeled app="${target.id}" — ` +
            `the ${target.id} vhost is not registered in lua-resty-prometheus.`,
        },
      )
      .toBe(true);
  }
});

// Scenario II: direct goto Prometheus → SSO login (as admin) → verify Prometheus UI → logout
//
// Prometheus is admin-only (allowed_groups: web-app-prometheus-administrator).
// Visiting the canonical Prometheus URL triggers the OAuth2-Proxy redirect
// chain to Keycloak; on successful auth the proxy redirects back to the
// Prometheus UI directly (no dashboard-iframe wrapping). The
// dashboard-tile-reachability concern is owned by web-app-dashboard's
// own spec, so this test no longer exercises that
// click path — keeping admin-reach SPOT-clean.
test("prometheus: admin sso login, verify ui, logout", async ({ page }) => {
  safeSkipUnlessEnabled("sso");
  const expectedOidcAuthUrl       = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedPrometheusBaseUrl = prometheusBaseUrl.replace(/\/$/, "");

  // 1. Navigate directly to Prometheus — oauth2-proxy redirects to Keycloak.
  await page.goto(`${expectedPrometheusBaseUrl}/`);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`
    })
    .toContain(expectedOidcAuthUrl);

  // 2. Log in as admin at Keycloak.
  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  // 3. After successful auth, oauth2-proxy redirects back to Prometheus.
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected redirect back to Prometheus after admin login: ${expectedPrometheusBaseUrl}`
    })
    .toContain(expectedPrometheusBaseUrl);

  // 4. Verify Prometheus UI is loaded.
  //    The Prometheus v3.x nav always exposes "Graph", "Alerts", and "Status" links.
  await expect(
    page.getByRole("link", { name: /^(Graph|Alerts|Status)$/i }).first()
  ).toBeVisible({ timeout: 30_000 });

  // 5. Logout via universal logout endpoint.
  await prometheusLogout(page, expectedPrometheusBaseUrl);

  // 6. Verify session is gone — oauth2-proxy redirects unauthenticated requests to Keycloak.
  await page.goto(`${expectedPrometheusBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: 15_000,
      message: "Expected redirect to Keycloak after logout"
    })
    .toContain(expectedOidcAuthUrl);
});

// Scenario II: biber (non-admin) navigates directly to Prometheus → SSO login → access denied
//
// biber is a regular authenticated user but is NOT in the web-app-prometheus-administrator group.
// After successfully authenticating with Keycloak, oauth2-proxy checks the groups claim and
// returns HTTP 403 — biber must never reach the Prometheus UI.
test("prometheus: biber is denied access after sso login", async ({ browser }) => {
  safeSkipUnlessEnabled("sso");
  const expectedOidcAuthUrl       = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedPrometheusBaseUrl = prometheusBaseUrl.replace(/\/$/, "");

  // Use an isolated browser context so this test has no shared session with other tests.
  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });

  try {
    const biberPage = await biberContext.newPage();

    // Register the callback listener BEFORE goto to guarantee no response is missed.
    // In fast local environments the entire redirect chain (goto → Keycloak → callback)
    // can complete before a listener registered after performKeycloakLoginForm would start,
    // causing waitForResponse to catch a 200 sub-resource instead of the real response.
    //
    // oauth2-proxy hits /oauth2/callback after the Keycloak login:
    //   • user NOT in allowed_groups → 403 (biber's expected path)
    //   • user IS in allowed_groups  → 302 redirect to the app (admin's path)
    const callbackResponsePromise = biberPage.waitForResponse(
      (res) => res.url().includes("/oauth2/callback"),
      { timeout: 60_000 }
    );

    // 1. Navigate directly to Prometheus — oauth2-proxy redirects to Keycloak
    await biberPage.goto(`${expectedPrometheusBaseUrl}/`);

    await expect
      .poll(() => biberPage.url(), {
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`
      })
      .toContain(expectedOidcAuthUrl);

    // 2. Log in as biber via Keycloak
    await performKeycloakLoginForm(biberPage, biberUsername, biberPassword);

    // 3. Await the callback response — must be 403 (biber is not in prometheus-administrator group)
    const callbackResponse = await callbackResponsePromise;

    expect(
      callbackResponse.status(),
      `Expected oauth2-proxy to deny biber with 403 at /oauth2/callback, got ${callbackResponse.status()}`
    ).toBe(403);

  } finally {
    await biberContext.close().catch(() => {});
  }
});

// -----------------------------------------------------------------------------
// Scrape-target reachability per consumer: one
// parameterised assertion per role declared as a prometheus consumer
// in its meta/services.yml. The role list is emitted into
// PROMETHEUS_TARGET_ROLES_JSON at deploy time by the env template via
// the `roles_with_service('prometheus')` Ansible filter, so this spec
// — and ONLY this spec — owns the per-role `up=1` assertion. Other
// roles' personas no longer drive the prometheus surface.
// -----------------------------------------------------------------------------

const prometheusTargetRoles = (() => {
  const raw = process.env.PROMETHEUS_TARGET_ROLES_JSON || "[]";
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
})();

test("prometheus scrape: every consumer role reports up=1", async ({ page }) => {
  test.skip(prometheusTargetRoles.length === 0, "no prometheus consumer roles in inventory");

  const expectedPrometheusBaseUrl = prometheusBaseUrl.replace(/\/$/, "");

  // Authenticate as administrator via the direct prometheus URL flow.
  // Same shape as scenario II's biber path, just with admin credentials
  // so the OAuth2-Proxy callback succeeds (302 -> prometheus).
  await page.goto(`${expectedPrometheusBaseUrl}/`, { waitUntil: "domcontentloaded" });
  if (page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
  }
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected admin to land on the prometheus surface (${expectedPrometheusBaseUrl})`,
    })
    .toContain(expectedPrometheusBaseUrl);

  // Query `up` once; iterate the consumer list against the same result
  // set so failures report which role's target is missing or down.
  const queryUrl = `${expectedPrometheusBaseUrl}/api/v1/query?query=${encodeURIComponent("up")}`;
  const response = await page.request.get(queryUrl, { ignoreHTTPSErrors: true });
  expect(
    response.status(),
    `prometheus /api/v1/query MUST respond < 400 (got ${response.status()})`
  ).toBeLessThan(400);

  const body = await response.json();
  expect(body?.status, "prometheus query API MUST report 'success'").toBe("success");

  const results = Array.isArray(body?.data?.result) ? body.data.result : [];
  const failures = [];

  for (const target of prometheusTargetRoles) {
    const needles = [target.id.toLowerCase(), String(target.canonical_domain || "").toLowerCase()].filter(Boolean);
    const matching = results.filter((entry) => {
      const labels = entry?.metric || {};
      // Read labels.app so native-metrics scrape jobs (which set the
      // app label explicitly via `roles/<role>/templates/prometheus.yml.j2`)
      // get matched alongside blackbox-healthz targets (which match
      // via the canonical domain on labels.instance).
      const haystack = `${labels.job || ""} ${labels.instance || ""} ${labels.app || ""}`.toLowerCase();
      return needles.some((needle) => needle && haystack.includes(needle));
    });
    if (matching.length === 0) {
      failures.push(`${target.id}: no matching prometheus scrape target found (job/instance/app must mention "${target.id}" or "${target.canonical_domain}")`);
      continue;
    }
    const down = matching.filter((entry) => !Array.isArray(entry.value) || entry.value[1] !== "1");
    if (down.length > 0) {
      failures.push(`${target.id}: ${down.length} matching target(s) reporting up != 1`);
    }
  }

  expect(
    failures,
    `prometheus scrape failures:\n  - ${failures.join("\n  - ")}`
  ).toEqual([]);
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // Prometheus admin-only interaction: open the targets / status page.
      // Confirms the operator reaches the management surface; biber is
      // covered by the deny-check inside runAdminFlow's sibling helper.
      const statusLink = interactivePage
        .getByRole("link", { name: /^(targets|status|alerts|graph|runtime|build)$/i })
        .first();
      if (await statusLink.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await statusLink.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /endpoint|state|labels|targets|alerts|series/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
