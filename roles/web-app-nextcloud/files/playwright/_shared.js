const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, findFirstVisibleCandidate, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { isServiceEnabled } = require("./service-gating");

const loginUsername = decodeDotenvQuotedValue(process.env.LOGIN_USERNAME);
const loginPassword = decodeDotenvQuotedValue(process.env.LOGIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const nextcloudDirectLoginPassword = decodeDotenvQuotedValue(process.env.NEXTCLOUD_DIRECT_LOGIN_PASSWORD) || loginPassword;
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const nextcloudBaseUrl = decodeDotenvQuotedValue(process.env.NEXTCLOUD_BASE_URL);
const moodleBaseUrl = decodeDotenvQuotedValue(process.env.MOODLE_BASE_URL);
const peertubeBaseUrl = decodeDotenvQuotedValue(process.env.PEERTUBE_BASE_URL);
const nextcloudUsernameFieldPattern = /account name(?: or email)?|username(?: or email)?/i;
const nextcloudCredentialSubmitPattern = /^(sign in|log in)$/i;

const nextcloudOidcEnabled = isServiceEnabled("sso");
const nextcloudLdapEnabled = isServiceEnabled("ldap");
const nextcloudLoginFlavor = !nextcloudOidcEnabled
  ? "native"
  : nextcloudLdapEnabled
    ? "oidc_login"
    : "sociallogin";

function getNextcloudShellCandidates(target) {
  return [
    {
      kind: "shell",
      locator: target.locator("#app-content-vue, #app-navigation-vue, #app-content, #header-start__appmenu")
    },
    {
      kind: "shell",
      locator: target.locator('a[href*="/apps/files"], a[href*="/apps/dashboard"]')
    }
  ];
}

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

  throw new Error("Timed out waiting for one of the expected Nextcloud selectors to become visible");
}

async function waitForVisibleCandidate(
  page,
  candidates,
  timeout = resolveTimeout(60_000),
  errorMessage = "Timed out waiting for one of the expected Nextcloud selectors to become visible"
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

async function dismissBlockingNextcloudModals(page, nextcloudFrame, maxDismissals = 4) {
  const modalOverlay = nextcloudFrame.locator(
    "#firstrunwizard.modal-mask, #firstrunwizard[role='dialog'], .modal-mask[role='dialog'], [role='dialog'][aria-modal='true']"
  );
  const dismissButtonCandidates = [
    nextcloudFrame.getByRole("button", { name: /^close$/i }),
    nextcloudFrame.getByRole("button", { name: /^schlie(?:ss|ß)en$/i }),
    nextcloudFrame.locator(
      ".modal-mask .modal-container__close, .modal-mask .header-close, [role='dialog'] .modal-container__close, [role='dialog'] .header-close"
    ),
    nextcloudFrame.locator(
      ".modal-mask .next, .modal-mask button[aria-label='Next'], [role='dialog'] .next, [role='dialog'] button[aria-label='Next']"
    ),
    nextcloudFrame.getByRole("button", { name: /skip|not now|later|dismiss|done|got it/i })
  ];
  let stableChecksWithoutModal = 0;

  for (let i = 0; i < maxDismissals; i += 1) {
    if (!(await modalOverlay.first().isVisible().catch(() => false))) {
      stableChecksWithoutModal += 1;
      if (stableChecksWithoutModal >= 2) {
        return;
      }
      await page.waitForTimeout(resolveTimeout(600));
      continue;
    }

    stableChecksWithoutModal = 0;
    let dismissed = false;

    for (const candidate of dismissButtonCandidates) {
      const button = candidate.first();
      if (await button.isVisible().catch(() => false)) {
        await button.click({ timeout: resolveTimeout(2_000) }).catch(() => {});
        dismissed = true;
        break;
      }
    }

    if (!dismissed) {
      await page.keyboard.press("Escape").catch(() => {});
    }

    await page.waitForTimeout(resolveTimeout(300));
  }
}

async function clickUserMenuWithModalRetry(page, nextcloudFrame, userMenuLocator, attempts = 5) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    await dismissBlockingNextcloudModals(page, nextcloudFrame, 6);

    try {
      await userMenuLocator.click({ timeout: resolveTimeout(4_000) });
      return;
    } catch (error) {
      const message = String(error && error.message ? error.message : error);
      const retriable = /intercepts pointer events|timed out|timeout/i.test(message);

      if (!retriable || attempt === attempts) {
        throw error;
      }
      await page.waitForTimeout(resolveTimeout(500));
    }
  }
}

function getNextcloudSocialLoginCandidates(target) {
  return [
    {
      kind: "social-login",
      locator: target.locator(
        'a[href*="/apps/sociallogin/"], a[href*="/custom_oidc/"], a[href*="/apps/oidc_login/"], a.oidc-button, button[formaction*="/apps/sociallogin/"], button[formaction*="/custom_oidc/"]'
      )
    },
    {
      kind: "social-login",
      locator: target.getByRole("link", { name: /log in with|sign in with|continue with|openid connect/i })
    },
    {
      kind: "social-login",
      locator: target.getByRole("button", { name: /log in with|sign in with|continue with|openid connect/i })
    }
  ];
}

