const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue } = require("./personas");
const { isServiceEnabled } = require("./service-gating");

const oidcEnabled = isServiceEnabled("oidc");

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

async function waitForFirstVisible(locators, timeout = 60_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const locator of locators) {
      if (await locator.first().isVisible().catch(() => false)) {
        return locator.first();
      }
    }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error("Timed out waiting for one of the expected selectors to become visible");
}

async function startMattermostSsoFlow(page, baseUrl) {
  const base = baseUrl.replace(/\/$/, "");
  await page.addInitScript(() => {
    try {
      localStorage.setItem("__landingPageSeen__", "true");
    } catch {}
  });
  let lastErr;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await page.goto(`${base}/login`, { waitUntil: "load", timeout: 60_000 });
      if (page.url().includes("/landing")) {
        await page.goto(`${base}/login`, { waitUntil: "load", timeout: 60_000 });
      }
      await page.locator("#input_loginId").waitFor({ state: "visible", timeout: 60_000 });
      lastErr = undefined;
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (lastErr) throw lastErr;
  const ssoButton = page.locator("a[href='/oauth/gitlab/login']");
  await ssoButton.waitFor({ state: "visible", timeout: 30_000 });
  await ssoButton.click();
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
      if (await sel.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        await sel.first().click({ force: true }).catch(() => {});
        await new Promise(r => setTimeout(r, 500));
      }
    }
    await frame.evaluate(() => {
      document.querySelectorAll("[data-cy='onboarding-task-list-overlay']").forEach(el => el.remove());
      document.querySelectorAll("#root-portal").forEach(el => { el.style.display = "none"; });
    }).catch(() => {});
    await frame.locator("body").press("Escape").catch(() => {});
    await new Promise(r => setTimeout(r, 500));
  }
}

async function waitForMattermostChannelView(frame, timeout = 60_000) {
  const channelSidebar = frame.locator(
    ".SidebarChannel, [data-testid='channel_sidebar'], #sidebar-left, .SidebarNavContainer"
  );
  const townSquare = frame.getByText("Town Square");
  return waitForFirstVisible([channelSidebar, townSquare], timeout);
}

// `waitUntil: "commit"` avoids net::ERR_ABORTED from the multi-domain
// redirect chain the universal-logout service triggers.
async function mattermostLogout(page, baseUrl) {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/logout`, { waitUntil: "commit" }).catch(() => {});
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
  expectedOidcAuthUrl,
  expectedMattermostBaseUrl,
  waitForFirstVisible,
  startMattermostSsoFlow,
  dismissMattermostPopups,
  waitForMattermostChannelView,
  mattermostLogout,
  beforeEach,
};
