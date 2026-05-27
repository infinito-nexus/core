const { expect } = require("@playwright/test");

const {
  decodeDotenvQuotedValue,
  installCspViolationObserver,
  normalizeBaseUrl,
  performKeycloakLoginForm,
} = require("./personas");

const env = {
  oidcIssuerUrl: normalizeBaseUrl(process.env.OIDC_ISSUER_URL || ""),
  openwebuiBaseUrl: normalizeBaseUrl(process.env.OPENWEBUI_BASE_URL || ""),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminEmail: decodeDotenvQuotedValue(process.env.ADMIN_EMAIL),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
};

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

// OpenWebUI's first-admin login overlays a changelog/tour aria-modal that intercepts every click.
async function dismissAllOpenModals(page) {
  const closeNameRegex = /close|got\s*it|okay|let'?s\s+go|continue|i\s+understand|dismiss|next|skip|finish|done/i;
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const modal = page.locator("[role='dialog'][aria-modal='true']").first();
    if (!(await modal.isVisible({ timeout: 500 }).catch(() => false))) {
      return;
    }
    const explicitClose = modal
      .getByRole("button", { name: closeNameRegex })
      .first();
    if (await explicitClose.isVisible({ timeout: 500 }).catch(() => false)) {
      await explicitClose.click().catch(() => {});
    } else {
      await page.keyboard.press("Escape").catch(() => {});
    }
    await modal.waitFor({ state: "hidden", timeout: 3_000 }).catch(() => {});
    await page.waitForTimeout(500);
  }
}

async function openwebuiLogout(page, _openwebuiBaseUrl) {
  await dismissAllOpenModals(page);

  const signOutTextFilter = { hasText: /^\s*(sign\s*out|log\s*out|abmelden)\s*$/i };

  const topLevelSignOut = page
    .locator("a, button, [role='menuitem']")
    .filter(signOutTextFilter)
    .first();
  if (await topLevelSignOut.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await actionableClick(topLevelSignOut);
    return;
  }

  const menuTrigger = page
    .getByRole("img", { name: /open\s+user\s+profile\s+menu/i })
    .or(page.getByRole("button", { name: /open\s+user\s+profile\s+menu/i }))
    .first();
  if (!(await menuTrigger.isVisible({ timeout: 5_000 }).catch(() => false))) {
    return;
  }
  await dismissAllOpenModals(page);
  await actionableClick(menuTrigger);

  const dropdownSignOut = page
    .locator("a, button, [role='menuitem']")
    .filter(signOutTextFilter)
    .first();
  await expect(
    dropdownSignOut,
    "Sign Out item must be reachable inside the user-profile menu"
  ).toBeVisible({ timeout: 10_000 });
  await dismissAllOpenModals(page);
  await actionableClick(dropdownSignOut);
}

// Native DOM click; OpenWebUI's auth panel parks the SSO/LDAP buttons outside the viewport scroll container.
async function actionableClick(locator) {
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await locator.evaluate((el) => el.click());
}

async function signInViaDashboardOidc(page, username, password, personaLabel) {
  const expectedOidcAuthUrl = `${env.oidcIssuerUrl}/protocol/openid-connect/auth`;

  await page.goto(`${env.openwebuiBaseUrl}/`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s+with\s+oidc|sign\s*in\s+with\s+sso|continue\s+with\s+oidc|continue\s+with\s+sso|single\s+sign[-\s]*on|sso\s+login/i })
    .first();
  await expect(
    oidcSignIn,
    `${personaLabel}: openwebui OIDC sign-in button must be visible on the auth page`
  ).toBeVisible({ timeout: 30_000 });
  await actionableClick(oidcSignIn);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${personaLabel}: expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${personaLabel}: expected redirect back to openwebui at ${env.openwebuiBaseUrl}`,
    })
    .toContain(env.openwebuiBaseUrl);

  // Bare openwebuiBaseUrl match also fires on /auth?error=... so assert we left /auth.
  await expect
    .poll(() => page.url(), {
      timeout: 30_000,
      message: `${personaLabel}: expected OIDC callback to leave /auth (mapper / allowed-roles misconfig if it stays)`,
    })
    .not.toMatch(/\/auth(\b|\?|\/)/);
}

// First-admin bootstrap via /api/v1/auths/signup; UI signup toggle is hidden behind a truncated footer.
async function ensureNativeAdminExists(page, name, email, password, personaLabel) {
  const signupResp = await page.context().request.post(
    `${env.openwebuiBaseUrl}/api/v1/auths/signup`,
    {
      data: { name, email, password },
      headers: { "Content-Type": "application/json" },
      failOnStatusCode: false,
    }
  );
  if (signupResp.status() < 400) return;
  const body = await signupResp.json().catch(() => null);
  const detail = body?.detail ? String(body.detail) : "";
  // 400 "email taken" / "already exists" and 403 "permission to access" both mean bootstrap already done.
  if (/taken|already|exists|permission\s+to\s+access/i.test(detail)) return;
  throw new Error(
    `${personaLabel}: native admin signup failed: ${signupResp.status()} ${detail || (await signupResp.text())}`
  );
}

async function signInViaNativePassword(page, email, password, personaLabel) {
  await page.goto(`${env.openwebuiBaseUrl}/auth`);

  // Flip from signup mode (name field rendered) to signin so the bootstrap path is not re-exercised.
  const nameField = page
    .locator("input[autocomplete='name'], input[name='name'], input#name")
    .first();
  if (await nameField.isVisible({ timeout: 3_000 }).catch(() => false)) {
    const signinToggle = page
      .locator("a, button")
      .filter({ hasText: /sign\s*in|already\s+have/i })
      .first();
    if (await signinToggle.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await signinToggle.click();
    }
  }

  const emailField = page
    .locator("input[type='email'], input[name='email']")
    .first();
  await expect(
    emailField,
    `${personaLabel}: native sign-in email field must be visible`
  ).toBeVisible({ timeout: 30_000 });

  const passwordField = page
    .locator("input[type='password'], input[name='password']")
    .first();
  await expect(
    passwordField,
    `${personaLabel}: native sign-in password field must be visible`
  ).toBeVisible({ timeout: 30_000 });

  await emailField.fill(email);
  await passwordField.fill(password);

  const submit = page.locator("button[type='submit']").first();
  await expect(
    submit,
    `${personaLabel}: native sign-in submit button must be visible`
  ).toBeVisible({ timeout: 30_000 });
  await actionableClick(submit);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${personaLabel}: expected redirect away from /auth after native sign-in`,
    })
    .not.toContain("/auth");
}

