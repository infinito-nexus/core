const crypto = require("crypto");
const { test, expect, request } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

const twoFactorEnabled = process.env.LOGIN_METHOD_2FA_ENABLED === "true";
const ENFORCE_ROLES = "two_factor_authentication_enforce_role_ids";
const AUTHENTICATOR_APP = "two_factor_authentication_method_authenticator_app";
const PROBE_ROLE = "Infinito 2FA probe";
const SETUP_MODAL = ".modal:has(.js-configuration-method), .modal:has(.js-cancel)";

/**
 * Args:
 *   shared: the Zammad shared helper module.
 *   testInfo: the TestInfo of the running test, for the project proxy.
 *   method: HTTP verb.
 *   path: path below /api/v1/.
 *   data: JSON body, or undefined for none.
 *
 * Returns:
 *   The status and the parsed answer of one cookie-less call as the API bot.
 */
async function botApi(shared, testInfo, method, path, data) {
  const api = await request.newContext({
    ignoreHTTPSErrors: true,
    proxy: testInfo.project.use.proxy,
    extraHTTPHeaders: {
      Authorization: `Basic ${Buffer.from(`${shared.env.adminApiUsername}:${shared.env.adminApiPassword}`).toString("base64")}`,
    },
  });
  try {
    const response = await api.fetch(`${shared.env.zammadBaseUrl}/api/v1/${path}`, {
      method,
      data,
      timeout: resolveTimeout(30_000),
    });
    return { status: response.status(), json: await response.json().catch(() => null) };
  } finally {
    await api.dispose();
  }
}

exports.register = function (shared) {
  test("2fa enrollment: with its own second factor enforced Zammad sends a local account without one to setup before it gets in", async ({ page }, testInfo) => {
    shared.skipUnlessServiceDisabled("sso");
    test.skip(!twoFactorEnabled, "LOGIN_METHOD_2FA_ENABLED=false");
    test.setTimeout(resolveTimeout(240_000));
    expect(shared.env.adminApiUsername, "ADMIN_API_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminApiPassword, "ADMIN_API_PASSWORD must be set").toBeTruthy();
    const api = (method, path, data) => botApi(shared, testInfo, method, path, data);

    const settings = await api("GET", "settings");
    expect(settings.status, "the API bot must read the Zammad settings").toBe(200);
    const enforce = settings.json.find((setting) => setting.name === ENFORCE_ROLES);
    const authenticatorApp = settings.json.find((setting) => setting.name === AUTHENTICATOR_APP);
    expect(enforce, `the ${ENFORCE_ROLES} setting must exist`).toBeTruthy();
    expect(authenticatorApp?.state_current?.value, "login.method.2fa is on, so the authenticator app method must be on").toBe(true);
    const previous = enforce.state_current.value;

    const roles = await api("GET", "roles");
    expect(roles.status, "the API bot must list the roles").toBe(200);
    let role = roles.json.find((entry) => entry.name === PROBE_ROLE);
    if (role) {
      const activated = await api("PUT", `roles/${role.id}`, { active: true });
      expect(activated.status, "the API bot must reactivate the probe role").toBe(200);
    } else {
      const created = await api("POST", "roles", {
        name: PROBE_ROLE,
        active: true,
        permissions: ["ticket.customer", "user_preferences.two_factor_authentication"],
      });
      expect(created.status, "the API bot must create the probe role").toBe(201);
      role = created.json;
    }

    const suffix = `${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
    const probe = { login: `infinito-2fa-probe-${suffix}`, password: crypto.randomBytes(24).toString("base64url") };
    let probeId = null;
    let enforcing = false;
    try {
      const user = await api("POST", "users", {
        login: probe.login,
        email: `${probe.login}@${shared.env.canonicalDomain}`,
        firstname: "Infinito",
        lastname: "2FA probe",
        password: probe.password,
        active: true,
        role_ids: [role.id],
      });
      expect(user.status, "the API bot must create the probe account").toBe(201);
      probeId = user.json.id;
      const enforced = await api("PUT", `settings/${enforce.id}`, { state_current: { value: [role.id] } });
      expect(enforced.status, "the API bot must enforce the second factor for the probe role only").toBe(200);
      enforcing = true;

      await gotoOnion(page, `${shared.env.zammadBaseUrl}/#login`, { waitUntil: "domcontentloaded" });
      const usernameInput = page.locator('input[name="username"]');
      await usernameInput.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
      await usernameInput.fill(probe.login);
      await page.locator('input[name="password"]').fill(probe.password);
      await page.locator('button[type="submit"]').first().click({ timeout: resolveTimeout(30_000) });

      const setup = page.locator(SETUP_MODAL).first();
      await expect(setup, "an account of an enforced role without a second factor must get the setup dialog").toBeVisible({
        timeout: resolveTimeout(60_000),
      });
      await expect(setup.locator(".modal-title"), "the dialog must ask the account to set up its second factor").toContainText(
        /set up two-factor authentication/i,
      );
      await expect(
        setup.locator('.js-configuration-method[data-method="AuthenticatorApp"]'),
        "the dialog must offer the authenticator app",
      ).toBeVisible({ timeout: resolveTimeout(30_000) });

      await page.keyboard.press("Escape");
      await expect(setup, "the setup dialog must not close before the account enrolls").toBeVisible();
      await page.reload({ waitUntil: "domcontentloaded" });
      const resumed = page.locator(SETUP_MODAL).first();
      await expect(resumed, "a reload must bring the setup dialog back").toBeVisible({ timeout: resolveTimeout(60_000) });
      await expect(resumed.locator(".modal-title")).toContainText(/set up two-factor authentication/i);

      const cancel = resumed.locator(".js-cancel").first();
      if (await cancel.isVisible()) {
        await cancel.click({ timeout: resolveTimeout(30_000) });
      } else {
        await shared.zammadLogout(page);
        await gotoOnion(page, `${shared.env.zammadBaseUrl}/#login`, { waitUntil: "domcontentloaded" });
      }
      await expect(page.locator('input[name="username"]'), "leaving the setup must end on the signed-out sign-in form").toBeVisible({
        timeout: resolveTimeout(60_000),
      });
    } finally {
      if (enforcing) {
        const restored = await api("PUT", `settings/${enforce.id}`, { state_current: { value: previous } }).catch((error) => ({
          status: String(error),
        }));
        if (restored.status !== 200) {
          console.warn(`restoring ${ENFORCE_ROLES} failed: ${restored.status}`);
        }
      }
      if (probeId !== null) {
        await api("PUT", `users/${probeId}`, { active: false }).catch((error) => console.warn(`deactivating the probe failed: ${error}`));
        await api("POST", "data_privacy_tasks", { deletable_type: "User", deletable_id: probeId }).catch((error) =>
          console.warn(`scheduling the probe deletion failed: ${error}`),
        );
      }
      await api("PUT", `roles/${role.id}`, { active: false }).catch((error) => console.warn(`deactivating the probe role failed: ${error}`));
    }
  });
};