async function loginToStandaloneNextcloud(adminPage, username = loginUsername, password = loginPassword) {
  const loginUrl = new URL("login", nextcloudBaseUrl).toString();
  const usernameField = adminPage.getByRole("textbox", { name: nextcloudUsernameFieldPattern });
  const passwordField = adminPage.locator('input[name="password"], input[type="password"]').first();
  const signInButton = adminPage.getByRole("button", { name: nextcloudCredentialSubmitPattern });
  const standaloneShellCandidates = getNextcloudShellCandidates(adminPage);

  await adminPage.goto(loginUrl, {
    waitUntil: "commit",
    timeout: resolveTimeout(60_000)
  }).catch(() => {});

  const credentialCandidates = [
    { kind: "credentials", locator: usernameField },
    { kind: "credentials", locator: signInButton }
  ];
  const socialLoginCandidates = getNextcloudSocialLoginCandidates(adminPage);

  let flavorCandidates;
  let timeoutMessage;
  switch (nextcloudLoginFlavor) {
    case "native":
      flavorCandidates = [...credentialCandidates, ...standaloneShellCandidates];
      timeoutMessage =
        "Timed out waiting for the Nextcloud native credential form or an already-authenticated shell";
      break;
    case "sociallogin":
      flavorCandidates = [
        ...socialLoginCandidates,
        ...credentialCandidates,
        ...standaloneShellCandidates
      ];
      timeoutMessage =
        "Timed out waiting for the Nextcloud social-login entry, the Keycloak credential form, or an already-authenticated shell";
      break;
    case "oidc_login":
    default:
      flavorCandidates = [
        ...credentialCandidates,
        ...socialLoginCandidates,
        ...standaloneShellCandidates
      ];
      timeoutMessage =
        "Timed out waiting for the Keycloak login form, the OIDC alt-login button, or an already-authenticated Nextcloud shell";
      break;
  }

  const initialState = await waitForVisibleCandidate(
    adminPage,
    flavorCandidates,
    60_000,
    timeoutMessage
  );

  if (initialState.kind === "shell") {
    await dismissBlockingNextcloudModals(adminPage, adminPage);
    return;
  }

  if (initialState.kind === "social-login") {
    await initialState.locator.click({ timeout: resolveTimeout(5_000) });
    await waitForVisibleCandidate(
      adminPage,
      [...credentialCandidates, ...standaloneShellCandidates],
      60_000,
      "Timed out waiting for the Keycloak credential form after following the Nextcloud social-login entry"
    );
  }

  const effectiveUsername = username;
  const effectivePassword =
    nextcloudLoginFlavor === "native" && username === loginUsername
      ? nextcloudDirectLoginPassword
      : password;

  await expect(usernameField).toBeVisible();
  await usernameField.click();
  await usernameField.fill(effectiveUsername);
  await usernameField.press("Tab");
  await passwordField.fill(effectivePassword);
  await signInButton.click();

  const postLoginState = await waitForVisibleCandidate(
    adminPage,
    standaloneShellCandidates,
    120_000,
    "Timed out waiting for a signed-in Nextcloud shell after the login redirect"
  );

  await expect(postLoginState.locator).toBeVisible();
  await dismissBlockingNextcloudModals(adminPage, adminPage);
}

async function logoutStandaloneNextcloud(adminPage) {
  const userMenuTrigger = adminPage
    .locator(
      "#user-menu button[aria-label='Settings menu'], #user-menu > button, #user-menu button"
    )
    .first();
  const logoutLinkByName = adminPage.getByRole("link", { name: "Log out" });
  const logoutLinkByHref = adminPage.locator('a[href*="logout"]');
  const logoutConfirmButton = adminPage.getByRole("button", { name: "Logout" });

  await dismissBlockingNextcloudModals(adminPage, adminPage);
  await clickUserMenuWithModalRetry(adminPage, adminPage, userMenuTrigger);

  const logoutLink = await waitForFirstVisible(
    adminPage,
    [logoutLinkByName, logoutLinkByHref],
    15_000
  );
  await expect(logoutLink).toBeVisible();
  await logoutLink.click();

  const logoutConfirmationVisible = await logoutConfirmButton
    .first()
    .waitFor({ state: "visible", timeout: resolveTimeout(10_000) })
    .then(() => true)
    .catch(() => false);
  if (logoutConfirmationVisible) {
    await logoutConfirmButton.click();
  }
}

async function loginToStandaloneNextcloudWithRetry(adminPage, username, password) {
  try {
    await loginToStandaloneNextcloud(adminPage, username, password);
    return;
  } catch {
    await adminPage.waitForTimeout(resolveTimeout(5_000));
    await loginToStandaloneNextcloud(adminPage, username, password);
  }
}

function beforeEach() {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(nextcloudBaseUrl, "NEXTCLOUD_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(loginUsername, "LOGIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(loginPassword, "LOGIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
}

module.exports = {
  env: {
    loginUsername,
    loginPassword,
    biberUsername,
    biberPassword,
    nextcloudBaseUrl,
    moodleBaseUrl,
    peertubeBaseUrl,
    nextcloudUsernameFieldPattern,
    nextcloudCredentialSubmitPattern,
    nextcloudOidcEnabled,
    nextcloudLdapEnabled,
    nextcloudLoginFlavor,
  },
  getNextcloudShellCandidates,
  waitForFirstVisible,
  waitForVisibleCandidate,
  dismissBlockingNextcloudModals,
  clickUserMenuWithModalRetry,
  loginToStandaloneNextcloud,
  logoutStandaloneNextcloud,
  loginToStandaloneNextcloudWithRetry,
  findFirstVisibleCandidate,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};
