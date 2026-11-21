const crypto = require("crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { apiFetchOnion, gotoOnion, normalizeBaseUrl, recordVideoOptions, requireDotenvValue } = require("./personas");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const adminEmail = requireDotenvValue(process.env.ADMIN_EMAIL, "ADMIN_EMAIL");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const twoFactorEnabled = process.env.LOGIN_METHOD_2FA_ENABLED === "true";
const CONTROL = `${base}/control`;
const ORGANIZER = "infinito-2fa-probe";
const PAGE = "#page-wrapper";
const SIGN_IN_FORM = "form.form-signin";
const FRAME = "nav.navbar.navbar-inverse";
const ENROLLMENT = /\/control\/settings\/2fa\/?(?:\?.*)?$/;

/**
 * Args:
 *   page: Playwright page that ends signed in to the pretix control panel through the native form.
 *   email: the account's e-mail address.
 *   password: its password.
 */
async function signInNative(page, email, password) {
  await gotoOnion(page, `${CONTROL}/login?backend=native`);
  await expect(page.locator(`${SIGN_IN_FORM} input[name='email']`), "the native sign-in form must render").toBeEditable({
    timeout: resolveTimeout(30_000),
  });
  await page.locator(`${SIGN_IN_FORM} input[name='email']`).fill(email);
  await page.locator(`${SIGN_IN_FORM} input[name='password']`).fill(password);
  await page.locator(`${SIGN_IN_FORM} button[type='submit'].btn-primary`).click({ timeout: resolveTimeout(30_000) });
  await expect(page.locator(FRAME), `the sign-in of ${email} stalled on ${page.url()}`).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: signed-in page of a staff user; ends in an admin session.
 */
async function adminMode(page) {
  await gotoOnion(page, `${CONTROL}/`);
  const sudo = page.locator("#button-sudo");
  if ((await sudo.count()) > 0) {
    await sudo.evaluate((button) => button.closest("form").submit());
    await page.waitForLoadState("domcontentloaded");
  }
  await expect(page.locator(`${FRAME} a.admin-only`), "the administrator must hold an admin session").toBeAttached({
    timeout: resolveTimeout(30_000),
  });
}

/**
 * Args:
 *   page: page in an admin session on a control page that renders a form.
 *   method: HTTP method.
 *   path: path below the probe organizer's API root.
 *   data: JSON body, or undefined.
 *
 * Returns:
 *   The status and the parsed JSON answer.
 */
async function organizerApi(page, method, path, data) {
  const csrf = await page.locator("input[name='csrfmiddlewaretoken']").first().inputValue();
  const response = await apiFetchOnion(page.request, `${base}/api/v1/organizers/${ORGANIZER}${path}`, {
    method,
    data,
    headers: {
      "X-CSRFToken": csrf,
      Referer: `${CONTROL}/`,
      "User-Agent": await page.evaluate(() => navigator.userAgent),
    },
    timeout: resolveTimeout(30_000),
  });
  const body = await response.text();
  return { status: response.status(), json: body ? JSON.parse(body) : null };
}

test("2fa enrollment: with its own second factor enforced pretix sends a local account without one to setup before it gets in", async ({ browser, page }, testInfo) => {
  skipUnlessServiceDisabled("sso");
  test.skip(!nativeEnabled, "LOGIN_METHOD_NATIVE_ENABLED=false");
  test.skip(!twoFactorEnabled, "LOGIN_METHOD_2FA_ENABLED=false");
  test.setTimeout(resolveTimeout(300_000));

  const suffix = `${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
  const probe = { email: `infinito-2fa-probe-${suffix}@${canonicalDomain}`, password: crypto.randomBytes(24).toString("base64url") };

  await signInNative(page, adminEmail, adminPassword);
  await adminMode(page);
  await gotoOnion(page, `${CONTROL}/organizers/`);
  if ((await page.locator(`a[href*='/control/organizer/${ORGANIZER}/']`).count()) === 0) {
    await gotoOnion(page, `${CONTROL}/organizers/add`);
    await page.locator(`${PAGE} input[name='name']`).fill("Infinito 2FA probe");
    await page.locator(`${PAGE} input[name='slug']`).fill(ORGANIZER);
    await page.locator(`${PAGE} form button[type='submit'].btn-primary`).click({ timeout: resolveTimeout(30_000) });
    await expect(page, "the administrator must create the probe organizer").toHaveURL(new RegExp(`/control/organizer/${ORGANIZER}/`), {
      timeout: resolveTimeout(30_000),
    });
  }

  let probeId = null;
  let teamId = null;
  let probeContext = null;
  try {
    await gotoOnion(page, `${CONTROL}/users/add`);
    await page.locator(`${PAGE} form input[name='email']`).fill(probe.email);
    await page.locator(`${PAGE} form input[name='fullname']`).fill("Infinito 2FA probe");
    await page.locator(`${PAGE} form input[name='new_pw']`).fill(probe.password);
    await page.locator(`${PAGE} form input[name='new_pw_repeat']`).fill(probe.password);
    await page.locator(`${PAGE} form input[name='is_active']`).check();
    for (const flag of ["needs_password_change", "require_2fa", "is_staff"]) {
      const box = page.locator(`${PAGE} form input[name='${flag}']`);
      if ((await box.count()) > 0) {
        await box.uncheck();
      }
    }
    await page.locator(`${PAGE} form button[type='submit'].btn-primary`).click({ timeout: resolveTimeout(30_000) });
    await page.waitForURL((url) => !url.pathname.endsWith("/users/add"), { timeout: resolveTimeout(30_000) });

    await gotoOnion(page, `${CONTROL}/settings`);
    const team = await organizerApi(page, "POST", "/teams/", {
      name: `Infinito 2FA probe ${suffix}`,
      require_2fa: true,
      all_events: false,
      limit_events: [],
      all_event_permissions: false,
      limit_event_permissions: [],
      all_organizer_permissions: false,
      limit_organizer_permissions: [],
    });
    expect(team.status, "the administrator must create a team that requires a second factor").toBe(201);
    teamId = team.json.id;
    const invite = await organizerApi(page, "POST", `/teams/${teamId}/invites/`, { email: probe.email });
    expect([200, 201], "inviting the existing probe account must add it to the team").toContain(invite.status);
    const members = await organizerApi(page, "GET", `/teams/${teamId}/members/`);
    const member = (members.json?.results || []).find((entry) => entry.email === probe.email);
    expect(member, "the probe account must be a member of the 2FA team").toBeTruthy();
    probeId = member.id;

    probeContext = await browser.newContext({ ignoreHTTPSErrors: true, proxy: testInfo.project.use.proxy, ...recordVideoOptions(testInfo) });
    const probePage = await probeContext.newPage();
    await signInNative(probePage, probe.email, probe.password);
    await expect(probePage, "a member of a 2FA team without a device must land on the 2FA settings").toHaveURL(ENROLLMENT, {
      timeout: resolveTimeout(60_000),
    });
    await expect(
      probePage.locator(PAGE).getByText(/obligatory usage of two-factor authentication/i).first(),
      "the 2FA settings must say that the team requires a second factor",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(
      probePage.locator(`${PAGE} a[href*='/control/settings/2fa/add']`).first(),
      "the 2FA settings must offer to add a device",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    await gotoOnion(probePage, `${CONTROL}/`);
    await expect(probePage, "the control panel must hand the account back to the 2FA settings").toHaveURL(ENROLLMENT, {
      timeout: resolveTimeout(60_000),
    });

    await probePage.locator("a[href$='/control/logout']").first().click({ timeout: resolveTimeout(30_000) });
    await expect(probePage.locator(`${SIGN_IN_FORM} input[name='email']`), "the logout must end on the sign-in form").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
  } finally {
    await (probeContext ? probeContext.close() : Promise.resolve()).catch(() => {});
    if (teamId !== null) {
      await gotoOnion(page, `${CONTROL}/settings`).catch(() => {});
      const removed = await organizerApi(page, "DELETE", `/teams/${teamId}/`).catch((error) => ({ status: String(error) }));
      if (removed.status !== 204) {
        console.warn(`deleting the probe team failed: ${removed.status}`);
      }
    }
    if (probeId !== null) {
      await gotoOnion(page, `${CONTROL}/users/${probeId}/anonymize`)
        .then(() => page.locator(`${PAGE} form button[type='submit']`).first().click({ timeout: resolveTimeout(30_000) }))
        .catch((error) => console.warn(`anonymizing the probe account failed: ${error}`));
    }
  }
});
