const crypto = require("node:crypto");
const { test, expect } = require("@playwright/test");

const { apiFetchOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const { totpCode } = require("./totp");

const REPOSITORY = "infinito-2fa-probe";
const ENROLL_PATH = "/user/settings/security/two_factor/enroll";
const ENROLL_LINK = `.flash-message a[href$="${ENROLL_PATH}"]`;
const QR_CODE = '.user-setting-content img[src^="data:image/png;base64,"]';
const SECRET = /^[A-Z2-7]+$/;

const admin = {
  login: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  password: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
};
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

function probeAccount() {
  const login = `infinito-2fa-probe-${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
  return { login, password: `${crypto.randomBytes(18).toString("base64url")}Aa1!` };
}

/**
 * Args:
 *   request: the request fixture, which carries no session, so the basic credentials alone authenticate.
 *   base: Gitea's base URL without a trailing slash.
 *   account: the account whose login and password sign the call.
 *   method: HTTP method.
 *   path: API path below /api/v1.
 *   data: JSON body, if any.
 */
function api(request, base, account, method, path, data) {
  return apiFetchOnion(request, `${base}/api/v1${path}`, {
    method,
    headers: {
      Accept: "application/json",
      Authorization: `Basic ${Buffer.from(`${account.login}:${account.password}`).toString("base64")}`,
    },
    data,
    timeout: resolveTimeout(30_000),
  });
}

/**
 * Args:
 *   request: the request fixture.
 *   base: Gitea's base URL without a trailing slash.
 *   probe: the probeAccount() to create with one private repository and no second factor.
 */
async function createProbe(request, base, probe) {
  const user = await api(request, base, admin, "POST", "/admin/users", {
    username: probe.login,
    email: `${probe.login}@${canonicalDomain}`,
    password: probe.password,
    must_change_password: false,
    send_notify: false,
  });
  expect(user.status(), "the administrator must create the probe account").toBe(201);
  const repository = await api(request, base, admin, "POST", `/admin/users/${probe.login}/repos`, {
    name: REPOSITORY,
    private: true,
    auto_init: true,
    readme: "Default",
  });
  expect(repository.status(), "the administrator must create the probe's private repository").toBe(201);
}

/**
 * Args:
 *   request: the request fixture.
 *   base: Gitea's base URL without a trailing slash.
 *   probe: the probeAccount() to delete together with its repository.
 */
async function deleteProbe(request, base, probe) {
  await api(request, base, admin, "DELETE", `/admin/users/${probe.login}?purge=true`).catch((error) =>
    console.warn(`deleting the probe account failed: ${error}`),
  );
}

/**
 * Args:
 *   request: the request fixture.
 *   base: Gitea's base URL without a trailing slash.
 *   account: the account that asks for the probe's repository.
 *   probe: the probe account that owns it.
 *
 * Returns:
 *   The HTTP status the API answers.
 */
async function repositoryStatus(request, base, account, probe) {
  return (await api(request, base, account, "GET", `/repos/${probe.login}/${REPOSITORY}`)).status();
}

exports.register = function (shared) {
  const base = () => shared.env.gitEaBaseUrl.replace(/\/$/, "");

  test("2fa enrollment: with its own second factor enforced Gitea keeps an account without one from its repositories until it enrolls", async ({ page, request }) => {
    test.skip(!shared.twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=false");
    // nocheck: playwright-sso-ldap-gate -- gates on the login methods that keep Gitea's password form, which the probe signs in through
    test.skip(!(shared.loginMethods.native || shared.loginMethods.ldap), "Gitea serves no password form for the probe to sign in through");
    test.setTimeout(resolveTimeout(300_000));

    const probe = probeAccount();
    try {
      await createProbe(request, base(), probe);
      expect(await repositoryStatus(request, base(), probe, probe), "the API must hide the repository from its owner without a second factor").toBe(404);
      expect(await repositoryStatus(request, base(), admin, probe), "the API must hide it from the administrator without a second factor as well").toBe(404);

      await shared.signIn(page, probe.login, probe.password);
      const refused = await gotoOnion(page, `${base()}/${probe.login}/${REPOSITORY}`);
      expect(refused?.status(), "the web must hide the repository from its owner without a second factor").toBe(404);
      await expect(page.locator(ENROLL_LINK), "Gitea must point the account to the 2FA enrollment").toBeVisible({
        timeout: resolveTimeout(60_000),
      });

      await gotoOnion(page, `${base()}${ENROLL_PATH}`);
      const secret = await page.locator(QR_CODE).getAttribute("alt", { timeout: resolveTimeout(60_000) });
      expect(secret, "the enrollment must show the new TOTP secret").toMatch(SECRET);
      await page.locator("#passcode").fill(totpCode(secret));
      await page.locator("#passcode").press("Enter");
      await expect(page, "the enrollment must end on the security settings").toHaveURL(/\/user\/settings\/security$/, {
        timeout: resolveTimeout(60_000),
      });

      const granted = await gotoOnion(page, `${base()}/${probe.login}/${REPOSITORY}`);
      expect(granted?.status(), "once enrolled the account must reach its repository").toBe(200);
      await expect(page.locator(ENROLL_LINK), "once enrolled Gitea must stop pointing to the enrollment").toHaveCount(0);
    } finally {
      await deleteProbe(request, base(), probe);
    }
  });

  test("2fa enrollment: with the enforcement off Gitea serves an account without a second factor its repositories", async ({ request }) => {
    test.skip(shared.twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=true");
    test.setTimeout(resolveTimeout(120_000));

    const probe = probeAccount();
    try {
      await createProbe(request, base(), probe);
      expect(await repositoryStatus(request, base(), probe, probe), "without the enforcement the API must serve the repository to its owner").toBe(200);
      expect(await repositoryStatus(request, base(), admin, probe), "without the enforcement the API must serve it to the administrator").toBe(200);
    } finally {
      await deleteProbe(request, base(), probe);
    }
  });
};
