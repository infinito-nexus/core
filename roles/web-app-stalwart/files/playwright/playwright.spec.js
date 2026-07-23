const { test, expect } = require("@playwright/test");

const {
  decodeDotenvQuotedValue,
  performKeycloakLoginForm,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  safeSkipUnlessEnabled,
} = require("./personas");

// Stalwart e2e — mirrors web-app-mailu: WebAdmin TLS smoke, SSO login, biber ->
// admin send/receive via Roundcube, and the shared persona flows. SSO scenarios
// run when SSO_SERVICE_ENABLED; personas gated by PERSONA_*_BLOCKED.
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = decodeDotenvQuotedValue(process.env.APP_BASE_URL || "").replace(/\/+$/, "");
const webmailBaseUrl = decodeDotenvQuotedValue(process.env.WEBMAIL_BASE_URL || "").replace(/\/+$/, "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME || "");
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || "");

// Roundcube auto-redirects to Keycloak (oauth_login_redirect); drive the login
// form, then wait for the mail UI.
async function roundcubeSsoLogin(page, username, password) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  await page.goto(`${webmailBaseUrl}/`);
  const ssoButton = page
    .getByRole("button", { name: /sso|single sign.?on|login with|openid/i })
    .or(page.getByRole("link", { name: /sso|single sign.?on|login with|openid/i }));
  if (await ssoButton.first().isVisible({ timeout: 5_000 }).catch(() => false)) {
    await ssoButton.first().click();
  }
  await expect
    .poll(() => page.url(), {
      timeout: 30_000,
      message: `Expected redirect to Keycloak OIDC: ${expectedOidcAuthUrl}`,
    })
    .toContain(expectedOidcAuthUrl);
  await performKeycloakLoginForm(page, username, password);
  await page.locator("#messagelist, .compose, a[href*='_action=compose'], .toolbar").first()
    .waitFor({ state: "visible", timeout: 60_000 });
}

// Logout MUST exist and work — a missing control is a failure, not a skip.
async function roundcubeLogout(page) {
  const logout = page.locator("a[href*='_task=logout'], a[href*='logout'], a.logout")
    .or(page.getByRole("link", { name: /logout|sign out/i }));
  await expect(logout.first(), "Roundcube logout control must be present").toBeVisible({
    timeout: 10_000,
  });
  await logout.first().click();
}

// Wait for a delivered mail in the recipient's mailbox — accept Inbox OR Junk (the
// .test env has no mail-auth DNS, so Stalwart files authenticated mail under Junk).
// Folders are switched by _mbox URL to avoid clicking a non-actionable folder link.
async function waitForEmailInMailbox(page, webmailBaseUrl, subjectText, timeout = 90_000) {
  const deadline = Date.now() + timeout;
  const mailboxes = ["INBOX", "Junk Mail"];
  const rowFor = () =>
    page.locator("#messagelist tbody tr, table.messagelist tbody tr").filter({ hasText: subjectText }).first();
  while (Date.now() < deadline) {
    for (const mbox of mailboxes) {
      await page
        .goto(`${webmailBaseUrl}/?_task=mail&_mbox=${encodeURIComponent(mbox)}`, { waitUntil: "domcontentloaded" })
        .catch(() => {});
      await page.waitForTimeout(2_000);
      if (await rowFor().isVisible().catch(() => false)) return rowFor();
    }
  }
  throw new Error(`Timed out waiting for email "${subjectText}" in ${mailboxes.join(" / ")}`);
}

test.beforeEach(() => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
});

// Baseline: WebAdmin is served on the canonical domain with TLS.
test("stalwart: WebAdmin is served under canonical domain with TLS", async ({ page }) => {
  const response = await page.goto(`${appBaseUrl}/`);
  expect(response, "Expected Stalwart response").toBeTruthy();
  expect(response.status(), "Expected status < 400").toBeLessThan(400);
  expect(response.url().includes(canonicalDomain), `Expected canonical domain "${canonicalDomain}"`).toBe(true);
  expect(response.headers()["strict-transport-security"], "Stalwart must emit HSTS").toBeTruthy();
});

// CalDAV/CardDAV auto-discovery is reachable through the proxy (.well-known -> /dav/*).
test("stalwart: CalDAV/CardDAV discovery is reachable", async ({ request }) => {
  for (const [wk, path] of [["caldav", "/dav/cal"], ["carddav", "/dav/card"]]) {
    const res = await request.get(`${appBaseUrl}/.well-known/${wk}`, { maxRedirects: 0 });
    expect([301, 302, 307, 308].includes(res.status()),
      `${wk} well-known must redirect (got ${res.status()})`).toBe(true);
    expect(res.headers()["location"] || "", `${wk} should point at ${path}`).toContain("/dav/");
  }
});

