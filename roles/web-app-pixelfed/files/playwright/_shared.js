// Shared Pixelfed Playwright spec state: env vars, locator candidates,
// loginToPixelfed/logoutFromPixelfed flow, and the Keycloak-admin email-swap
// setup that lets biber pass pixelfed's `email:strict,…,dns,spoof` validator
// (Egulias rejects `.example` per RFC 2606 before any DNS lookup; without the
// swap, ValidationException → Laravel `back()` → Keycloak Referer → broken
// SSO callback). `playwright.spec.js` wires `beforeAll`/`afterAll`/`beforeEach`
// and `require()`s one test module per test scenario.
const { resolveTimeout } = require("./timeouts");

const { expect, request } = require("@playwright/test");
const { decodeDotenvQuotedValue, findFirstVisibleCandidate, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { isServiceEnabled } = require("./service-gating");

const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const pixelfedBaseUrl = decodeDotenvQuotedValue(process.env.PIXELFED_BASE_URL);

const oidcEnabled = isServiceEnabled("sso");

const kcBaseUrl   = decodeDotenvQuotedValue(process.env.KEYCLOAK_BASE_URL    || "").replace(/\/$/, "");
const kcRealm     = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM       || "");
const kcAdminUser = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_USERNAME || "");
const kcAdminPw   = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_PASSWORD || "");
const biberOidcEmailOverride = decodeDotenvQuotedValue(process.env.BIBER_OIDC_EMAIL_OVERRIDE || "");

// The OIDC self-provisioning path is exercised by the non-reserved
// `biber` first so the bootstrapped administrator (whose name is
// reserved and cannot be created through pixelfed's first-time OIDC
// registration flow) can be validated separately afterwards.
const loginScenarios = [
  {
    label: "biber",
    usernameEnv: "BIBER_USERNAME",
    passwordEnv: "BIBER_PASSWORD",
    username: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
    password: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD)
  },
  {
    label: "administrator",
    usernameEnv: "ADMIN_USERNAME",
    passwordEnv: "ADMIN_PASSWORD",
    username: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
    password: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD)
  }
];

async function waitForFirstVisible(page, locators, timeout = resolveTimeout(60_000), errorMessage = "Timed out waiting for a visible locator") {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    for (const locator of locators) {
      const candidate = locator.first();

      if (await candidate.isVisible().catch(() => false)) {
        return candidate;
      }
    }

    await page.waitForTimeout(resolveTimeout(500));
  }

  throw new Error(errorMessage);
}

async function waitForVisibleCandidate(
  page,
  candidates,
  timeout = resolveTimeout(60_000),
  errorMessage = "Timed out waiting for a visible candidate"
) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    const visibleCandidate = await findFirstVisibleCandidate(candidates);

    if (visibleCandidate) {
      return visibleCandidate;
    }

    await page.waitForTimeout(resolveTimeout(500));
  }

  throw new Error(errorMessage);
}

async function anyVisible(locators) {
  for (const candidate of locators) {
    const locator = candidate.locator || candidate;
    const visibleLocator = typeof locator.first === "function" ? locator.first() : locator;

    if (await visibleLocator.isVisible().catch(() => false)) {
      return true;
    }
  }

  return false;
}

function getPixelfedLoginEntryCandidates(target) {
  return [
    {
      kind: "login-link",
      locator: target.getByRole("link", { name: /^Login$/i })
    },
    {
      kind: "login-button",
      locator: target.getByRole("button", { name: /^Login$/i })
    },
    {
      kind: "login-href",
      locator: target.locator('a[href="/login"], a[title="Login"]')
    }
  ];
}

function getPixelfedOidcEntryCandidates(target) {
  return [
    {
      kind: "oidc-link",
      locator: target.getByRole("link", { name: /^Sign-in with OIDC$/i })
    },
    {
      kind: "oidc-button",
      locator: target.getByRole("button", { name: /^Sign-in with OIDC$/i })
    },
    {
      kind: "oidc-href",
      locator: target.locator('a[href="/auth/oidc/start"]')
    }
  ];
}

