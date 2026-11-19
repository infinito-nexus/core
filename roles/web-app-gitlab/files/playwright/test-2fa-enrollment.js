const crypto = require("crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled } = require("./service-gating");
const {
  apiFetchOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  recordVideoOptions,
  requireDotenvValue,
} = require("./personas");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = decodeDotenvQuotedValue(requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN"));
const rootPassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const twoFactorEnabled = process.env.LOGIN_METHOD_2FA_ENABLED === "true";
const ROOT_USERNAME = "root";
const USERNAME = "[data-testid='username-field']";
const PASSWORD = "[data-testid='password-field']";
const SIGN_IN = "[data-testid='sign-in-button']";
const ENROLLMENT = /\/-\/profile\/two_factor_auth/;

/**
 * Args:
 *   page: Playwright page that ends signed in through GitLab's password form.
 *   username: the account to sign in.
 *   password: its password.
 */
async function signInWithPassword(page, username, password) {
  await gotoOnion(page, `${base}/users/sign_in`);
  await expect(page.locator(USERNAME), "the GitLab password form must render").toBeEditable({ timeout: resolveTimeout(30_000) });
  await page.locator(USERNAME).fill(username);
  await page.locator(PASSWORD).fill(password);
  await page.locator(SIGN_IN).click({ timeout: resolveTimeout(30_000) });
  await page.waitForURL((url) => !url.pathname.startsWith("/users/sign_in"), { timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: signed-in Playwright page; the call runs in it with the session cookie and the CSRF token of the page.
 *   method: HTTP verb.
 *   path: path below /api/v4.
 *   payload: JSON body, omitted for a request without one.
 *
 * Returns:
 *   The HTTP status and the parsed answer.
 */
async function api(page, method, path, payload) {
  return page.evaluate(
    async ([verb, url, body]) => {
      const token = document.querySelector("meta[name='csrf-token']")?.content || "";
      const response = await fetch(url, {
        method: verb,
        credentials: "same-origin",
        headers: { "content-type": "application/json", "x-csrf-token": token },
        body: body === null ? undefined : JSON.stringify(body),
      });
      return { status: response.status, data: await response.json().catch(() => null) };
    },
    [method, `/api/v4${path}`, payload === undefined ? null : payload],
  );
}

test("2fa enrollment: with its own second factor enforced GitLab sends a local account without one to setup before it gets in", async ({ browser, page, request }, testInfo) => {
  skipUnlessServiceDisabled("sso");
  test.skip(!nativeEnabled, "LOGIN_METHOD_NATIVE_ENABLED=false");
  test.skip(!twoFactorEnabled, "LOGIN_METHOD_2FA_ENABLED=false");
  test.setTimeout(resolveTimeout(300_000));

  const suffix = `${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
  const probe = {
    username: `infinito-2fa-probe-${suffix}`,
    password: crypto.randomBytes(24).toString("base64url"),
  };
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);

  await signInWithPassword(page, ROOT_USERNAME, rootPassword);
  await gotoOnion(page, `${base}/`);
  let probeId = null;
  let probeContext = null;
  try {
    const created = await api(page, "POST", "/users", {
      email: `${probe.username}@${canonicalDomain}`,
      username: probe.username,
      name: "Infinito 2FA probe",
      password: probe.password,
      skip_confirmation: true,
    });
    expect(created.status, "root must create the probe account").toBe(201);
    probeId = created.data.id;
    const impersonation = await api(page, "POST", `/users/${probeId}/impersonation_tokens`, {
      name: `infinito-2fa-probe-${suffix}`,
      scopes: ["api"],
      expires_at: tomorrow,
    });
    expect(impersonation.status, "root must mint an impersonation token for the probe").toBe(201);

    const group = await apiFetchOnion(request, `${base}/api/v4/groups`, {
      method: "POST",
      headers: { "PRIVATE-TOKEN": impersonation.data.token },
      data: {
        name: `Infinito 2FA group ${suffix}`,
        path: `infinito-2fa-group-${suffix}`,
        visibility: "private",
        require_two_factor_authentication: true,
        two_factor_grace_period: 0,
      },
      timeout: resolveTimeout(30_000),
    });
    expect(group.status(), "the probe must own a group that requires a second factor without grace period").toBe(201);

    probeContext = await browser.newContext({
      ignoreHTTPSErrors: true,
      proxy: testInfo.project.use.proxy,
      ...recordVideoOptions(testInfo),
    });
    const probePage = await probeContext.newPage();
    await probePage.addLocatorHandler(probePage.getByTestId("alert-modal-remind-button"), (remind) => remind.click());
    await signInWithPassword(probePage, probe.username, probe.password);

    await expect(probePage, "an account its group requires a second factor of must land on the 2FA setup page").toHaveURL(ENROLLMENT, {
      timeout: resolveTimeout(60_000),
    });
    await expect(
      probePage.getByText(/require you to add 2FA|secure your account with two-factor authentication/i).first(),
      "the setup page must say that a second factor is required",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(
      probePage.getByTestId("register-otp-authenticator-button").or(probePage.getByRole("button", { name: /register authenticator/i })).first(),
      "the setup page must offer the one-time password authenticator",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    await gotoOnion(probePage, `${base}/dashboard/projects`);
    await expect(probePage, "the dashboard must hand the account back to the 2FA setup page").toHaveURL(ENROLLMENT, {
      timeout: resolveTimeout(60_000),
    });
    const self = await probePage.request.get(`${base}/api/v4/user`, { timeout: resolveTimeout(30_000) });
    expect(self.ok(), "the API must refuse the session of an account that has not enrolled yet").toBe(false);
  } finally {
    await (probeContext ? probeContext.close() : Promise.resolve()).catch(() => {});
    if (probeId !== null) {
      const removed = await api(page, "DELETE", `/users/${probeId}?hard_delete=true`).catch((error) => ({ status: String(error) }));
      if (removed.status !== 204) {
        console.warn(`deleting the probe account failed: ${removed.status}`);
      }
    }
  }
});
