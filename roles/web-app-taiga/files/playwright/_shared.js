// Shared Taiga Playwright spec state: env vars, locator helpers, login/
// logout flow, themed-surface assertions, and the `beforeEach` env-presence
// guard. `playwright.spec.js` wires the lifecycle hook and `require()`s one
// test module per scenario so each test stays atomar.

const { expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, escapeRegex, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const loginUsername = decodeDotenvQuotedValue(process.env.LOGIN_USERNAME);
const loginPassword = decodeDotenvQuotedValue(process.env.LOGIN_PASSWORD);
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const oidcButtonText = decodeDotenvQuotedValue(process.env.OIDC_BUTTON_TEXT);
const taigaBaseUrl = decodeDotenvQuotedValue(process.env.TAIGA_BASE_URL);
const taigaOauth2Enabled = isServiceEnabled("oauth2");
const taigaOidcEnabled = isServiceEnabled("oidc");

async function findFirstVisible(locators) {
  for (const locator of locators) {
    const candidate = locator.first();

    if (await candidate.isVisible().catch(() => false)) {
      return candidate;
    }
  }

  return null;
}

async function getOauth2ProxyCookies(page, baseUrl) {
  const cookies = await page.context().cookies(baseUrl);
  return cookies.filter((cookie) => /oauth2/i.test(cookie.name));
}

function getOidcEntryLocators(target) {
  const oidcLabelPattern = oidcButtonText
    ? new RegExp(escapeRegex(oidcButtonText), "i")
    : /oidc|single sign-on|sso/i;

  return [
    target.getByRole("link", { name: oidcLabelPattern }),
    target.getByRole("button", { name: oidcLabelPattern }),
    target.locator('[href*="/oidc"], [data-href*="/oidc"], [ui-sref*="oidc"], [ng-click*="oidc"]')
  ];
}

async function waitForOauth2ProxyCookie(page, baseUrl, shouldExist, timeout, errorMessage) {
  await expect
    .poll(
      async () => {
        const oauth2Cookies = await getOauth2ProxyCookies(page, baseUrl);
        return oauth2Cookies.length > 0;
      },
      {
        timeout,
        message: errorMessage
      }
    )
    .toBe(shouldExist);
}

async function activateLocatorClick(locator) {
  const target = locator.first();
  const count = await target.count().catch(() => 0);

  if (!count) {
    return false;
  }

  try {
    await target.dispatchEvent("click");
  } catch {
    await target.evaluate((el) => el.click());
  }

  return true;
}

async function tryLogoutFromTaiga(page, taigaFrame) {
  const directLogoutLocators = [
    taigaFrame.locator('a[title="Logout"]'),
    taigaFrame.locator('a[ng-click*="logout"]'),
    taigaFrame.locator('a[href*="logout"]'),
    taigaFrame.locator('[tg-nav*="logout"]'),
    taigaFrame.getByRole("link", { name: /log ?out/i }),
    taigaFrame.getByRole("button", { name: /log ?out/i }),
    taigaFrame.locator('[href*="logout"], [ui-sref*="logout"], [ng-click*="logout"]')
  ];
  const menuTriggerLocators = [
    taigaFrame.locator("[aria-haspopup='true']"),
    taigaFrame.locator("nav button"),
    taigaFrame.locator(".user-avatar, .avatar, .profile-avatar, .profile-button, [class*='avatar']")
  ];

  for (const directLogoutLocator of directLogoutLocators) {
    if (await activateLocatorClick(directLogoutLocator)) {
      await page.waitForTimeout(1_000);
      return true;
    }
  }

  const directLogout = await findFirstVisible(directLogoutLocators);
  if (directLogout) {
    await directLogout.click({ timeout: 2_000 }).catch(() => {});
    await page.waitForTimeout(1_000);
    return true;
  }

  for (const triggerLocator of menuTriggerLocators) {
    const trigger = await findFirstVisible([triggerLocator]);

    if (!trigger) {
      continue;
    }

    await trigger.click({ timeout: 2_000 }).catch(() => {});
    await page.waitForTimeout(500);

    const revealedLogout = await findFirstVisible(directLogoutLocators);
    if (revealedLogout) {
      await revealedLogout.click({ timeout: 2_000 }).catch(() => {});
      await page.waitForTimeout(1_000);
      return true;
    }
  }

  return false;
}

async function waitForAuthenticatedTaigaShell(frameOrPage, timeout, errorMessage) {
  await expect
    .poll(
      async () => {
        const bodyText = await frameOrPage.locator("body").innerText().catch(() => "");
        const loginFormVisible = await frameOrPage
          .locator("input[name='username'], input#username, input[name='password'], input#password, #kc-login")
          .first()
          .isVisible()
          .catch(() => false);

        if (loginFormVisible) {
          return false;
        }

        return bodyText.length > 100 && /taiga|projects|kanban|backlog|discover/i.test(bodyText);
      },
      {
        timeout,
        message: errorMessage
      }
    )
    .toBe(true);
}

async function waitForTopLevelLoginRequirement(
  page,
  expectedTaigaBaseUrl,
  expectedOidcAuthUrl,
  timeout,
  errorMessage
) {
  const deadline = Date.now() + timeout;
  const keycloakUsernameField = page.locator("input[name='username'], input#username");

  while (Date.now() < deadline) {
    const currentUrl = page.url();

    if (
      currentUrl.includes(expectedOidcAuthUrl) &&
      (await keycloakUsernameField.first().isVisible().catch(() => false))
    ) {
      return { kind: "keycloak" };
    }

    if (currentUrl.includes(expectedTaigaBaseUrl)) {
      const loginEntry = await findFirstVisible([
        page.getByRole("link", { name: /^Login$/i }),
        page.getByRole("button", { name: /^Login$/i })
      ]);

      if (loginEntry) {
        return { kind: "taiga-login-page", locator: loginEntry };
      }

      const oidcEntry = await findFirstVisible(getOidcEntryLocators(page));

      if (oidcEntry) {
        return { kind: "taiga-oidc-entry", locator: oidcEntry };
      }
    }

    await page.waitForTimeout(500);
  }

  throw new Error(errorMessage);
}

function getTaigaUrls() {
  const expectedTaigaBaseUrl = taigaBaseUrl.replace(/\/$/, "");
  const expectedOidcAuthUrl = oidcIssuerUrl
    ? `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`
    : "";

  return {
    expectedTaigaBaseUrl,
    expectedOidcAuthUrl,
    taigaOauth2SignOutUrl: `${expectedTaigaBaseUrl}/oauth2/sign_out`,
    discoverUrl: `${expectedTaigaBaseUrl}/discover`,
    projectsUrl: `${expectedTaigaBaseUrl}/projects`,
    userSettingsUrl: `${expectedTaigaBaseUrl}/user-settings/user-profile`
  };
}

async function getComputedStyleValue(locator, propertyName) {
  return locator
    .first()
    .evaluate((element, cssProperty) => getComputedStyle(element).getPropertyValue(cssProperty), propertyName);
}

async function expectGradientBackground(locator, message) {
  await expect(locator.first()).toBeVisible({ timeout: 60_000 });
  await expect
    .poll(
      async () => getComputedStyleValue(locator, "background-image"),
      {
        timeout: 60_000,
        message
      }
    )
    .toMatch(/gradient/i);
}

async function loginToTaiga(page) {
  const taigaUrls = getTaigaUrls();

  // Navigate directly to Taiga's login route. Hitting `/` auto-redirects to
  // `/discover` (a public showcase that exposes only a top-of-page Login
  // link, NOT the SSO button), which made the detector classify the page
  // as `taiga-login-page`, click the bare Login link, then immediately
  // expect the Keycloak username field — never re-detecting the SSO
  // entry on `/login`. Going straight to `/login` puts us on the page
  // that actually renders the OIDC button so the directive's click
  // handler is bound by the time we click.
  await page.goto(`${taigaUrls.expectedTaigaBaseUrl}/login`);

  if (taigaOauth2Enabled) {
    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: `Expected Taiga to navigate to Keycloak auth via oauth2-proxy: ${taigaUrls.expectedOidcAuthUrl}`
      })
      .toContain(taigaUrls.expectedOidcAuthUrl);
  } else {
    const initialAuthState = await waitForTopLevelLoginRequirement(
      page,
      taigaUrls.expectedTaigaBaseUrl,
      taigaUrls.expectedOidcAuthUrl,
      60_000,
      "Expected Taiga to expose either the Taiga OIDC entry point or the Keycloak login page"
    );

    if (initialAuthState.kind === "taiga-oidc-entry") {
      await initialAuthState.locator.click();
      await expect
        .poll(() => page.url(), {
          timeout: 60_000,
          message: `Expected Taiga OIDC login to navigate to Keycloak auth: ${taigaUrls.expectedOidcAuthUrl}`
        })
        .toContain(taigaUrls.expectedOidcAuthUrl);
    } else if (initialAuthState.kind === "taiga-login-page") {
      await initialAuthState.locator.click();
      // The bare Login link routes to `/login`; the OIDC entry only
      // becomes interactive once that view has rendered. Re-detect so
      // we click the SSO entry next, not the keycloak form.
      const ssoEntry = await waitForTopLevelLoginRequirement(
        page,
        taigaUrls.expectedTaigaBaseUrl,
        taigaUrls.expectedOidcAuthUrl,
        60_000,
        "Expected Taiga OIDC entry to appear after the Login link click"
      );
      if (ssoEntry.kind === "taiga-oidc-entry") {
        await ssoEntry.locator.click();
        await expect
          .poll(() => page.url(), {
            timeout: 60_000,
            message: `Expected Taiga OIDC login to navigate to Keycloak auth: ${taigaUrls.expectedOidcAuthUrl}`
          })
          .toContain(taigaUrls.expectedOidcAuthUrl);
      }
    }
  }

  const usernameField = page.locator("input[name='username'], input#username");
  const passwordField = page.locator("input[name='password'], input#password");
  const signInButton = page.locator(
    "input#kc-login, button#kc-login, button[type='submit'], input[type='submit']"
  );

  await expect(usernameField.first()).toBeVisible({ timeout: 60_000 });
  await usernameField.first().fill(loginUsername);
  await passwordField.first().fill(loginPassword);
  await signInButton.first().click();

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected Taiga to redirect back after Keycloak login: ${taigaUrls.expectedTaigaBaseUrl}`
    })
    .toContain(taigaUrls.expectedTaigaBaseUrl);

  if (taigaOauth2Enabled) {
    await waitForOauth2ProxyCookie(
      page,
      taigaUrls.expectedTaigaBaseUrl,
      true,
      60_000,
      "Expected Taiga to establish an oauth2-proxy session after the Keycloak login redirect"
    );
  }

  await waitForAuthenticatedTaigaShell(
    page,
    60_000,
    "Timed out waiting for a signed-in Taiga shell after the Keycloak login redirect"
  );

  return taigaUrls;
}

async function logoutFromTaiga(page, session) {
  if (taigaOauth2Enabled) {
    await page.goto(session.taigaOauth2SignOutUrl);
    await waitForOauth2ProxyCookie(
      page,
      session.expectedTaigaBaseUrl,
      false,
      60_000,
      "Expected Taiga oauth2-proxy session cookie to be cleared after /oauth2/sign_out"
    );
  } else {
    await page.goto(session.expectedTaigaBaseUrl);
    await waitForAuthenticatedTaigaShell(
      page,
      60_000,
      "Timed out waiting for the top-level signed-in Taiga shell before logout"
    );
    await tryLogoutFromTaiga(page, page);
  }

  await page.goto(session.expectedTaigaBaseUrl);

  const loggedOutState = await waitForTopLevelLoginRequirement(
    page,
    session.expectedTaigaBaseUrl,
    session.expectedOidcAuthUrl,
    60_000,
    "Expected logged-out access to Taiga to require a fresh login"
  );

  if (taigaOauth2Enabled) {
    expect(loggedOutState.kind).toBe("keycloak");
    await expect(page.locator("input[name='username'], input#username").first()).toBeVisible({ timeout: 60_000 });
    await expect
      .poll(
        async () => page.url(),
        {
          timeout: 60_000,
          message: "Expected top-level Taiga re-entry to stay on the Keycloak login page after logout"
        }
      )
      .toContain(session.expectedOidcAuthUrl);
    return;
  }

  expect(["keycloak", "taiga-login-page", "taiga-oidc-entry"]).toContain(loggedOutState.kind);

  if (loggedOutState.kind === "keycloak") {
    await expect(page.locator("input[name='username'], input#username").first()).toBeVisible({ timeout: 60_000 });
    return;
  }

  await expect(loggedOutState.locator).toBeVisible({ timeout: 60_000 });
}

async function reachTopLevelTaigaAuthEntry(page, taigaUrls, timeout, errorMessage) {
  const deadline = Date.now() + timeout;
  let loginClicked = false;

  while (Date.now() < deadline) {
    const currentUrl = page.url();
    const keycloakUsernameField = page.locator("input[name='username'], input#username");

    if (
      currentUrl.includes(taigaUrls.expectedOidcAuthUrl) &&
      (await keycloakUsernameField.first().isVisible().catch(() => false))
    ) {
      return { kind: "keycloak" };
    }

    if (currentUrl.includes(taigaUrls.expectedTaigaBaseUrl)) {
      const oidcEntry = await findFirstVisible(getOidcEntryLocators(page));

      if (oidcEntry) {
        return { kind: "taiga-oidc-entry", locator: oidcEntry };
      }

      const loginEntry = await findFirstVisible([
        page.getByRole("link", { name: /^Login$/i }),
        page.getByRole("button", { name: /^Login$/i })
      ]);

      if (loginEntry && !loginClicked) {
        await loginEntry.click();
        loginClicked = true;
        await page.waitForTimeout(500);
        continue;
      }

      const visibleLocalLoginField = await findFirstVisible([
        page.locator("input[name='username'], input#username"),
        page.locator("input[name='password'], input#password")
      ]);

      if (visibleLocalLoginField) {
        await page.waitForTimeout(1_000);

        const persistedLocalLoginField = await findFirstVisible([
          page.locator("input[name='username'], input#username"),
          page.locator("input[name='password'], input#password")
        ]);

        if (persistedLocalLoginField) {
          return { kind: "taiga-local-login-visible", locator: persistedLocalLoginField };
        }
      }
    }

    await page.waitForTimeout(500);
  }

  throw new Error(errorMessage);
}

function beforeEach() {
  expect(taigaBaseUrl, "TAIGA_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(loginUsername, "LOGIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(loginPassword, "LOGIN_PASSWORD must be set in the Playwright env file").toBeTruthy();

  if (taigaOauth2Enabled || taigaOidcEnabled) {
    expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  }
}

async function loginToTaigaNative(page) {
  const taigaUrls = getTaigaUrls();

  // Variant where neither OIDC nor oauth2 is enabled: Taiga shows its own
  // form (LDAP federation when `loginFormType=ldap`, plain local-DB auth
  // otherwise). The login route stays on Taiga the whole time — no
  // Keycloak round-trip — so the username/password form lives at /login
  // directly.
  await page.goto(`${taigaUrls.expectedTaigaBaseUrl}/login`);

  const usernameField = page.locator("input[name='username'], input#username");
  const passwordField = page.locator("input[name='password'], input#password");
  const signInButton = page.locator(
    "input#kc-login, button#kc-login, button[type='submit'], input[type='submit']",
  );

  await expect(usernameField.first()).toBeVisible({ timeout: 60_000 });
  await usernameField.first().fill(loginUsername);
  await passwordField.first().fill(loginPassword);
  await signInButton.first().click();

  await waitForAuthenticatedTaigaShell(
    page,
    60_000,
    "Timed out waiting for a signed-in Taiga shell after the native login form submit",
  );

  return taigaUrls;
}

async function logoutFromTaigaNative(page, session) {
  await page.goto(session.expectedTaigaBaseUrl);
  await waitForAuthenticatedTaigaShell(
    page,
    60_000,
    "Timed out waiting for the top-level signed-in Taiga shell before native logout",
  );
  await tryLogoutFromTaiga(page, page);

  await page.goto(`${session.expectedTaigaBaseUrl}/login`);
  await expect(page.locator("input[name='username'], input#username").first())
    .toBeVisible({ timeout: 60_000 });
}

module.exports = {
  env: { taigaOauth2Enabled, taigaOidcEnabled },
  skipUnlessServiceEnabled,
  loginToTaiga,
  logoutFromTaiga,
  loginToTaigaNative,
  logoutFromTaigaNative,
  getTaigaUrls,
  expectGradientBackground,
  reachTopLevelTaigaAuthEntry,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};
