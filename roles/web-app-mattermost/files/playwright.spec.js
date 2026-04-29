const { test, expect } = require("@playwright/test");

test.use({
  ignoreHTTPSErrors: true
});

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) {
    return value;
  }

  if (!(value.startsWith('"') && value.endsWith('"'))) {
    return value;
  }

  const encoded = value.slice(1, -1);

  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl      = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const mattermostBaseUrl  = decodeDotenvQuotedValue(process.env.MATTERMOST_BASE_URL);
const prometheusBaseUrl  = decodeDotenvQuotedValue(process.env.PROMETHEUS_BASE_URL);
const adminUsername      = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword      = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername      = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword      = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

async function waitForFirstVisible(locators, timeout = 60_000) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    for (const locator of locators) {
      if (await locator.first().isVisible().catch(() => false)) {
        return locator.first();
      }
    }

    await new Promise(r => setTimeout(r, 500));
  }

  throw new Error("Timed out waiting for one of the expected selectors to become visible");
}

// Perform SSO login via Keycloak inside a frame context (or page context for direct navigation).
async function performOidcLogin(frame, username, password) {
  const usernameField = frame.getByRole("textbox", { name: /username|email/i });
  const passwordField = frame.getByRole("textbox", { name: "Password" });
  const signInButton  = frame.getByRole("button", { name: /sign in/i });

  await usernameField.waitFor({ state: "visible", timeout: 60_000 });
  await usernameField.fill(username);
  await usernameField.press("Tab");
  await passwordField.fill(password);
  await signInButton.click();
}

// Trigger the Mattermost SSO flow the way a real user does: navigate to
// the login page, then click the "SSO with Infinito.Nexus" button that
// templates/javascript.js.j2 injects via MutationObserver. This verifies
// end-to-end that (a) the login form mounts, (b) the injection fires,
// (c) the rendered button carries the right href and (d) the click
// kicks off the Keycloak OIDC round-trip. Direct navigation to
// /oauth/gitlab/login would skip (a)-(c) and silently hide button
// regressions; if the user cannot click their way through, the test
// should fail.
//
// Mattermost v11 redirects fresh browser contexts (no cookies) from
// /login to /landing before the login form renders. We bounce back to
// /login until the form (#input_loginId) actually mounts, so the
// injection has an anchor.
async function startMattermostSsoFlow(page, baseUrl) {
  const base = baseUrl.replace(/\/$/, "");
  await page.goto(`${base}/login`);
  if (page.url().includes("/landing")) {
    await page.goto(`${base}/login`);
  }

  // Wait for the login form to mount before looking for the SSO button.
  // The injection's MutationObserver only fires once #input_loginId
  // exists, so racing the button query against form-mount is what
  // caused the original 30s timeouts on fresh contexts.
  await page
    .locator("#input_loginId")
    .waitFor({ state: "visible", timeout: 30_000 });

  const ssoButton = page.locator("a[href='/oauth/gitlab/login']");
  await ssoButton.waitFor({ state: "visible", timeout: 30_000 });
  await ssoButton.click();
}

