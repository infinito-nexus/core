const { expect } = require("@playwright/test");
const {
  assertCspInjections,
  confirmKeycloakLogoutIfPrompted,
  gotoOnion,
  performKeycloakLogin,
  requireDotenvValue,
  safeIsEnabled,
} = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const PVE_AUTH_COOKIE = "PVEAuthCookie";
const KEYCLOAK_LOGIN_FORM = "#kc-form-login";

function proxmoxEnv() {
  return {
    appBaseUrl: requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL").replace(/\/$/, ""),
    canonicalDomain: requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN"),
    issuerUrl: requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL").replace(/\/$/, ""),
    username: requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"),
    password: requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"),
    realm: requireDotenvValue(process.env.PROXMOX_REALM, "PROXMOX_REALM"),
    group: requireDotenvValue(process.env.PROXMOX_ADMIN_GROUP, "PROXMOX_ADMIN_GROUP"),
    role: requireDotenvValue(process.env.PROXMOX_ADMIN_ROLE, "PROXMOX_ADMIN_ROLE"),
  };
}

async function pveTicket(page, appBaseUrl) {
  const cookies = await page.context().cookies(appBaseUrl);
  return cookies.find((cookie) => cookie.name === PVE_AUTH_COOKIE)?.value || "";
}

function userMenu(page) {
  return page.locator("#userinfo");
}

function realmLoginButton(page) {
  return page
    .getByRole("button", { name: /openid redirect/i })
    .or(page.locator(".x-btn", { hasText: /openid redirect/i }))
    .first();
}

async function signInThroughGate(page, env) {
  await page.context().clearCookies();
  await gotoOnion(page, `${env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: "the oauth2-proxy gate must send an anonymous visitor to the Keycloak authorization endpoint",
    })
    .toContain(`${env.issuerUrl}/protocol/openid-connect/auth`);
  await performKeycloakLogin(page, env.username, env.password, env.canonicalDomain);
}

async function signInThroughRealm(page, env) {
  const loginButton = realmLoginButton(page);
  await expect(
    loginButton,
    `the Proxmox VE login window must preselect the OpenID realm ${env.realm}`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  await loginButton.click();

  const keycloakForm = page.locator(KEYCLOAK_LOGIN_FORM);
  await expect(userMenu(page).or(keycloakForm).first()).toBeVisible({ timeout: resolveTimeout(90_000) });
  if (await keycloakForm.isVisible().catch(() => false)) {
    await performKeycloakLogin(page, env.username, env.password, env.canonicalDomain);
  }
  await expect(
    userMenu(page),
    `the realm login must hand ${env.username}@${env.realm} a Proxmox VE ticket`,
  ).toContainText(`${env.username}@${env.realm}`, { timeout: resolveTimeout(90_000) });
  expect(await pveTicket(page, env.appBaseUrl), `${PVE_AUTH_COOKIE} must hold the ticket`).not.toBe("");
}

async function assertAdministrator(page, env) {
  await expect(
    page.getByRole("button", { name: "Create VM", exact: true }).first(),
    "an Administrator on / may allocate VMs, so Create VM must be enabled",
  ).not.toHaveClass(/x-btn-disabled|x-item-disabled/, { timeout: resolveTimeout(30_000) });

  await page.locator(".x-tree-node-text", { hasText: /^Datacenter/ }).first().click();
  await page.locator(".x-treelist-item-text", { hasText: /^Permissions$/ }).first().click();
  await expect(
    page.locator(".x-grid-item", { hasText: env.group }).filter({ hasText: env.role }).first(),
    `the permission list must grant ${env.role} on / to the group ${env.group}`,
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function signOut(page, env) {
  const universalLogout = isServiceEnabled("logout");
  await userMenu(page).click();
  const reachedKeycloak = universalLogout
    ? page.waitForURL((url) => url.href.startsWith(`${env.issuerUrl}/protocol/openid-connect/logout`), {
        waitUntil: "commit",
        timeout: resolveTimeout(30_000),
      })
    : null;
  await page
    .getByRole("menuitem", { name: /^\s*logout\s*$/i })
    .or(page.locator(".x-menu-item-text", { hasText: /^Logout$/ }))
    .first()
    .click();
  if (reachedKeycloak) {
    await reachedKeycloak;
    await confirmKeycloakLogoutIfPrompted(page);
  }

  await expect
    .poll(() => pveTicket(page, env.appBaseUrl), {
      timeout: resolveTimeout(60_000),
      message: `the logout must delete ${PVE_AUTH_COOKIE}, which ends the Proxmox VE session in this browser`,
    })
    .toBe("");

  await gotoOnion(page, `${env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  if (universalLogout) {
    await expect(
      page.locator(KEYCLOAK_LOGIN_FORM),
      "after the universal logout the gate must ask Keycloak for credentials again, so the Keycloak session ended",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
    return;
  }
  await expect(
    realmLoginButton(page),
    "after the in-app logout Proxmox VE must show its login window again",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function runProxmoxAdminFlow(page) {
  const env = proxmoxEnv();
  await signInThroughGate(page, env);
  await signInThroughRealm(page, env);
  await assertCspInjections(page, { isEnabled: safeIsEnabled });
  await assertAdministrator(page, env);
  await signOut(page, env);
}

module.exports = { proxmoxEnv, runProxmoxAdminFlow, signInThroughGate, signInThroughRealm };
