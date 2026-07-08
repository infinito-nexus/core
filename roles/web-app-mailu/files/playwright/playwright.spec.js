const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion, isOnionCanonical, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow, safeSkipUnlessEnabled } = require("./personas");
test.use({
  ignoreHTTPSErrors: true
});

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl  = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const mailuBaseUrl   = decodeDotenvQuotedValue(process.env.MAILU_BASE_URL);
const adminUsername  = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword  = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const adminEmail     = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const biberEmail     = decodeDotenvQuotedValue(process.env.BIBER_EMAIL);

async function waitForFirstVisible(page, locators, timeout = resolveTimeout(60_000)) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    for (const locator of locators) {
      if (await locator.first().isVisible().catch(() => false)) {
        return locator.first();
      }
    }

    await page.waitForTimeout(resolveTimeout(500));
  }

  throw new Error("Timed out waiting for one of the expected selectors to become visible");
}

// Mailu's heviat OIDC fork shows its own /sso/login page with a local login form AND an
// "SSO Login" link that redirects to Keycloak. Click that link specifically.
// Use openid-connect/auth (not just openid-connect) to avoid accidentally clicking the logout
// link (openid-connect/logout) which is also present in the Roundcube interface.
async function clickThroughMailuSsoPage(frame) {
  const oidcLink = frame.locator("a[href*='openid-connect/auth']").first();

  // Over Tor, Matomo link-tracking intercepts the click to fire a beacon that
  // stalls, so the click never commits the navigation; goto the href directly.
  if (isOnionCanonical()) {
    const href = await oidcLink.getAttribute("href", { timeout: resolveTimeout(15_000) }).catch(() => null);
    if (href) {
      await frame.goto(href);
    }
    return;
  }

  if (await oidcLink.isVisible({ timeout: resolveTimeout(3_000) }).catch(() => false)) {
    await oidcLink.click();
  }
}

// Perform SSO login via Keycloak inside a frame context (or page context for direct navigation).
// Works for both iframe-embedded and full-page Mailu flows.

// Wait for an email with the given subject to appear in the current view.
// Retries for up to `timeout` ms to account for delivery delay.
async function waitForEmailInInbox(page, subjectText, timeout = resolveTimeout(60_000)) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    // Roundcube Elastic renders emails as <tr> rows inside #messagelist tbody
    const emailRow = page.locator("#messagelist tbody tr, table.messagelist tbody tr").filter({ hasText: subjectText });

    if (await emailRow.first().isVisible().catch(() => false)) {
      return emailRow.first();
    }

    // Refresh inbox by clicking the inbox folder
    await page.getByRole("link", { name: "Inbox" }).first().click().catch(() => {});
    await page.waitForTimeout(resolveTimeout(3_000));
  }

  throw new Error(`Timed out waiting for email with subject "${subjectText}" to arrive`);
}

test.beforeEach(() => {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(mailuBaseUrl,  "MAILU_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(adminEmail,    "ADMIN_EMAIL must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberEmail,    "BIBER_EMAIL must be set in the Playwright env file").toBeTruthy();
});