// Dismiss Mattermost onboarding modals/tips that may appear after first SSO login.
async function dismissMattermostPopups(frame) {
  const dismissSelectors = [
    // Existing selectors
    frame.getByRole("button", { name: /next|done|skip|got it|close|ok/i }),
    frame.locator("[aria-label='Close'], .modal-header .close, button.close"),
    // NEW: Target the specific onboarding overlay causing the intercept error
    frame.locator("[data-cy='onboarding-task-list-overlay']"),
    frame.locator(".onboarding-tour-tip__close"),
    // "Welcome to Mattermost" onboarding card on first DM open — its
    // dismiss button reads "No thanks, I'll figure it out myself".
    frame.getByRole("button", { name: /no thanks/i }),
    frame.getByText(/no thanks, i'?ll figure it out/i),
  ];

  for (let round = 0; round < 3; round++) {
    for (const sel of dismissSelectors) {
      if (await sel.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        // If it's the overlay itself, we might need to click a specific 'X' or 'Skip' inside it
        // but often clicking the element or pressing Escape works.
        await sel.first().click({ force: true }).catch(() => {});
        await new Promise(r => setTimeout(r, 500));
      }
    }

    // Forcefully hide the onboarding root if it persists via CSS 
    // (This is a 'hammer' approach if the click fails)
    await frame.evaluate(() => {
      document.querySelectorAll("[data-cy='onboarding-task-list-overlay']").forEach(el => el.remove());
      document.querySelectorAll("#root-portal").forEach(el => el.style.display = 'none');
    }).catch(() => {});

    await frame.locator("body").press("Escape").catch(() => {});
    await new Promise(r => setTimeout(r, 500));
  }
}

// Wait for Mattermost's main channel view to finish loading.
// Returns the first visible indicator (channel sidebar or Town Square link).
async function waitForMattermostChannelView(frame, timeout = 60_000) {
  const channelSidebar = frame.locator(
    ".SidebarChannel, [data-testid='channel_sidebar'], #sidebar-left, .SidebarNavContainer"
  );
  const townSquare = frame.getByText("Town Square");

  return waitForFirstVisible([channelSidebar, townSquare], timeout);
}

// Log out via the universal logout endpoint.
// Every app's nginx vhost intercepts `location = /logout` and proxies it to
// web-svc-logout, which terminates all active sessions across all apps.
// Using `waitUntil: 'commit'` avoids net::ERR_ABORTED from the multi-domain
// redirect chain the service triggers after invalidating the session.
async function mattermostLogout(page, baseUrl) {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/logout`, { waitUntil: "commit" }).catch(() => {});
}

test.beforeEach(() => {
  expect(oidcIssuerUrl,     "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(mattermostBaseUrl, "MATTERMOST_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername,     "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword,     "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername,     "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword,     "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
});

// Scenario 0: /metricz on the prometheus domain exposes metrics for Mattermost.
//
// Mattermost declares prometheus as a shared service dependency. When prometheus is
// deployed alongside Mattermost, lua-resty-prometheus records per-request metrics for
// the Mattermost vhost and exposes them via the single /metricz scrape endpoint on the
// prometheus domain. This test verifies the end-to-end contract:
//   1. /metricz returns HTTP 200 with prometheus text-format content.
//   2. The response contains at least one metric line labeled app="web-app-mattermost",
//      confirming that Mattermost's vhost is tracked by the shared metrics dict.
//
// /metricz is intentionally unauthenticated — prometheus must scrape it without
// bearer tokens or OAuth2. If this test returns 401/403, the nginx ACL whitelist
// for /metricz is misconfigured.
test("metricz endpoint exposes mattermost metrics when prometheus is loaded as dependency", async ({ request }) => {
  const metriczUrl = `${prometheusBaseUrl.replace(/\/$/, "")}/metricz`;

  const response = await request.get(metriczUrl);

  if (response.status() === 404) {
    test.skip(true, "/metricz returned 404 — prometheus nginx vhost not deployed in this CI run (deploy web-app-prometheus explicitly to enable this test)");
    return;
  }

  expect(
    response.status(),
    `/metricz must return 200 — got ${response.status()}. ` +
    "If 401/403, the nginx ACL whitelist for /metricz is misconfigured."
  ).toBe(200);

  const body = await response.text();

  // Prometheus text format always begins comment lines with '#'.
  expect(body, "/metricz response must be prometheus text format (lines starting with #)").toMatch(/^#/m);

  // At least one metric must carry the Mattermost app label, confirming the vhost
  // is tracked in the shared lua-resty-prometheus memory dict.
  expect(
    body,
    `/metricz must contain metrics labeled app="web-app-mattermost" — ` +
    "if missing, the Mattermost vhost is not registered in lua-resty-prometheus."
  ).toContain('app="web-app-mattermost"');
});

// Scenario I: Prometheus scrapes Mattermost native metrics — the mattermost job target is up.
//
// When native_metrics.enabled=true in the Mattermost inventory, Mattermost exposes /metrics
// on a dedicated listener port (MM_METRICSSETTINGS_LISTENADDRESS). Prometheus scrapes it
// via an internal port binding (host.docker.internal:PORT) rather than going through
// nginx/OAuth2. This test authenticates against Prometheus via SSO and queries the
// Prometheus HTTP API to confirm the mattermost job has at least one UP target (value=1).
//
// The test is skipped when:
//   - PROMETHEUS_BASE_URL or OIDC_ISSUER_URL are unset (prometheus not deployed)
//   - The query returns no results (native_metrics.enabled=false in this deployment)
test("prometheus scrapes mattermost native metrics — job target is up", async ({ browser, request }) => {
  const metriczPreflight = await request.get(`${prometheusBaseUrl.replace(/\/$/, "")}/metricz`);
  if (metriczPreflight.status() === 404) {
    test.skip(true, "Prometheus nginx vhost not deployed in this CI run (deploy web-app-prometheus explicitly to enable this test)");
    return;
  }

  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });

  try {
    const page = await ctx.newPage();

    // Navigate to prometheus — triggers SSO redirect to Keycloak.
    await page.goto(prometheusBaseUrl);

    await expect
      .poll(() => page.url(), {
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC issuer: ${oidcIssuerUrl}`
      })
      .toContain(oidcIssuerUrl);

    await performOidcLogin(page, adminUsername, adminPassword);

    await expect
      .poll(() => page.url(), {
        timeout: 30_000,
        message: `Expected redirect back to Prometheus: ${prometheusBaseUrl}`
      })
      .toContain(prometheusBaseUrl.replace(/\/$/, ""));

    // Query the Prometheus HTTP API for the mattermost job's up metric.
    const queryUrl = `${prometheusBaseUrl.replace(/\/$/, "")}/api/v1/query?query=up%7Bjob%3D%22mattermost%22%7D`;
    const response = await ctx.request.get(queryUrl);

    expect(
      response.ok(),
      `Prometheus API returned ${response.status()} — expected 200.`
    ).toBeTruthy();

    const data = await response.json();

    expect(
      data.status,
      `Prometheus API response status must be "success", got: ${data.status}`
    ).toBe("success");

    const results = data.data.result;

    if (results.length === 0) {
      test.skip(true, "No mattermost job in Prometheus — native_metrics.enabled=false in this deployment");
      return;
    }

    const value = parseFloat(results[0].value[1]);

    expect(
      value,
      `Prometheus up{job="mattermost"} must be 1 (target UP) — got ${value}. ` +
      "If 0, the Mattermost container is down or the internal port binding is broken."
    ).toBe(1);

  } finally {
    await ctx.close().catch(() => {});
  }
});

