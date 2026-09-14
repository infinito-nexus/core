const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, findFirstVisibleCandidate, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const {
  getNextcloudShellCandidates,
  waitForFirstVisible,
  trackServerErrors,
  waitForVisibleCandidate,
  dismissBlockingNextcloudModals,
  clickWithModalRetry,
} = require("./_page");

const loginUsername = decodeDotenvQuotedValue(process.env.LOGIN_USERNAME);
const loginPassword = decodeDotenvQuotedValue(process.env.LOGIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const nextcloudDirectLoginPassword = decodeDotenvQuotedValue(process.env.NEXTCLOUD_DIRECT_LOGIN_PASSWORD) || loginPassword;
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const nextcloudBaseUrl = decodeDotenvQuotedValue(process.env.NEXTCLOUD_BASE_URL);
const mastodonBaseUrl = decodeDotenvQuotedValue(process.env.MASTODON_BASE_URL);
const moodleBaseUrl = decodeDotenvQuotedValue(process.env.MOODLE_BASE_URL);
const peertubeBaseUrl = decodeDotenvQuotedValue(process.env.PEERTUBE_BASE_URL);
const xwikiBaseUrl = decodeDotenvQuotedValue(process.env.XWIKI_BASE_URL);
const nextcloudUsernameFieldPattern = /account name(?: or email)?|username(?: or email)?/i;
const nextcloudCredentialSubmitPattern = /^(sign in|log in)$/i;

const nextcloudOidcEnabled = isServiceEnabled("sso");
const nextcloudLdapEnabled = isServiceEnabled("ldap");
const nextcloudLoginFlavor = !nextcloudOidcEnabled
  ? "native"
  : nextcloudLdapEnabled
    ? "oidc_login"
    : "sociallogin";

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

async function attemptStandaloneNextcloudLogin(adminPage, username, password) {
  const loginUrl = new URL("login", nextcloudBaseUrl).toString();
  const usernameField = adminPage.getByRole("textbox", { name: nextcloudUsernameFieldPattern });
  const passwordField = adminPage.locator('input[name="password"], input[type="password"]').first();
  const signInButton = adminPage.getByRole("button", { name: nextcloudCredentialSubmitPattern });
  const standaloneShellCandidates = getNextcloudShellCandidates(adminPage);

  trackServerErrors(adminPage);

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
    resolveTimeout(60_000),
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
      resolveTimeout(60_000),
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
  await signInButton.click({ timeout: resolveTimeout(30_000) });

  const postLoginState = await waitForVisibleCandidate(
    adminPage,
    standaloneShellCandidates,
    resolveTimeout(120_000),
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
  await clickWithModalRetry(adminPage, adminPage, userMenuTrigger);

  const logoutLink = await waitForFirstVisible(
    adminPage,
    [logoutLinkByName, logoutLinkByHref],
    15_000
  );
  await expect(logoutLink).toBeVisible();
  await logoutLink.click({ timeout: resolveTimeout(30_000) });

  const logoutConfirmationVisible = await logoutConfirmButton
    .first()
    .waitFor({ state: "visible", timeout: resolveTimeout(10_000) })
    .then(() => true)
    .catch(() => false);
  if (logoutConfirmationVisible) {
    await logoutConfirmButton.click();
  }

  await adminPage.waitForLoadState("networkidle", { timeout: resolveTimeout(45_000) }).catch(() => {});
}

async function loginToStandaloneNextcloud(adminPage, username = loginUsername, password = loginPassword) {
  try {
    await attemptStandaloneNextcloudLogin(adminPage, username, password);
    return;
  } catch (first) {
    await adminPage.waitForTimeout(resolveTimeout(5_000));
    try {
      await attemptStandaloneNextcloudLogin(adminPage, username, password);
    } catch (second) {
      second.message += `\n\nThe first attempt failed with: ${first.message}`;
      throw second;
    }
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
    mastodonBaseUrl,
    moodleBaseUrl,
    peertubeBaseUrl,
    xwikiBaseUrl,
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
  clickWithModalRetry,
  loginToStandaloneNextcloud,
  logoutStandaloneNextcloud,
  findFirstVisibleCandidate,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};
