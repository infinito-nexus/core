const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { assertCspResponseHeader, decodeDotenvQuotedValue, expectNoCspViolations, gotoOnion, installCspViolationObserver, normalizeBaseUrl, performKeycloakLoginForm, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const cspRelated = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
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

const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const bbbBaseUrl = normalizeBaseUrl(process.env.BBB_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(bbbBaseUrl, "BBB_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
  await installCspViolationObserver(page);
});

test("bigbluebutton enforces Content-Security-Policy and exposes canonical domain from applications lookup", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);
  const response = await gotoOnion(page, `${bbbBaseUrl}/`);
  expect(response, "Expected BBB landing response").toBeTruthy();
  expect(response.status(), "Expected BBB landing response to be successful").toBeLessThan(400);
  assertCspResponseHeader(response, "bigbluebutton landing");
  const documentUrl = response.url();
  expect(
    documentUrl.includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the BBB URL`
  ).toBe(true);
  await expectNoCspViolations(page, diagnostics, "bigbluebutton landing");
});

// Log out via the universal logout endpoint. Every app's nginx vhost intercepts
// `location = /logout` and proxies it to web-svc-logout, which terminates both
// the Greenlight session and the Keycloak SSO. `waitUntil: 'commit'` avoids
// stalling on any provider-side teardown.
async function bbbLogout(page, bbbBaseUrl) {
  await gotoOnion(page, `${bbbBaseUrl}/logout`, { waitUntil: "commit" })
    .catch(() => {});
  await page.context().clearCookies();
}

// Greenlight (BBB) auto-submits its SSO form when `?sso=true` is present on the
// SPA root (see greenlight App.jsx#autoSignIn). This is a deterministic SSO
// entry that doesn't depend on React button labels or DOM timing.
async function signInViaBbbOidc(page, username, password, personaLabel) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${bbbBaseUrl}/?sso=true`);

  // Greenlight's autoSignIn (App.jsx) fires on the SPA root when `?sso=true`
  // is present. Older Greenlight versions or first-render races may drop the
  // user on `/signin` instead. Fall back to clicking the explicit OIDC button
  // that Greenlight renders when `OPENID_CONNECT_*` env is set.
  await page
    .waitForURL((u) => u.toString().includes(expectedOidcAuthUrl), { timeout: resolveTimeout(10_000) })
    .catch(async () => {
      const oidcButton = page
        .locator("a, button")
        .filter({ hasText: /sign\s*in\s*with|openid|oidc|sso|single\s*sign[-\s]*on/i })
        .first();
      if (await oidcButton.isVisible({ timeout: resolveTimeout(5_000) }).catch(() => false)) {
        await oidcButton.click().catch(() => {});
      }
    });

  await page.waitForURL((u) => u.toString().includes(expectedOidcAuthUrl), {
    timeout: resolveTimeout(120_000)
  });

  await performKeycloakLoginForm(page, username, password);

  await page.waitForURL((u) => u.toString().startsWith(`${bbbBaseUrl}/`) && !u.toString().includes("/auth/openid_connect") && !u.toString().includes("?sso=true"), {
    timeout: resolveTimeout(120_000)
  });

  // Authenticated Greenlight renders a header "Sign Out" control in the nav
  // menu. The unauthenticated landing has "Sign In" / "Sign Up" buttons and
  // never exposes "Sign Out". This is the load-bearing assertion that
  // distinguishes real auth from a short-circuited navigation.
  await gotoOnion(page, `${bbbBaseUrl}/rooms`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: expected /rooms to remain accessible post-login (not to be redirected to / or /signin)`
    })
    .toMatch(new RegExp(`^${bbbBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/rooms(/|\\?|$)`));
}

async function assertLoggedOut(page, bbbBaseUrl, personaLabel) {
  // After logout, /rooms must no longer render the authenticated shell; the
  // unauthenticated Greenlight landing exposes "Sign In" / "Sign Up" or
  // redirects to the sign-in route.
  await gotoOnion(page, `${bbbBaseUrl}/rooms`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await expect
    .poll(
      async () => {
        const url = page.url();
        if (/\/(signin|login|ldap_signin)(\/|\?|$)/i.test(url)) return "signin";
        const signInVisible = await page
          .getByRole("link", { name: /sign\s*in|log\s*in|anmelden/i })
          .first()
          .isVisible()
          .catch(() => false);
        if (signInVisible) return "signin";
        const signInButtonVisible = await page
          .getByRole("button", { name: /sign\s*in|log\s*in|anmelden/i })
          .first()
          .isVisible()
          .catch(() => false);
        if (signInButtonVisible) return "signin";
        return "pending";
      },
      {
        timeout: resolveTimeout(60_000),
        message: `${personaLabel}: expected bigbluebutton to require a new sign-in after logout`
      }
    )
    .toBe("signin");
}

test("administrator: bigbluebutton OIDC login and logout", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const diagnostics = attachDiagnostics(page);
  await signInViaBbbOidc(page, adminUsername, adminPassword, "administrator");
  await bbbLogout(page, bbbBaseUrl);
  await assertLoggedOut(page, bbbBaseUrl, "administrator");
  await expectNoCspViolations(page, diagnostics, "bigbluebutton administrator OIDC");
});

test("biber: bigbluebutton OIDC login and logout", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const diagnostics = attachDiagnostics(page);
  await signInViaBbbOidc(page, biberUsername, biberPassword, "biber");
  await bbbLogout(page, bbbBaseUrl);
  await assertLoggedOut(page, bbbBaseUrl, "biber");
  await expectNoCspViolations(page, diagnostics, "bigbluebutton biber OIDC");
});


// Persona scenarios.
// Bodies live in the shared persona helpers under
// roles/test-e2e-playwright/files/personas/{guest,biber,admin}.js.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});
