const { expect } = require("@playwright/test");
const { isServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue } = require("./personas");

const env = {
  filerUrl: decodeDotenvQuotedValue(process.env.SEAWEEDFS_FILER_URL),
  masterUrl: decodeDotenvQuotedValue(process.env.SEAWEEDFS_MASTER_URL),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  ssoEnabled: isServiceEnabled("sso"),
  consumerBuckets: (() => {
    try {
      return JSON.parse(decodeDotenvQuotedValue(process.env.SEAWEEDFS_CONSUMER_BUCKETS) || "[]");
    } catch {
      return [];
    }
  })(),
};

async function keycloakLogin(page, username, password) {
  await page.waitForLoadState("domcontentloaded");
  const user = page.locator("#username, input[name='username']").first();
  await user.waitFor({ state: "visible", timeout: 60_000 });
  await user.fill(username);
  await page.locator("#password, input[name='password']").first().fill(password);
  await page.locator("#kc-login, button[type='submit'], input[type='submit']").first().click();
  await page.waitForLoadState("networkidle").catch(() => {});
}

function isAuthChain(url) {
  return /\/oauth2\/|\/realms\/|\/protocol\/openid-connect\//.test(url);
}

module.exports = { env, keycloakLogin, isAuthChain, expect };