// Scenario I: SSO login -> WebAdmin -> logout.
// WebAdmin is a username-first OAuth flow: enter the email, and (the mail domain
// being bound to our OIDC directory) the webui redirects to Keycloak. There is no
// static SSO link, so we type the email first, then drive the Keycloak form.
test("stalwart: sso login, open WebAdmin, logout", async ({ page }) => {
  safeSkipUnlessEnabled("sso");
  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;

  await page.goto(`${appBaseUrl}/`);
  // WebAdmin SPA routes the unauthenticated admin to its own /account/login.
  await expect.poll(() => page.url(), { timeout: 30_000 }).toContain(`${canonicalDomain}/account/login`);

  // Enter the admin email; the webui discovers the OIDC provider and redirects.
  const loginField = page
    .getByRole("textbox", { name: /email|user|login/i })
    .or(page.locator("input[type='email'], input[type='text'], input[name='username'], input[name='email']"))
    .first();
  await loginField.waitFor({ state: "visible", timeout: 30_000 });
  await loginField.fill(adminEmail);
  await page
    .getByRole("button", { name: /continue|next|log ?in|sign ?in/i })
    .or(page.locator("button[type='submit']"))
    .first()
    .click();

  await expect.poll(() => page.url(), { timeout: 60_000 }).toContain(expectedOidcAuthUrl);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: 60_000 }).toContain(canonicalDomain);

  // WebAdmin chrome confirms the authenticated admin session.
  await expect(
    page.locator("nav, .sidebar, [class*='menu'], h1, h2").filter({ hasText: /dashboard|domains|account|settings|directory/i }).first()
  ).toBeVisible({ timeout: 30_000 });

  // The WebAdmin SPA keeps logout behind its account menu — no stable direct
  // control exists on the page (verified in CI), so click it only when exposed.
  // Hard logout coverage lives in the Roundcube scenarios (roundcubeLogout).
  const logout = page.locator("a[href*='logout'], button:has-text('Logout')").or(page.getByRole("link", { name: /logout/i }));
  if (await logout.first().isVisible({ timeout: 5_000 }).catch(() => false)) {
    await logout.first().click();
  }
});

// Scenario II: biber -> administrator send/receive through the Roundcube webmail UI.
// Login is via Keycloak SSO (Roundcube XOAUTH2 -> Stalwart), mirroring web-app-mailu.
// biber and the administrator are separate people: isolated browser contexts.
test("stalwart: biber sends to administrator, administrator receives it", async ({ browser }) => {
  safeSkipUnlessEnabled("sso");
  // The env template always renders these — a missing value is a rendering
  // regression and MUST fail, not silently skip the flagship scenario.
  expect(webmailBaseUrl, "WEBMAIL_BASE_URL must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const testSubject = `Playwright stalwart ${Date.now()}`;
  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });

  try {
    const biberPage = await biberContext.newPage();
    await roundcubeSsoLogin(biberPage, biberUsername, biberPassword);
    await biberPage.goto(`${webmailBaseUrl}/?_task=mail&_action=compose`);
    await biberPage.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await biberPage.locator("#_to, input[name='_to']").first().fill(adminEmail);
    await biberPage.locator("#compose-subject, input[name='_subject']").first().fill(testSubject);
    await biberPage.locator("#composebody, textarea[name='_message'], [contenteditable='true']").first()
      .fill("Hello Administrator, this is an automated Playwright test email.");
    await biberPage.locator(".formbuttons .send, button.send, a.send").first().click();
    // Roundcube (Elastic, framed) sends via AJAX: it may stay on the compose URL and
    // just show a toast. Surface an SMTP error immediately if one appears; otherwise
    // the real proof of a successful send is receipt in the admin inbox below.
    const sendError = biberPage.locator("#messagestack .error, .toast .error, .toast-error").first();
    if (await sendError.isVisible({ timeout: 15_000 }).catch(() => false)) {
      throw new Error(`Roundcube reported a send error: ${await sendError.textContent()}`);
    }
    await roundcubeLogout(biberPage);

    const adminPage = await adminContext.newPage();
    await roundcubeSsoLogin(adminPage, adminUsername, adminPassword);
    const emailRow = await waitForEmailInMailbox(adminPage, webmailBaseUrl, testSubject, 90_000);
    await expect(emailRow).toBeVisible();
    await emailRow.click();
    await expect(
      adminPage.locator("#messagecontframe, #mailview-right, .message-part").first()
    ).toBeVisible({ timeout: 15_000 });
    await roundcubeLogout(adminPage);
  } finally {
    await biberContext.close().catch(() => {});
    await adminContext.close().catch(() => {});
  }
});

// Shared persona flows (gated by PERSONA_*_BLOCKED in templates/playwright.env.j2).
test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const link = interactivePage
        .getByRole("link", { name: /^(domains|accounts|directory|settings|dashboard)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /domains|accounts|directory|settings|dashboard/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