// Scenario I: direct mailu → SSO login → webinterface → admin interface → logout
test("mailu: sso login, open admin interface, logout", async ({ page }) => {
  safeSkipUnlessEnabled("sso");
  const expectedOidcAuthUrl  = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedMailuBaseUrl = mailuBaseUrl.replace(/\/$/, "");

  // 1. Navigate directly to Mailu
  await gotoOnion(page, `${expectedMailuBaseUrl}/`);

  // 2. Mailu's SSO fork may land on /sso/login before redirecting to Keycloak — click through it
  await page.waitForTimeout(resolveTimeout(2_000));
  await clickThroughMailuSsoPage(page);

  // 3. Wait for redirect to Keycloak OIDC auth
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `Expected Mailu to navigate to Keycloak OIDC: ${expectedOidcAuthUrl}`
    })
    .toContain(expectedOidcAuthUrl);

  // 4. Fill credentials and sign in via Keycloak
  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  // 5. Wait for redirect back to Mailu webmail
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `Expected Mailu to redirect back after login: ${expectedMailuBaseUrl}`
    })
    .toContain(expectedMailuBaseUrl);

  // 6. Verify logged in — look for compose button or inbox folder link
  const composeButton  = page.getByRole("button", { name: /compose/i });
  const inboxContainer = page.getByRole("link", { name: /inbox/i });

  await waitForFirstVisible(page, [composeButton, inboxContainer], resolveTimeout(30_000));

  // 7. Navigate to the admin interface (admin users see an Administration link or /admin path)
  const adminLink = page.getByRole("link", { name: /administration|admin/i });
  const adminLinkVisible = await adminLink.first().isVisible().catch(() => false);

  if (adminLinkVisible) {
    await adminLink.first().click();
  } else {
    // Fallback: navigate directly to the admin URL
    await gotoOnion(page, `${expectedMailuBaseUrl}/admin`);
  }

  // 8. Verify admin interface loaded — match any heading visible in Mailu's admin panel
  await expect(
    page.locator("h1, h2, h3, .nav-title, .sidebar-heading").filter({ hasText: /administration|domains|user|mail/i }).first()
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  // 9. Logout — Mailu admin logout is a link with /logout or /signout in the href
  const logoutByHref = page.locator("a[href*='logout'], a[href*='signout']");
  const logoutVisible = await logoutByHref.first().isVisible({ timeout: resolveTimeout(5_000) }).catch(() => false);

  if (logoutVisible) {
    await logoutByHref.first().click();
  } else {
    // Fallback: navigate directly to the admin logout endpoint
    await gotoOnion(page, `${expectedMailuBaseUrl}/admin/ui/logout`);
  }
});