// Scenario II: dashboard → click Mattermost → verify iframe → SSO login → verify channel view → logout
//
// The SSO flow runs through `startMattermostSsoFlow`, which clicks the
// "SSO with Infinito.Nexus" button injected by templates/javascript.js.j2.
// This covers both the UI (is the button rendered for the user?) and
// the OIDC plumbing (does the click trigger the Keycloak round-trip?)
// in one assertion path; a button regression fails this test before
// the OIDC code is even reached.
test("dashboard to mattermost: sso login, verify channel view, logout", async ({ page }) => {
  const expectedOidcAuthUrl       = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedMattermostBaseUrl = mattermostBaseUrl.replace(/\/$/, "");

  // 1. Navigate to dashboard and click Mattermost app link
  await page.goto("/");
  await page.getByRole("link", { name: "Explore Mattermost" }).click();

  // 2. Verify the Mattermost iframe is present on the dashboard (confirms dashboard integration)
  await expect(page.locator("#main iframe")).toBeVisible();

  // 3. Trigger SSO by navigating directly to the GitLab OAuth2 endpoint
  await startMattermostSsoFlow(page, expectedMattermostBaseUrl);

  // 4. Wait for redirect to Keycloak OIDC auth
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected redirect to Keycloak OIDC: ${expectedOidcAuthUrl}`
    })
    .toContain(expectedOidcAuthUrl);

  // 5. Fill credentials and sign in via Keycloak
  await performOidcLogin(page, adminUsername, adminPassword);

  // 6. Wait for redirect back to Mattermost after successful auth
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected redirect back to Mattermost: ${expectedMattermostBaseUrl}`
    })
    .toContain(expectedMattermostBaseUrl);

  // 7. Dismiss any onboarding popups that appear after first SSO login
  await dismissMattermostPopups(page);

  // 8. Verify logged in — channel sidebar or Town Square must be visible
  await waitForMattermostChannelView(page, 30_000);

  // 9. Logout via API — session is invalidated without going through the nginx /logout
  // intercept that routes to the universal-logout service.
  await mattermostLogout(page, expectedMattermostBaseUrl);

  // 10. Verify the session is gone — Mattermost should redirect to login or landing
  // for unauthenticated requests. In Mattermost v11+ the default unauthenticated
  // redirect is /landing#/ rather than /login.
  await page.goto(`${expectedMattermostBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: 15_000,
      message: "Expected Mattermost to redirect to /login or /landing after logout"
    })
    .toMatch(/\/(login|landing)/);

  await page.goto("/");
});

// Scenario III: biber logs in → sends direct message to administrator → administrator logs in
//              (separate browser) → verifies message → both log out
//
// Using isolated browser contexts models two separate users on separate machines:
// no shared cookies, no shared Keycloak SSO session.
test("mattermost: biber sends direct message to administrator, administrator receives it", async ({ browser }) => {
  const expectedOidcAuthUrl       = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedMattermostBaseUrl = mattermostBaseUrl.replace(/\/$/, "");
  const testMessage               = `Playwright test ${Date.now()}`;

  // Separate contexts = separate browser profiles (no shared cookies or SSO session)
  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });

  try {
    // --- Part 1: biber logs in and sends a direct message to administrator ---

    const biberPage = await biberContext.newPage();

    // Trigger SSO directly — bypasses /landing app-selection dialog for fresh contexts
    await startMattermostSsoFlow(biberPage, expectedMattermostBaseUrl);

    // Wait for redirect to Keycloak OIDC auth page
    await expect
      .poll(() => biberPage.url(), {
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC: ${expectedOidcAuthUrl}`
      })
      .toContain(expectedOidcAuthUrl);

    await performOidcLogin(biberPage, biberUsername, biberPassword);

    // Wait for redirect back to Mattermost (any path under the base URL)
    await expect
      .poll(() => biberPage.url(), {
        timeout: 60_000,
        message: "Expected redirect back to Mattermost after biber login"
      })
      .toContain(expectedMattermostBaseUrl);

    // Dismiss onboarding popups that appear for new SSO users
    await dismissMattermostPopups(biberPage);

    // Open DM with administrator by navigating directly to the DM URL.
    // On first login biber has no team membership and lands on /select_team —
    // navigating to /{team}/messages/@{username} auto-joins the open team and
    // opens the DM in one step, so waitForMattermostChannelView is not needed here.
    // Mattermost v11 supports /{team}/messages/@{username} — more reliable than
    // clicking the sidebar "New DM" button whose aria-label changed across versions.
    await biberPage.goto(`${expectedMattermostBaseUrl}/main/messages/@${adminUsername}`);

    // Re-dismiss popups after navigation: opening the DM channel for the
    // first time triggers the "Welcome to Mattermost" onboarding card,
    // which intercepts Enter-key submission of the post composer.
    await dismissMattermostPopups(biberPage);

    // Wait for the DM channel to open — message input must be visible
    const messageInput = biberPage
      .locator("#post_textbox, [data-testid='post_textbox'], div[contenteditable='true'].post-create__input")
      .first();

    await messageInput.waitFor({ state: "visible", timeout: 30_000 });
    await messageInput.click({ force: true });
    // Use keyboard.type() rather than fill() — Mattermost's rich-text editor is a
    // contenteditable div and fill() bypasses React's onChange handlers, leaving the
    // component state empty even though the text is visible in the DOM.
    await biberPage.keyboard.type(testMessage);

    // Send the message (Enter key submits; Shift+Enter inserts a newline)
    await biberPage.keyboard.press("Enter");

    // Confirm the message appears in the channel.
    // getByTestId('postContent') scopes to the post body, avoiding strict-mode
    // violations from Mattermost's screen-reader <span> that duplicates the text.
    await expect(biberPage.getByTestId("postContent").getByText(testMessage)).toBeVisible({ timeout: 15_000 });

    // Logout as biber
    await mattermostLogout(biberPage, expectedMattermostBaseUrl);

    // --- Part 2: administrator logs in and verifies the direct message (fresh browser context) ---

    const adminPage = await adminContext.newPage();

    // Trigger SSO directly — bypasses /landing app-selection dialog for fresh contexts
    await startMattermostSsoFlow(adminPage, expectedMattermostBaseUrl);

    await expect
      .poll(() => adminPage.url(), {
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC: ${expectedOidcAuthUrl}`
      })
      .toContain(expectedOidcAuthUrl);

    await performOidcLogin(adminPage, adminUsername, adminPassword);

    await expect
      .poll(() => adminPage.url(), {
        timeout: 60_000,
        message: "Expected redirect back to Mattermost after admin login"
      })
      .toContain(expectedMattermostBaseUrl);

    await dismissMattermostPopups(adminPage);
    await waitForMattermostChannelView(adminPage, 30_000);

    // Open DM with biber by navigating directly to the DM URL.
    await adminPage.goto(`${expectedMattermostBaseUrl}/main/messages/@${biberUsername}`);

    // Verify biber's message is visible in the DM channel
    await expect(adminPage.getByTestId("postContent").getByText(testMessage)).toBeVisible({ timeout: 30_000 });

    // Logout as administrator
    await mattermostLogout(adminPage, expectedMattermostBaseUrl);

  } finally {
    await biberContext.close().catch(() => {});
    await adminContext.close().catch(() => {});
  }
});
