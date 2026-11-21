const crypto = require("node:crypto");
const { expect } = require("@playwright/test");

const {
  OIDC_LOGIN_READY_FLAG,
  apiFetchOnion,
  apiGetOnion,
  clickOidcLoginLink,
  decodeDotenvJsonList,
  decodeDotenvQuotedValue,
  gotoOnion,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");
const { isTorUrl } = require("./personas/utils/network");
const { isOnionTarget, resolveTimeout } = require("./timeouts");

const SYNAPSE_IDP = "oidc-keycloak";
const DURATION_UNITS_MS = { s: 1_000, m: 60_000, h: 3_600_000 };
const HEADER = "nav.menu-header";
const RESULT = "#infinito-logout-result";
const RESULT_PARAM = "logout-result";
const KEYCLOAK_LOGIN = "input[name='username'], input#username";
const SSO_BUTTON = /\bsso\b/i;
const XWIKI_SIGNED_IN = /data-xwiki-user-reference="(?:[^"]*[:])?XWiki\.(?!XWikiGuest")/;
const GATED_SESSIONS = {
  "web-app-mediawiki": {
    start: async (page, base) => {
      await gotoOnion(page, `${base}/index.php?title=Special:UserLogin`, { waitUntil: "domcontentloaded" });
      const button = page.getByRole("button", { name: SSO_BUTTON }).first();
      if (await button.isVisible().catch(() => false)) {
        await button.click({ timeout: resolveTimeout(30_000) });
      }
    },
    signedIn: async (request, base) => {
      const response = await apiGetOnion(request, `${base}/api.php?action=query&meta=userinfo&format=json`, {
        maxRedirects: 0,
        timeout: resolveTimeout(30_000),
      });
      return response.status() === 200 && Number((await response.json()).query.userinfo.id) > 0;
    },
  },
  "web-app-xwiki": {
    start: (page, base) => gotoOnion(page, `${base}/bin/login/XWiki/XWikiLogin`, { waitUntil: "domcontentloaded" }),
    signedIn: async (request, base) => {
      const response = await apiGetOnion(request, `${base}/bin/view/Main/`, { timeout: resolveTimeout(30_000) });
      return XWIKI_SIGNED_IN.test(await response.text());
    },
  },
  "web-app-zammad": {
    start: (page, base) => gotoOnion(page, `${base}/auth/openid_connect`, { waitUntil: "domcontentloaded" }),
    signedIn: async (request, base) => {
      const response = await apiGetOnion(request, `${base}/api/v1/users/me`, {
        headers: { Accept: "application/json" },
        maxRedirects: 0,
        timeout: resolveTimeout(30_000),
      });
      return response.status() === 200;
    },
  },
};

/**
 * Return the URLs this pass can reach: the onion pass goes through Tor and
 * reaches every network, the clearnet pass has no Tor proxy.
 *
 * Args:
 *   urls: the URLs of every network the node serves.
 */
function reachableThisPass(urls) {
  return isOnionTarget() ? urls : urls.filter((url) => !isTorUrl(url));
}

const logoutEnv = {
  accountUrl: requireDotenvValue(process.env.KEYCLOAK_ACCOUNT_URL, "KEYCLOAK_ACCOUNT_URL"),
  backchannelTargets: decodeDotenvJsonList(process.env.BACKCHANNEL_TARGETS_JSON, "BACKCHANNEL_TARGETS_JSON"),
  biberPassword: requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD"),
  biberUsername: requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME"),
  clientId: requireDotenvValue(process.env.OIDC_CLIENT_ID, "OIDC_CLIENT_ID"),
  cookieRefresh: requireDotenvValue(process.env.SSO_PROXY_COOKIE_REFRESH, "SSO_PROXY_COOKIE_REFRESH"),
  dashboardUrls: reachableThisPass(decodeDotenvJsonList(process.env.DASHBOARD_URLS_JSON, "DASHBOARD_URLS_JSON")),
  everywhereMarker: requireDotenvValue(process.env.LOGOUT_EVERYWHERE_MARKER, "LOGOUT_EVERYWHERE_MARKER"),
  issuerUrl: requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"),
  logoutUrl: requireDotenvValue(process.env.KEYCLOAK_LOGOUT_URL, "KEYCLOAK_LOGOUT_URL"),
  proxyTargetUrls: reachableThisPass(decodeDotenvJsonList(process.env.PROXY_TARGET_URLS_JSON, "PROXY_TARGET_URLS_JSON")),
  keycloakThemeEnabled: decodeDotenvQuotedValue(process.env.KEYCLOAK_THEME_ENABLED || "") === "true",
  synapseUrl: decodeDotenvQuotedValue(process.env.MATRIX_SYNAPSE_URL || ""),
  tokenUrl:requireDotenvValue(process.env.KEYCLOAK_TOKEN_URL, "KEYCLOAK_TOKEN_URL"),
};

/**
 * Args:
 *   value: an oauth2-proxy duration such as "1m" or "30s".
 */
function durationMs(value) {
  const match = /^(\d+)([smh])$/.exec(value);
  if (!match) throw new Error(`SSO_PROXY_COOKIE_REFRESH ${value} is not a duration of s, m or h`);
  return Number(match[1]) * DURATION_UNITS_MS[match[2]];
}

/**
 * Args:
 *   browser: the Playwright browser.
 *   javaScriptEnabled: whether pages of the context run scripts.
 */
async function openContext(browser, javaScriptEnabled = true) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, javaScriptEnabled });
  context.on("page", (page) => page.on("dialog", (dialog) => dialog.accept().catch(() => {})));
  return context;
}

