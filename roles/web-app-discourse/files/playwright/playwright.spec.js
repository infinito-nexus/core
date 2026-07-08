const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { assertCspMetaParity, assertCspResponseHeader, decodeDotenvQuotedValue, expectNoCspViolations, installCspViolationObserver, normalizeBaseUrl, performKeycloakLoginForm, runGuestFlow, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
test.use({ ignoreHTTPSErrors: true });

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const cspRelated = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }

    if (/content security policy|csp/i.test(message.text())) {
      cspRelated.push({ source: "console", text: message.text() });
    }
  });

  page.on("pageerror", (error) => {
    const text = String(error);
    pageErrors.push(text);

    if (/content security policy|csp/i.test(text)) {
      cspRelated.push({ source: "pageerror", text });
    }
  });

  return { consoleErrors, pageErrors, cspRelated };
}

async function discourseLogout(page, discourseBaseUrl) {
  await page
    .goto(`${discourseBaseUrl}/session/destroy`, { waitUntil: "commit" })
    .catch(() => {});
  await page
    .goto(`${oidcIssuerUrl}/protocol/openid-connect/logout`, { waitUntil: "commit" })
    .catch(() => {});
  await page.context().clearCookies();
}

const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const discourseBaseUrl = normalizeBaseUrl(process.env.DISCOURSE_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(discourseBaseUrl, "DISCOURSE_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

  await page.context().clearCookies();
  await installCspViolationObserver(page);
});

test("discourse enforces Content-Security-Policy and exposes canonical domain from applications lookup", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  const response = await gotoOnion(page, `${discourseBaseUrl}/`);
  expect(response, "Expected discourse landing response").toBeTruthy();
  expect(response.status(), "Expected discourse landing response to be successful").toBeLessThan(400);

  const directives = assertCspResponseHeader(response, "discourse landing");
  await assertCspMetaParity(page, directives, "discourse landing");

  const documentUrl = response.url();
  expect(
    documentUrl.includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" (from applications lookup) to back the discourse URL`
  ).toBe(true);

  await expectNoCspViolations(page, diagnostics, "discourse landing");
});

async function signInViaDashboardOidc(page, username, password, personaLabel) {
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
      message: `${personaLabel}: expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: expected redirect back to discourse at ${discourseBaseUrl}`
    })
    .toContain(discourseBaseUrl);
}

test("administrator: discourse OIDC login and logout", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const diagnostics = attachDiagnostics(page);

  await signInViaDashboardOidc(page, adminUsername, adminPassword, "administrator");

  await expect(page.locator("body")).toContainText(/topic|category|welcome|latest|discourse/i, { timeout: resolveTimeout(60_000) });

  await discourseLogout(page, discourseBaseUrl);

  await gotoOnion(page, `${discourseBaseUrl}/`);
  await expect
    .poll(
      async () =>
        (await page
          .locator("a, button")
          .filter({ hasText: /sign\s*up|log\s*in|anmelden|continue\s+with/i })
          .first()
          .count()
          .catch(() => 0)) > 0,
      {
        timeout: resolveTimeout(60_000),
        message: "Expected discourse to require a new sign-in after logout"
      }
    )
    .toBe(true);

  await expectNoCspViolations(page, diagnostics, "discourse administrator OIDC");
});

test("biber: discourse OIDC login and logout", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const diagnostics = attachDiagnostics(page);

  await signInViaDashboardOidc(page, biberUsername, biberPassword, "biber");

  await expect(page.locator("body")).toContainText(/topic|category|welcome|latest|discourse/i, { timeout: resolveTimeout(60_000) });

  await discourseLogout(page, discourseBaseUrl);

  await gotoOnion(page, `${discourseBaseUrl}/`);
  await expect
    .poll(
      async () =>
        (await page
          .locator("a, button")
          .filter({ hasText: /sign\s*up|log\s*in|anmelden|continue\s+with/i })
          .first()
          .count()
          .catch(() => 0)) > 0,
      {
        timeout: resolveTimeout(60_000),
        message: "Expected discourse to require a new sign-in after logout"
      }
    )
    .toBe(true);

  await expectNoCspViolations(page, diagnostics, "discourse biber OIDC");
});


// Persona scenarios.
// Bodies live in the shared persona helpers under
// roles/test-e2e-playwright/files/personas/{guest,biber,admin}.js.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});