// Scenario II: biber logs in → sends email to administrator → administrator logs in
//              (separate browser) → waits for email → logs out
//
// biber and the administrator are two different people on separate machines.
// Using isolated browser contexts models this correctly: no shared cookies, no shared
// Keycloak SSO session. This avoids any logout/session-cleanup race condition entirely.
test("mailu: biber sends email to administrator, administrator receives it", async ({ browser }) => {
  safeSkipUnlessEnabled("sso");
  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const testSubject         = `Playwright test ${Date.now()}`;

  // Separate contexts = separate browser profiles (no shared cookies or SSO session)
  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });

  try {
    // --- Part 1: biber logs in and sends email ---

    const biberPage = await biberContext.newPage();

    await biberPage.goto(mailuBaseUrl);

    // Mailu webmail may show an SSO button or redirect directly to Keycloak
    const ssoButton = biberPage.getByRole("button", { name: /sso|single sign.?on|login with/i });
    const ssoButtonVisible = await ssoButton.first().isVisible({ timeout: resolveTimeout(5_000) }).catch(() => false);

    if (ssoButtonVisible) {
      await ssoButton.first().click();
    }

    // Click through Mailu's own /sso/login intermediate page if present
    await clickThroughMailuSsoPage(biberPage);

    // Wait for Keycloak OIDC auth page
    await expect
      .poll(() => biberPage.url(), {
        timeout: resolveTimeout(30_000),
        message: `Expected redirect to Keycloak OIDC: ${expectedOidcAuthUrl}`
      })
      .toContain(expectedOidcAuthUrl);

    await performKeycloakLoginForm(biberPage, biberUsername, biberPassword);

    // Wait for redirect back to Mailu webmail — require /webmail/ in the URL to confirm
    // the OIDC callback was fully processed and the PHP session cookie was set.
    // Matching only mailuBaseUrl would pass prematurely on the callback URL itself
    // (e.g. /sso/login?code=...) before Mailu finishes the auth-code exchange.
    await expect
      .poll(() => biberPage.url(), {
        timeout: resolveTimeout(60_000),
        message: "Expected redirect back to Mailu webmail after biber login"
      })
      .toContain(`${mailuBaseUrl.replace(/\/$/, "")}/webmail/`);

    // Navigate directly to Roundcube compose URL — clicking the compose button requires
    // rcmail.js to fully execute, direct navigation is more reliable in Playwright.
    // Selectors confirmed from rendered DOM: id="_to", id="compose-subject",
    // id="composebody", button.btn.btn-primary.send inside .formbuttons
    await biberPage.goto(`${mailuBaseUrl.replace(/\/$/, "")}/webmail/?_task=mail&_action=compose`);
    await biberPage.waitForLoadState("networkidle", { timeout: resolveTimeout(15_000) }).catch(() => {});

    const toField      = biberPage.locator("#_to, input[name='_to']").first();
    const subjectField = biberPage.locator("#compose-subject, input[name='_subject']").first();
    const bodyField    = biberPage.locator("#composebody, textarea[name='_message'], [contenteditable='true']").first();
    const sendButton   = biberPage.locator(".formbuttons .send, button.send, a.send");

    await toField.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
    await toField.fill(adminEmail);

    await subjectField.fill(testSubject);
    await bodyField.click();
    await bodyField.fill("Hello Administrator, this is an automated Playwright test email.");

    await sendButton.first().waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
    await sendButton.first().click();

    // After send, Roundcube redirects away from _action=compose
    await expect.poll(() => biberPage.url(), { timeout: resolveTimeout(30_000) })
      .not.toContain("_action=compose");

    // Logout as biber — click the visible Logout button in Roundcube's sidebar
    const biberLogoutLink = biberPage.locator("a[href*='logout'], a[href*='signout']")
      .or(biberPage.getByRole("button", { name: /logout/i }))
      .or(biberPage.getByRole("link", { name: /logout/i }));

    await biberLogoutLink.first().waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
    await biberLogoutLink.first().click();

    // --- Part 2: administrator logs in and checks inbox (fresh browser context) ---

    const adminPage = await adminContext.newPage();

    await adminPage.goto(mailuBaseUrl);

    const ssoButtonAdmin = adminPage.getByRole("button", { name: /sso|single sign.?on|login with/i });
    const ssoAdminVisible = await ssoButtonAdmin.first().isVisible({ timeout: resolveTimeout(5_000) }).catch(() => false);

    if (ssoAdminVisible) {
      await ssoButtonAdmin.first().click();
    }

    // Click through Mailu's own /sso/login intermediate page if present
    await clickThroughMailuSsoPage(adminPage);

    await expect
      .poll(() => adminPage.url(), {
        timeout: resolveTimeout(30_000),
        message: `Expected redirect to Keycloak OIDC: ${expectedOidcAuthUrl}`
      })
      .toContain(expectedOidcAuthUrl);

    await performKeycloakLoginForm(adminPage, adminUsername, adminPassword);

    await expect
      .poll(() => adminPage.url(), {
        timeout: resolveTimeout(60_000),
        message: "Expected redirect back to Mailu webmail after admin login"
      })
      .toContain(`${mailuBaseUrl.replace(/\/$/, "")}/webmail/`);

    // Wait for inbox to load
    const inboxFolder = adminPage.getByRole("link", { name: "Inbox" });

    await inboxFolder.first().waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
    await inboxFolder.first().click();

    // Wait for biber's email to arrive (email delivery may take a few seconds)
    const emailRow = await waitForEmailInInbox(adminPage, testSubject, resolveTimeout(60_000));

    await expect(emailRow).toBeVisible();
    await emailRow.click();

    // Verify email content is visible (Roundcube shows message body in #messagecontframe iframe or preview pane)
    await expect(
      adminPage.locator("#messagecontframe, #mailview-right, .message-part").first()
    ).toBeVisible({ timeout: resolveTimeout(15_000) });

    // Logout as administrator
    const adminLogoutLink = adminPage.locator("a[href*='logout'], a[href*='signout']")
      .or(adminPage.getByRole("button", { name: /logout/i }))
      .or(adminPage.getByRole("link", { name: /logout/i }));

    await adminLogoutLink.first().waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
    await adminLogoutLink.first().click();

  } finally {
    await biberContext.close().catch(() => {});
    await adminContext.close().catch(() => {});
  }
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
      // web-app-mailu admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|administration|domains|users|fetchmail|aliases)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /domains|users|fetchmail|aliases|relays|administration/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