function getPixelfedAuthenticatedCandidates(target) {
  return [
    {
      kind: "user-menu",
      locator: target.getByRole("link", { name: /^User Menu$/i })
    },
    {
      kind: "user-menu-button",
      locator: target.getByRole("button", { name: /^User Menu$/i })
    },
    {
      kind: "user-menu-title",
      locator: target.locator('a[title="User Menu"], a[aria-haspopup="true"]')
    },
    {
      kind: "settings",
      locator: target.locator('a[href="/settings/home"], a[href*="/settings/home"]')
    },
    {
      kind: "logout",
      locator: target.locator('a[href="/logout"], a[href*="/logout"]')
    },
    {
      kind: "logout-button",
      locator: target.getByRole("button", { name: /^Logout$/i })
    }
  ];
}

function getPixelfedUserMenuCandidates(target) {
  return getPixelfedAuthenticatedCandidates(target).filter((candidate) =>
    ["user-menu", "user-menu-button", "user-menu-title"].includes(candidate.kind)
  );
}

function getPixelfedLogoutCandidates(target) {
  return getPixelfedAuthenticatedCandidates(target).filter((candidate) =>
    ["logout", "logout-button"].includes(candidate.kind)
  );
}

function getKeycloakLogoutConfirmCandidates(target) {
  return [
    {
      kind: "kc-logout-button",
      locator: target.getByRole("button", { name: /^Logout$/i })
    },
    {
      kind: "kc-logout-submit",
      locator: target.locator('button[type="submit"], input[type="submit"]')
    },
    {
      kind: "kc-logout-form",
      locator: target.locator('form button, form input[type="submit"]')
    }
  ];
}

function getLoggedOutSuccessCandidates(target) {
  return [
    {
      kind: "logged-out-heading",
      locator: target.getByRole("heading", { name: /you are logged out/i })
    },
    {
      kind: "logged-out-text",
      locator: target.getByText(/you are logged out/i)
    },
    {
      kind: "session-ended-text",
      locator: target.getByText(/logged out|session ended|signed out/i)
    }
  ];
}

async function loginToPixelfed(page, loginScenario) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedPixelfedBaseUrl = pixelfedBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedPixelfedBaseUrl}/`);

  if (!page.url().includes(expectedOidcAuthUrl)) {
    let oidcEntry = await waitForVisibleCandidate(
      page,
      getPixelfedOidcEntryCandidates(page),
      5_000
    ).catch(() => null);

    if (!oidcEntry) {
      const loginEntry = await waitForVisibleCandidate(
        page,
        getPixelfedLoginEntryCandidates(page),
        20_000,
        `Timed out waiting for the Pixelfed login entry before starting the OIDC flow for ${loginScenario.label}`
      );
      await loginEntry.locator.click();
      oidcEntry = await waitForVisibleCandidate(
        page,
        getPixelfedOidcEntryCandidates(page),
        20_000,
        `Timed out waiting for the Pixelfed OIDC action for ${loginScenario.label}`
      );
    }

    await oidcEntry.locator.click();
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: `Expected Pixelfed to redirect to Keycloak OIDC for ${loginScenario.label}: ${expectedOidcAuthUrl}`
      })
      .toContain(expectedOidcAuthUrl);
  }

  const usernameField = page.locator('input[name="username"], input#username, input[type="email"]');
  const passwordField = page.locator('input[name="password"], input#password, input[type="password"]');
  const signInButton = page.locator('button[type="submit"], input[type="submit"]');
  const rememberMeCheckbox = page.locator('input[name="rememberMe"], input#rememberMe');

  const visibleUsernameField = await waitForFirstVisible(
    page,
    [usernameField, page.getByRole("textbox", { name: /username|email/i })],
    60_000,
    `Timed out waiting for the Keycloak username field for ${loginScenario.label}`
  );

  await expect(visibleUsernameField).toBeVisible();
  await visibleUsernameField.click();
  await visibleUsernameField.fill(loginScenario.username);
  await passwordField.first().fill(loginScenario.password);

  if (await rememberMeCheckbox.first().isVisible().catch(() => false)) {
    await rememberMeCheckbox.first().check().catch(() => {});
  } else {
    await page.getByText(/remember me/i).click({ timeout: resolveTimeout(2_000) }).catch(() => {});
  }

  const visibleSignInButton = await waitForFirstVisible(
    page,
    [signInButton, page.getByRole("button", { name: /sign in|log in|login/i })],
    30_000,
    `Timed out waiting for the Keycloak sign-in button for ${loginScenario.label}`
  );

  await visibleSignInButton.click();

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `Expected to redirect back to Pixelfed after Keycloak login for ${loginScenario.label}: ${expectedPixelfedBaseUrl}`
    })
    .toMatch(new RegExp(`^${expectedPixelfedBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));

  const authenticatedState = await waitForVisibleCandidate(
    page,
    getPixelfedAuthenticatedCandidates(page),
    60_000,
    `Timed out waiting for an authenticated Pixelfed UI after the Keycloak login redirect for ${loginScenario.label}`
  );

  await expect(authenticatedState.locator).toBeVisible();
}

