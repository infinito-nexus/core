const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { gotoOnion, isAuthChain, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { performKeycloakLoginForm } = require("./personas/utils/keycloak");
const { isServiceEnabled } = require("./service-gating");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const ssoEnabled = isServiceEnabled("sso");

const signInAffordance = (page) => page.getByText(/^\s*(log\s?in|sign\s?in)\s*$/i).first();

const hostOf = (page) => {
  try {
    return new URL(page.url()).hostname;
  } catch {
    return "";
  }
};
const onIdentityProvider = (page) => isAuthChain(page.url()) && hostOf(page) !== canonicalDomain;
const backOnApp = (page) => hostOf(page) === canonicalDomain && !isAuthChain(page.url());

async function signIn(page, label, username, password) {
  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/login`, { waitUntil: "domcontentloaded" });

  if (ssoEnabled) {
    await expect
      .poll(() => onIdentityProvider(page), {
        timeout: resolveTimeout(60_000),
        message: "the oauth2 ACL protects /login, so the proxy must hand the persona to Keycloak",
      })
      .toBe(true);
    await performKeycloakLoginForm(page, username, password);
    await expect
      .poll(() => backOnApp(page), {
        timeout: resolveTimeout(60_000),
        message: `the oauth2 proxy gates /login, so Keycloak must hand back to ${canonicalDomain}`,
      })
      .toBe(true);
  }

  const passwordField = page.locator("input[type='password']:visible").first();
  await expect(
    passwordField,
    "Funkwhale serves its own sign-in form on /login; the proxy only gates the route, it does not create an application session",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });

  await page
    .locator("input[autocomplete='username']:visible, input[type='text']:visible, input[type='email']:visible")
    .first()
    .fill(username);
  await passwordField.fill(password);
  await passwordField.press("Enter");

  await expect(
    signInAffordance(page),
    `the sidebar must stop offering sign-in once ${label} holds a Funkwhale session`,
  ).toBeHidden({ timeout: resolveTimeout(60_000) });
}

async function signOut(page, label) {
  const signOutControl = page
    .getByRole("link", { name: /log\s?out|sign\s?out/i })
    .or(page.getByRole("button", { name: /log\s?out|sign\s?out/i }))
    .first();
  const signOutReachable = await signOutControl
    .waitFor({ state: "visible", timeout: resolveTimeout(10_000) })
    .then(() => true)
    .catch(() => false);
  if (signOutReachable) {
    await signOutControl.click();
  } else {
    await gotoOnion(page, `${appBaseUrl}/logout`, { waitUntil: "domcontentloaded" });
  }

  const confirmSignOut = page.getByRole("button", { name: /(log|sign)\s?(me\s?)?out/i }).first();
  const confirmReachable = await confirmSignOut
    .waitFor({ state: "visible", timeout: resolveTimeout(10_000) })
    .then(() => true)
    .catch(() => false);
  if (confirmReachable) {
    await Promise.all([
      page
        .waitForResponse(
          (r) => r.url().includes("/api/v2/users/logout") && r.request().method() === "POST",
          { timeout: resolveTimeout(15_000) },
        )
        .catch(() => null),
      confirmSignOut.click(),
    ]);
  }

  await gotoOnion(page, appBaseUrl, { waitUntil: "domcontentloaded" });

  await expect(
    signInAffordance(page),
    `after sign-out Funkwhale must offer sign-in to ${label} again`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function currentUser(page) {
  const url = `${appBaseUrl}/api/v2/users/me/`;
  const response = await page.request.get(url);
  expect(response.ok(), `GET ${url} answered ${response.status()}`).toBe(true);
  return response.json();
}

module.exports = { appBaseUrl, signIn, signOut, currentUser };
