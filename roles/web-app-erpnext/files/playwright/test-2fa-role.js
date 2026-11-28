const crypto = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue } = require("./personas");

const LOGIN = "/api/method/login";
const LOGGED_USER = "/api/method/frappe.auth.get_logged_user";
const senderAddress = decodeDotenvQuotedValue(process.env.EMAIL_FROM_ADDRESS || "");

function probeAccount() {
  const suffix = crypto.randomBytes(4).toString("hex");
  const [mailbox, domain] = senderAddress.split("@");
  return {
    role: `Infinito 2FA Probe ${suffix}`,
    email: `${mailbox}+infinito-2fa-probe-${suffix}@${domain}`,
    password: `${crypto.randomBytes(18).toString("base64url")}-Aa9`,
  };
}

async function writeResource(api, shared, method, path, data) {
  const response = await api.fetch(`${shared.env.erpnextBaseUrl}/api/resource/${path}`, {
    method,
    data,
    timeout: resolveTimeout(60_000),
  });
  expect(response.ok(), `${method} /api/resource/${path} must succeed for the API bot`).toBe(true);
}

async function passwordSignIn(browser, shared, account) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const login = await context.request.post(`${shared.env.erpnextBaseUrl}${LOGIN}`, {
      form: { usr: account.email, pwd: account.password },
      timeout: resolveTimeout(60_000),
    });
    expect(login.status(), "Frappe must answer the password sign-in of the probe").toBe(200);
    const logged = await context.request.get(`${shared.env.erpnextBaseUrl}${LOGGED_USER}`, {
      timeout: resolveTimeout(60_000),
    });
    return {
      body: await login.json(),
      user: logged.status() === 200 ? (await logged.json()).message : null,
    };
  } finally {
    await context.close().catch(() => {});
  }
}

exports.register = function (shared) {
  test("2fa: a role with the Two Factor Authentication box holds the password sign-in of its member at the second factor", async ({ browser }) => {
    test.skip(!shared.env.loginMethods.native, "LOGIN_METHOD_NATIVE_ENABLED=false: disable_user_pass_login refuses the probe's password");
    test.skip(!shared.env.loginMethods.twoFactor, "LOGIN_METHOD_2FA_ENABLED=false: enable_two_factor_auth is off");
    shared.skipUnlessServiceEnabled("email");
    test.setTimeout(resolveTimeout(240_000));
    expect(senderAddress, "EMAIL_FROM_ADDRESS must name the outgoing mailbox when the email service is on").toContain("@");

    const account = probeAccount();
    const api = await shared.breakGlassApi();
    try {
      await writeResource(api, shared, "POST", "Role", { role_name: account.role, desk_access: 0, two_factor_auth: 1 });
      await writeResource(api, shared, "POST", "User", {
        email: account.email,
        first_name: "Infinito 2FA Probe",
        send_welcome_email: 0,
        new_password: account.password,
        roles: [{ role: account.role }],
      });

      const held = await passwordSignIn(browser, shared, account);
      expect(typeof held.body.tmp_id, "Frappe must hand the sign-in a tmp_id for the second factor").toBe("string");
      expect(held.body.verification, "Frappe must name the verification the sign-in waits for").toBeTruthy();
      expect(held.user, "the password alone must open no session").toBeNull();

      await writeResource(api, shared, "PUT", `Role/${encodeURIComponent(account.role)}`, { two_factor_auth: 0 });
      const open = await passwordSignIn(browser, shared, account);
      expect(open.body.tmp_id, "without the box the sign-in must not wait for a second factor").toBeUndefined();
      expect(open.user, "without the box the password must open the probe's session").toBe(account.email);
    } finally {
      await api
        .delete(`${shared.env.erpnextBaseUrl}/api/resource/User/${encodeURIComponent(account.email)}`, { timeout: resolveTimeout(60_000) })
        .catch(() => {});
      await api
        .delete(`${shared.env.erpnextBaseUrl}/api/resource/Role/${encodeURIComponent(account.role)}`, { timeout: resolveTimeout(60_000) })
        .catch(() => {});
      await api.dispose().catch(() => {});
    }
  });
};