async function confirmKeycloakLogoutIfNeeded(page, loginScenario) {
  const expectedOidcLogoutIndicator = "/protocol/openid-connect/logout";
  const deadline = Date.now() + 20_000;

  while (Date.now() < deadline) {
    const looksLikeKeycloakLogout = page.url().includes(expectedOidcLogoutIndicator);

    const visibleConfirm = await waitForVisibleCandidate(
      page,
      getKeycloakLogoutConfirmCandidates(page),
      2_000,
      `Timed out waiting for the Keycloak logout confirmation button for ${loginScenario.label}`
    ).catch(() => null);

    if (looksLikeKeycloakLogout || visibleConfirm) {
      const confirmButton = visibleConfirm || await waitForVisibleCandidate(
        page,
        getKeycloakLogoutConfirmCandidates(page),
        5_000,
        `Timed out waiting for the Keycloak logout confirmation button for ${loginScenario.label}`
      );

      await confirmButton.locator.click().catch(() => {});
      return true;
    }

    const loggedOutSuccessVisible = await anyVisible(getLoggedOutSuccessCandidates(page));
    const pixelfedLoginVisible = await anyVisible(getPixelfedLoginEntryCandidates(page));

    if (loggedOutSuccessVisible || pixelfedLoginVisible) {
      return false;
    }

    await page.waitForTimeout(resolveTimeout(500));
  }

  return false;
}

async function logoutFromPixelfed(page, loginScenario) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;

  let logoutTrigger = await waitForVisibleCandidate(
    page,
    getPixelfedLogoutCandidates(page),
    10_000,
    `Timed out waiting for the Pixelfed Logout action after login for ${loginScenario.label}`
  ).catch(() => null);

  if (!logoutTrigger) {
    const userMenuTrigger = await waitForVisibleCandidate(
      page,
      getPixelfedUserMenuCandidates(page),
      10_000,
      `Timed out waiting for the Pixelfed User Menu after login for ${loginScenario.label}`
    );

    await userMenuTrigger.locator.click();

    logoutTrigger = await waitForVisibleCandidate(
      page,
      getPixelfedLogoutCandidates(page),
      10_000,
      `Timed out waiting for the Pixelfed Logout action after opening the User Menu for ${loginScenario.label}`
    );
  }

  await logoutTrigger.locator.click();

  await confirmKeycloakLogoutIfNeeded(page, loginScenario).catch(() => false);

  await expect
    .poll(
      async () => {
        const loginCandidates = getPixelfedLoginEntryCandidates(page);
        const logoutCandidates = getPixelfedLogoutCandidates(page);
        const loggedOutSuccessCandidates = getLoggedOutSuccessCandidates(page);
        const currentUrl = page.url();

        const pixelfedLoginVisible = await anyVisible(loginCandidates);
        const pixelfedLogoutVisible = await anyVisible(logoutCandidates);
        const loggedOutSuccessVisible = await anyVisible(loggedOutSuccessCandidates);
        const backOnLoginProvider = currentUrl.includes(expectedOidcAuthUrl);

        const loggedOutStateReached =
          pixelfedLoginVisible ||
          loggedOutSuccessVisible ||
          backOnLoginProvider;

        return loggedOutStateReached && !pixelfedLogoutVisible;
      },
      {
        timeout: resolveTimeout(60_000),
        message: `Expected Pixelfed to return to a logged-out state after logout for ${loginScenario.label}`
      }
    )
    .toBe(true);
}

