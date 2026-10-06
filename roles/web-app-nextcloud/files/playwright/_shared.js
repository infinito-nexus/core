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
const MINIMAL_DOCX_BASE64 =
  "UEsDBBQAAAAIAEq201x5bjPX6AAAAK0BAAATAAAAW0NvbnRlbnRfVHlwZXNdLnhtbH1QyU7DMBD9FWuuKHHggBCK0wPLETiUDxjZk8SqN3nc0v49Tlt6QIXjzFv1+tXeO7GjzDYGBbdtB4KCjsaGScHn+rV5AMEFg0EXAyk4EMNq6NeHRCyqNrCCuZT0KCXrmTxyGxOFiowxeyz1zJNMqDc4kbzrunupYygUSlMWDxj6Zxpx64p42df3qUcmxyCeTsQlSwGm5KzGUnG5C+ZXSnNOaKvyyOHZJr6pBJBXExbk74Cz7r0Ok60h8YG5vKGvLPkVs5Em6q2vyvZ/mys94zhaTRf94pZy1MRcF/euvSAebfjpL49zD99QSwMECgAAAAAASrbTXAAAAAAAAAAAAAAAAAYAAABfcmVscy9QSwMEFAAAAAgASrbTXJv9N+qtAAAAKQEAAAsAAABfcmVscy8ucmVsc43POw7CMAwG4KtE3mlaBoRQ0y4IqSsqB7ASN61oHkrCo7cnAwNFDIy2f3+W6/ZpZnanECdnBVRFCYysdGqyWsClP232wGJCq3B2lgQsFKFt6jPNmPJKHCcfWTZsFDCm5A+cRzmSwVg4TzZPBhcMplwGzT3KK2ri27Lc8fBpwNpknRIQOlUB6xdP/9huGCZJRydvhmz6ceIrkWUMmpKAhwuKq3e7yCzwpuarF5sXUEsDBAoAAAAAAEq201wAAAAAAAAAAAAAAAAFAAAAd29yZC9QSwMEFAAAAAgASrbTXC5rweurAAAA6wAAABEAAAB3b3JkL2RvY3VtZW50LnhtbEWOQQ7CIBBFr0LYW6oLY5q27jyBHgBhaIkwQ4Bae3uhLty8n8lM3p/++vGOvSEmSzjwY9NyBqhIW5wG/rjfDhfOUpaopSOEgW+Q+HXs106TWjxgZkWAqVsHPuccOiGSmsHL1FAALDtD0ctcxjiJlaIOkRSkVPzeiVPbnoWXFnlVPklvNUNFrMijRWPRZmKEbiNjrAKmaAmuCFhpUq9e1LvKuDPs/LnE/8/xC1BLAQIeAxQAAAAIAEq201x5bjPX6AAAAK0BAAATAAAAAAAAAAEAAACkgQAAAABbQ29udGVudF9UeXBlc10ueG1sUEsBAh4DCgAAAAAASrbTXAAAAAAAAAAAAAAAAAYAAAAAAAAAAAAQAO1BGQEAAF9yZWxzL1BLAQIeAxQAAAAIAEq201yb/TfqrQAAACkBAAALAAAAAAAAAAEAAACkgT0BAABfcmVscy8ucmVsc1BLAQIeAwoAAAAAAEq201wAAAAAAAAAAAAAAAAFAAAAAAAAAAAAEADtQRMCAAB3b3JkL1BLAQIeAxQAAAAIAEq201wua8HrqwAAAOsAAAARAAAAAAAAAAEAAACkgTYCAAB3b3JkL2RvY3VtZW50LnhtbFBLBQYAAAAABQAFACABAAAQAwAAAAA=";
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
  MINIMAL_DOCX_BASE64,
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