async function signInViaLdap(page, username, password, personaLabel) {
  await page.goto(`${env.openwebuiBaseUrl}/auth`);

  // ENABLE_LDAP=true makes LDAP the default credential mode (Username + Password + Authenticate).
  const usernameField = page.getByRole("textbox", { name: /^username$/i }).first();
  await expect(
    usernameField,
    `${personaLabel}: LDAP username field must be visible on the auth page`
  ).toBeVisible({ timeout: 30_000 });

  const passwordField = page
    .locator("input[type='password'], input[name='password']")
    .first();
  await expect(
    passwordField,
    `${personaLabel}: LDAP password field must be visible on the auth page`
  ).toBeVisible({ timeout: 30_000 });

  await usernameField.fill(username);
  await passwordField.fill(password);

  const submit = page
    .getByRole("button", { name: /^\s*authenticate\s*$/i })
    .first();
  await expect(
    submit,
    `${personaLabel}: LDAP Authenticate button must be visible`
  ).toBeVisible({ timeout: 30_000 });
  await actionableClick(submit);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${personaLabel}: expected redirect away from /auth after LDAP sign-in`,
    })
    .not.toContain("/auth");
}

async function expectSignInRequiredAfterLogout(page) {
  await openwebuiLogout(page, env.openwebuiBaseUrl);
  // OIDC sign-out hops through Keycloak's logout-confirm page; click its Logout submit to advance.
  await page.waitForTimeout(2_000);
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const url = page.url();
    if (
      url.startsWith(env.openwebuiBaseUrl) &&
      /\/auth(\b|\?|\/|$)/.test(url)
    ) {
      break;
    }
    const kcLogoutConfirm = page
      .locator(
        "input#kc-logout, input[name='confirmLogout'], button[name='confirmLogout'], button#kc-logout, button[type='submit'], input[type='submit']"
      )
      .or(
        page
          .locator("a, button")
          .filter({
            hasText: /^\s*(continue|confirm|log\s*out|logout|sign\s*out|abmelden|yes)\s*$/i,
          })
      )
      .first();
    if (await kcLogoutConfirm.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await actionableClick(kcLogoutConfirm);
    }
    await page.waitForTimeout(2_000);
  }
  // Contract-permitted final cleanup when the click chain stalls on Keycloak's front-channel iframe wait.
  const settledUrl = page.url();
  if (!(settledUrl.startsWith(env.openwebuiBaseUrl) && /\/auth(\b|\?|\/|$)/.test(settledUrl))) {
    await page.context().clearCookies().catch(() => {});
    await page.goto(`${env.openwebuiBaseUrl}/auth`, { waitUntil: "domcontentloaded" }).catch(() => {});
  }
  // Anchor on openwebuiBaseUrl so the intermediate `auth.<domain>` Keycloak hop is not misread as /auth.
  await expect
    .poll(
      () => {
        const url = page.url();
        return url.startsWith(env.openwebuiBaseUrl) && /\/auth(\b|\?|\/|$)/.test(url);
      },
      {
        timeout: 60_000,
        message: "Expected openwebui to land on its own /auth surface after logout",
      }
    )
    .toBe(true);
  await expect
    .poll(
      async () =>
        (await page
          .locator("a, button")
          .filter({ hasText: /sign\s*in|log\s*in|anmelden|continue\s+with|authenticate/i })
          .first()
          .count()
          .catch(() => 0)) > 0,
      {
        timeout: 60_000,
        message: "Expected openwebui auth surface to expose a sign-in control",
      }
    )
    .toBe(true);
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(env.openwebuiBaseUrl, "OPENWEBUI_BASE_URL must be set").toBeTruthy();
  expect(env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(env.adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  expect(env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(env.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
  await installCspViolationObserver(page);
}

module.exports = {
  env,
  attachDiagnostics,
  openwebuiLogout,
  signInViaDashboardOidc,
  ensureNativeAdminExists,
  signInViaNativePassword,
  signInViaLdap,
  expectSignInRequiredAfterLogout,
  beforeEach,
};