async function keycloakAdminToken(api) {
  const tokenResp = await api.post(
    `${kcBaseUrl}/realms/master/protocol/openid-connect/token`,
    {
      form: {
        client_id: "admin-cli",
        username: kcAdminUser,
        password: kcAdminPw,
        grant_type: "password",
      },
    },
  );
  if (!tokenResp.ok()) {
    throw new Error(`Keycloak admin token failed: ${tokenResp.status()} ${await tokenResp.text()}`);
  }
  return (await tokenResp.json()).access_token;
}

async function getKeycloakUser(api, auth, username) {
  const usersResp = await api.get(
    `${kcBaseUrl}/admin/realms/${kcRealm}/users?username=${encodeURIComponent(username)}&exact=true`,
    { headers: auth },
  );
  if (!usersResp.ok()) {
    throw new Error(`Keycloak user lookup failed for ${username}: ${usersResp.status()} ${await usersResp.text()}`);
  }
  const users = await usersResp.json();
  if (!users.length) {
    throw new Error(`Keycloak user '${username}' not found in realm ${kcRealm}`);
  }
  return users[0];
}

async function updateKeycloakUserEmail(username, newEmail, emailVerified) {
  // Returns the previous {email, emailVerified} so the caller can restore it.
  const api = await request.newContext({ ignoreHTTPSErrors: true });
  try {
    const token = await keycloakAdminToken(api);
    const auth = { Authorization: `Bearer ${token}` };
    const user = await getKeycloakUser(api, auth, username);
    const original = { email: user.email, emailVerified: user.emailVerified };
    const putResp = await api.put(
      `${kcBaseUrl}/admin/realms/${kcRealm}/users/${user.id}`,
      {
        headers: { ...auth, "Content-Type": "application/json" },
        data: { ...user, email: newEmail, emailVerified: emailVerified },
      },
    );
    if (!putResp.ok()) {
      throw new Error(`Keycloak user email update for ${username} failed: ${putResp.status()} ${await putResp.text()}`);
    }
    return original;
  } finally {
    await api.dispose();
  }
}

const state = { biberOriginalKeycloakProfile: null };

async function beforeAll() {
  if (!oidcEnabled) {
    return;
  }
  expect(kcBaseUrl,   "KEYCLOAK_BASE_URL must be set when OIDC is enabled").toBeTruthy();
  expect(kcRealm,     "KEYCLOAK_REALM must be set when OIDC is enabled").toBeTruthy();
  expect(kcAdminUser, "KEYCLOAK_ADMIN_USERNAME must be set when OIDC is enabled").toBeTruthy();
  expect(kcAdminPw,   "KEYCLOAK_ADMIN_PASSWORD must be set when OIDC is enabled").toBeTruthy();
  expect(biberOidcEmailOverride, "BIBER_OIDC_EMAIL_OVERRIDE must be set when OIDC is enabled").toBeTruthy();
  state.biberOriginalKeycloakProfile = await updateKeycloakUserEmail(
    decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
    biberOidcEmailOverride,
    true,
  );
}

async function afterAll() {
  if (!oidcEnabled || state.biberOriginalKeycloakProfile === null) {
    return;
  }
  await updateKeycloakUserEmail(
    decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
    state.biberOriginalKeycloakProfile.email,
    state.biberOriginalKeycloakProfile.emailVerified,
  );
}

function beforeEach() {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(pixelfedBaseUrl, "PIXELFED_BASE_URL must be set in the Playwright env file").toBeTruthy();

  for (const loginScenario of loginScenarios) {
    expect(
      loginScenario.username,
      `${loginScenario.usernameEnv} must be set in the Playwright env file`
    ).toBeTruthy();
    expect(
      loginScenario.password,
      `${loginScenario.passwordEnv} must be set in the Playwright env file`
    ).toBeTruthy();
  }
}

module.exports = {
  env: { oidcEnabled, oidcIssuerUrl, pixelfedBaseUrl },
  loginScenarios,
  loginToPixelfed,
  logoutFromPixelfed,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeAll,
  afterAll,
  beforeEach,
};