function dashboardHeader(page) {
  return page.locator(HEADER).first();
}

function accountTrigger(page) {
  return dashboardHeader(page).getByRole("button", { name: /account/i }).first();
}

/**
 * Args:
 *   page: a dashboard page whose header oidc.js has yet to settle.
 */
async function awaitOidcReady(page) {
  await page.waitForFunction((flag) => window[flag] === true, OIDC_LOGIN_READY_FLAG, {
    timeout: resolveTimeout(60_000),
  });
}

/**
 * Args:
 *   page: a page signed in to the dashboard.
 */
async function openAccountMenu(page) {
  await awaitOidcReady(page);
  await accountTrigger(page).click({ timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   page: a dashboard page whose logout redirects back to the dashboard with
 *     the logout result in its query.
 */
async function awaitDashboardReturn(page) {
  const origins = logoutEnv.dashboardUrls.map((url) => new URL(url).origin);
  await page.waitForURL((url) => origins.includes(url.origin) && url.searchParams.has(RESULT_PARAM), {
    timeout: resolveTimeout(180_000),
  });
}

/**
 * Args:
 *   page: a page on the Keycloak logout confirmation page.
 */
async function confirmOnThisDevice(page) {
  await page.locator("#kc-logout").click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("load", { timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: a page the Account menu's "Log out on this device" just navigated.
 */
async function expectConfirmationPageWithBothChoices(page) {
  await page.waitForURL((url) => url.pathname.endsWith(new URL(logoutEnv.logoutUrl).pathname), {
    timeout: resolveTimeout(60_000),
  });
  await expect(page.locator("#kc-logout"), "Log out on this device lands on the confirmation page").toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await expect(page.locator("#kc-logout-everywhere"), "which still offers the other choice").toBeVisible({
    timeout: resolveTimeout(30_000),
  });
}

/**
 * Args:
 *   page: a page of the context to log out.
 */
async function confirmLogoutOnThisDevice(page) {
  await gotoOnion(page, logoutEnv.logoutUrl);
  await confirmOnThisDevice(page);
}

/**
 * Args:
 *   page: a page signed in to the dashboard.
 */
async function logOutThisDeviceFromAccountMenu(page) {
  await chooseFromAccountMenu(page, "device");
  await expectConfirmationPageWithBothChoices(page);
  await confirmOnThisDevice(page);
}

function loginTrigger(page) {
  return dashboardHeader(page).locator("a, button").filter({ hasText: /^\s*login\s*$/i }).first();
}

/**
 * Args:
 *   page: a page of the context that signs in.
 *   dashboardUrl: the dashboard of one network.
 */
async function signInToDashboard(page, dashboardUrl) {
  await gotoOnion(page, dashboardUrl);
  await awaitOidcReady(page);
  if (!(await accountTrigger(page).isVisible())) {
    const trigger = loginTrigger(page);
    const authPage = await clickOidcLoginLink(page, trigger, trigger);
    if (authPage) {
      await performKeycloakLoginForm(authPage, logoutEnv.biberUsername, logoutEnv.biberPassword);
    }
  }
  await expect(accountTrigger(page), `${dashboardUrl}: biber must reach the Account menu`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

/**
 * Args:
 *   page: a page signed in to the dashboard.
 *   choice: "device" or "everywhere".
 */
function accountChoice(page, choice) {
  const name = choice === "device" ? /log\s*out on this device/i : /log\s*out everywhere/i;
  return dashboardHeader(page).getByRole("link", { name });
}

/**
 * Args:
 *   page: a page signed in to the dashboard.
 *   choice: "device" or "everywhere".
 */
async function chooseFromAccountMenu(page, choice) {
  await openAccountMenu(page);
  const link = accountChoice(page, choice);
  await expect(link).toBeVisible({ timeout: resolveTimeout(10_000) });
  await link.click({ timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   page: any page of the context to check.
 *   dashboardUrl: the dashboard of one network.
 */
async function expectDashboardSignedOut(page, dashboardUrl) {
  await gotoOnion(page, dashboardUrl);
  await expect(loginTrigger(page), `${dashboardUrl}: the dashboard must offer Login again`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await expect(accountTrigger(page)).toBeHidden({ timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   page: any page of the context to check.
 *   dashboardUrl: the dashboard of one network.
 */
async function expectDashboardSignedIn(page, dashboardUrl) {
  await gotoOnion(page, dashboardUrl);
  await expect(accountTrigger(page), `${dashboardUrl}: the Keycloak session must still be alive`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

/**
 * Args:
 *   page: a page signed out at the dashboard.
 */
async function expectLoginAsksForCredentials(page) {
  const trigger = loginTrigger(page);
  const authPage = await clickOidcLoginLink(page, trigger, trigger);
  expect(authPage, "the next OIDC authentication must reach Keycloak").toBeTruthy();
  await expect(authPage.locator(KEYCLOAK_LOGIN).first()).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

/**
 * Sign in to Synapse through Keycloak and return the access token of that
 * Synapse session, which is bound to the Keycloak session of the context.
 *
 * Args:
 *   page: a page of the context that signs in.
 */
async function signInToSynapse(page) {
  const base = logoutEnv.synapseUrl.replace(/\/$/, "");
  const landing = `${base}/_matrix/static/`;
  await gotoOnion(page, `${base}/_matrix/client/v3/login/sso/redirect/${SYNAPSE_IDP}?redirectUrl=${encodeURIComponent(landing)}`);
  const username = page.locator(KEYCLOAK_LOGIN).first();
  if (await username.isVisible().catch(() => false)) {
    await performKeycloakLoginForm(page, logoutEnv.biberUsername, logoutEnv.biberPassword, { settle: false });
  }
  const continueLink = page.locator("a[href*='loginToken=']").first();
  await expect
    .poll(async () => page.url().includes("loginToken=") || (await continueLink.isVisible().catch(() => false)), {
      timeout: resolveTimeout(120_000),
      message: "Synapse must hand back a login token after the Keycloak round trip",
    })
    .toBe(true);
  const tokenUrl = page.url().includes("loginToken=") ? page.url() : await continueLink.getAttribute("href");
  const loginToken = new URL(tokenUrl, base).searchParams.get("loginToken");
  const response = await apiFetchOnion(page.request, `${base}/_matrix/client/v3/login`, {
    method: "POST",
    data: { type: "m.login.token", token: loginToken },
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "Synapse must accept its own login token").toBe(200);
  return (await response.json()).access_token;
}

/**
 * Args:
 *   request: an API request context.
 *   accessToken: a Synapse access token.
 */
async function synapseSessionStatus(request, accessToken) {
  const response = await apiFetchOnion(request, `${logoutEnv.synapseUrl.replace(/\/$/, "")}/_matrix/client/v3/account/whoami`, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
    timeout: resolveTimeout(30_000),
  });
  return response.status();
}

/**
 * Args:
 *   request: an API request context.
 *   accessToken: a Synapse access token.
 *   expected: the status the session must answer with.
 */
async function expectSynapseSession(request, accessToken, expected) {
  await expect
    .poll(() => synapseSessionStatus(request, accessToken), {
      timeout: resolveTimeout(60_000),
      message: `the Synapse session must answer whoami with ${expected}`,
    })
    .toBe(expected);
}

/**
 * Return a fresh token set of biber from the shared client, in a Keycloak
 * session of its own that endTokenSession ends.
 *
 * Args:
 *   request: an API request context.
 */
async function biberTokens(request) {
  const response = await apiFetchOnion(request, logoutEnv.tokenUrl, {
    method: "POST",
    form: {
      client_id: logoutEnv.clientId,
      grant_type: "password",
      scope: "openid",
      username: logoutEnv.biberUsername,
      password: logoutEnv.biberPassword,
    },
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "biber must get a fresh token").toBe(200);
  return response.json();
}

/**
 * Args:
 *   request: an API request context.
 *   refreshToken: the refresh token of the session biberTokens opened.
 */
async function endTokenSession(request, refreshToken) {
  await apiFetchOnion(request, logoutEnv.logoutUrl, {
    method: "POST",
    form: { client_id: logoutEnv.clientId, refresh_token: refreshToken },
    timeout: resolveTimeout(30_000),
  }).catch((error) => console.warn(`ending the token session of the check failed: ${error}`));
}

/**
 * Return the applications Keycloak lists for biber, read with a fresh token of
 * biber and the Account REST API.
 *
 * Args:
 *   request: an API request context.
 */
async function accountApplications(request) {
  const { access_token: accessToken, refresh_token: refreshToken } = await biberTokens(request);
  try {
    const response = await apiFetchOnion(request, `${logoutEnv.accountUrl.replace(/\/$/, "")}/applications`, {
      method: "GET",
      headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` },
      timeout: resolveTimeout(30_000),
    });
    expect(response.status(), "the Account REST API must list biber's applications").toBe(200);
    return await response.json();
  } finally {
    await endTokenSession(request, refreshToken);
  }
}

/**
 * Args:
 *   request: an API request context of another device than the one whose
 *     sessions end.
 */
async function endEveryOtherSession(request) {
  const { access_token: accessToken, refresh_token: refreshToken } = await biberTokens(request);
  try {
    const response = await apiFetchOnion(request, `${logoutEnv.accountUrl.replace(/\/$/, "")}/sessions`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
      timeout: resolveTimeout(30_000),
    });
    expect(response.status(), "the Account REST API must end every other session of biber").toBe(204);
  } finally {
    await endTokenSession(request, refreshToken);
  }
}

/**
 * Returns:
 *   One entry per deployed application behind the logout gate and network
 *   this pass reaches: its id, its base URL on that network and its sign-in
 *   start and session probe from GATED_SESSIONS.
 */
function gatedAppSessions() {
  return logoutEnv.backchannelTargets
    .filter((target) => target.sealed_url)
    .flatMap((target) => {
      const session = GATED_SESSIONS[target.id];
      if (!session) {
        throw new Error(`${target.id} sits behind the logout gate, but GATED_SESSIONS names no sign-in and session probe for it`);
      }
      return reachableThisPass(target.app_urls).map((url) => ({ id: target.id, base: url.replace(/\/$/, ""), session }));
    });
}

/**
 * Args:
 *   page: a page of the context whose app session is probed.
 *   gated: one entry of gatedAppSessions().
 *   alive: whether the app session must be alive.
 */
async function expectGatedSession(page, gated, alive) {
  await expect
    .poll(() => gated.session.signedIn(page.request, gated.base), {
      timeout: resolveTimeout(60_000),
      message: `${gated.id} on ${gated.base}: the app session must be ${alive ? "alive" : "gone"}`,
    })
    .toBe(alive);
}

/**
 * Args:
 *   page: a page of the context that signs in.
 *   gated: one entry of gatedAppSessions().
 */
async function signInToGatedApp(page, gated) {
  await gated.session.start(page, gated.base);
  const form = page.locator(KEYCLOAK_LOGIN).first();
  await expect
    .poll(async () => (await form.isVisible().catch(() => false)) || (await gated.session.signedIn(page.request, gated.base)), {
      timeout: resolveTimeout(120_000),
      message: `${gated.id} on ${gated.base}: the sign-in must reach the Keycloak form or come back signed in`,
    })
    .toBe(true);
  if (await form.isVisible().catch(() => false)) {
    await performKeycloakLoginForm(page, logoutEnv.biberUsername, logoutEnv.biberPassword);
  }
  await expectGatedSession(page, gated, true);
}

/**
 * Args:
 *   page: a page of the context whose Keycloak session ended.
 *   gated: one entry of gatedAppSessions().
 */
async function expectGatedAppAsksForLogin(page, gated) {
  await expectGatedSession(page, gated, false);
  await gated.session.start(page, gated.base);
  await expect(page.locator(KEYCLOAK_LOGIN).first(), `${gated.id} on ${gated.base}: the next sign-in must ask for credentials`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

function base64url(value) {
  return Buffer.from(typeof value === "string" ? value : JSON.stringify(value)).toString("base64url");
}

/**
 * Return a logout token signed with a key Keycloak never published.
 *
 * Args:
 *   audience: the client id the token pretends to be for.
 *   overrides: claims that replace the valid ones, such as a foreign `iss`.
 */
function forgedLogoutToken(audience, overrides = {}) {
  const { privateKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
  const now = Math.floor(Date.now() / 1000);
  const header = base64url({ alg: "RS256", typ: "logout+jwt", kid: crypto.randomUUID() });
  const claims = base64url({
    iss: logoutEnv.issuerUrl,
    aud: audience,
    iat: now,
    exp: now + 120,
    jti: crypto.randomUUID(),
    sid: crypto.randomUUID(),
    events: { "http://schemas.openid.net/event/backchannel-logout": {} },
    ...overrides,
  });
  const signature = crypto.sign("sha256", Buffer.from(`${header}.${claims}`), privateKey).toString("base64url");
  return `${header}.${claims}.${signature}`;
}

module.exports = {
  KEYCLOAK_LOGIN,
  RESULT,
  accountApplications,
  accountChoice,
  awaitDashboardReturn,
  biberTokens,
  chooseFromAccountMenu,
  confirmLogoutOnThisDevice,
  durationMs,
  endEveryOtherSession,
  endTokenSession,
  expectDashboardSignedIn,
  expectDashboardSignedOut,
  expectGatedAppAsksForLogin,
  expectGatedSession,
  expectLoginAsksForCredentials,
  expectSynapseSession,
  forgedLogoutToken,
  gatedAppSessions,
  logOutThisDeviceFromAccountMenu,
  logoutEnv,
  openAccountMenu,
  openContext,
  signInToDashboard,
  signInToGatedApp,
  signInToSynapse,
};
