const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const oidcEnabled = process.env.LOGIN_METHOD_SSO_ENABLED === "true";
const SSO_ENTRY = "a[href^='/oauth/gitlab/login']";

const loginMethods = {
  native: process.env.LOGIN_METHOD_NATIVE_ENABLED === "true",
  registration: process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true",
};
const nativeForm = loginMethods.native && !oidcEnabled;
const NATIVE_FORM_PARTS = [
  ".login-body-card-form > .Input_container",
  ".login-body-card-form > .login-body-card-form-link",
  ".login-body-card-form > #saveSetting",
];

const env = {
  oidcIssuerUrl:     decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL),
  mattermostBaseUrl: decodeDotenvQuotedValue(process.env.MATTERMOST_BASE_URL),
  adminUsername:     decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword:     decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername:     decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword:     decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
};

function expectedOidcAuthUrl() {
  return `${env.oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
}

function expectedMattermostBaseUrl() {
  return env.mattermostBaseUrl.replace(/\/$/, "");
}

async function waitForFirstVisible(locators, timeout = resolveTimeout(60_000)) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const locator of locators) {
      if (await locator.first().isVisible().catch(() => false)) {
        return locator.first();
      }
    }
    await new Promise(r => setTimeout(r, resolveTimeout(500)));
  }
  throw new Error("Timed out waiting for one of the expected selectors to become visible");
}

async function openMattermostSignIn(page, baseUrl) {
  const base = baseUrl.replace(/\/$/, "");
  await page.addInitScript(() => {
    try {
      localStorage.setItem("__landingPageSeen__", "true");
    } catch {}
  });
  let lastErr;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await gotoOnion(page, `${base}/login`, { waitUntil: "load", timeout: resolveTimeout(60_000) });
      if (page.url().includes("/landing")) {
        await gotoOnion(page, `${base}/login`, { waitUntil: "load", timeout: resolveTimeout(60_000) });
      }
      await page.locator("[data-testid='login-body-card']").waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
      lastErr = undefined;
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (lastErr) throw lastErr;
}

async function startMattermostSsoFlow(page, baseUrl) {
  await openMattermostSignIn(page, baseUrl);
  const ssoButton = page.locator(SSO_ENTRY).first();
  await ssoButton.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await ssoButton.click({ timeout: resolveTimeout(30_000) });
}

async function dismissMattermostPopups(frame) {
  const dismissSelectors = [
    frame.getByRole("button", { name: /next|done|skip|got it|close|ok/i }),
    frame.locator("[aria-label='Close'], .modal-header .close, button.close"),
    frame.locator("[data-cy='onboarding-task-list-overlay']"),
    frame.locator(".onboarding-tour-tip__close"),
    frame.getByRole("button", { name: /no thanks/i }),
    frame.getByText(/no thanks, i'?ll figure it out/i),
  ];

  for (let round = 0; round < 3; round++) {
    for (const sel of dismissSelectors) {
      if (await sel.first().isVisible().catch(() => false)) {
        await sel.first().click({ force: true }).catch(() => {});
        await new Promise(r => setTimeout(r, resolveTimeout(500)));
      }
    }
    await frame.evaluate(() => {
      document.querySelectorAll("[data-cy='onboarding-task-list-overlay']").forEach(el => el.remove());
      document.querySelectorAll("#root-portal").forEach(el => { el.style.display = "none"; });
    }).catch(() => {});
    await frame.locator("body").press("Escape").catch(() => {});
    await new Promise(r => setTimeout(r, resolveTimeout(500)));
  }
}

async function waitForMattermostChannelView(frame, timeout = resolveTimeout(60_000)) {
  const channelSidebar = frame.locator(
    ".SidebarChannel, [data-testid='channel_sidebar'], #sidebar-left, .SidebarNavContainer"
  );
  const townSquare = frame.getByText("Town Square");
  return waitForFirstVisible([channelSidebar, townSquare], timeout);
}

// `waitUntil: "commit"` avoids net::ERR_ABORTED from the multi-domain
// redirect chain the universal-logout service triggers.
async function mattermostLogout(page, baseUrl) {
  const root = baseUrl.replace(/\/$/, "");
  const session = await page.context().cookies(root).catch(() => []);
  const csrf = session.find((cookie) => cookie.name === "MMCSRF");
  await page.request
    .post(`${root}/api/v4/users/logout`, {
      headers: csrf ? { "X-CSRF-Token": csrf.value } : {},
      failOnStatusCode: false,
    })
    .catch(() => {});
  await gotoOnion(page, `${root}/logout`, { waitUntil: "commit" }).catch(() => {});
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const cookies = await page.context().cookies(root).catch(() => []);
    if (!cookies.some((cookie) => cookie.name === "MMAUTHTOKEN" && cookie.value)) return;
    await page.waitForTimeout(resolveTimeout(500));
  }
}

function beforeEach() {
  expect(env.oidcIssuerUrl,     "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(env.mattermostBaseUrl, "MATTERMOST_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(env.adminUsername,     "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(env.adminPassword,     "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(env.biberUsername,     "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(env.biberPassword,     "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
}

module.exports = {
  env,
  oidcEnabled,
  loginMethods,
  nativeForm,
  NATIVE_FORM_PARTS,
  SSO_ENTRY,
  expectedOidcAuthUrl,
  expectedMattermostBaseUrl,
  waitForFirstVisible,
  openMattermostSignIn,
  startMattermostSsoFlow,
  dismissMattermostPopups,
  waitForMattermostChannelView,
  mattermostLogout,
  beforeEach,
};
