const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiFetchOnion, decodeDotenvQuotedValue, gotoOnion, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const fiderBaseUrl = requireDotenvValue(process.env.FIDER_BASE_URL, "FIDER_BASE_URL").replace(/\/$/, "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const biberEmail = decodeDotenvQuotedValue(process.env.BIBER_EMAIL || "");
const loginMethodNative = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const loginMethodSso = process.env.LOGIN_METHOD_SSO_ENABLED === "true";

const SIGN_IN_CONTROL = ".c-modal-window .c-signin-control";

/**
 * Args:
 *   page: Playwright page that ends on the open sign-in modal of the Fider board.
 */
async function openSignIn(page) {
  await gotoOnion(page, `${fiderBaseUrl}/`);
  const signIn = page.getByRole("button", { name: /sign in/i }).or(page.getByRole("link", { name: /sign in/i }));
  await signIn.first().waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await signIn.first().click();
  await expect(page.locator(SIGN_IN_CONTROL), "the header sign-in must open the sign-in modal").toBeVisible({
    timeout: resolveTimeout(15_000),
  });
}

/**
 * Args:
 *   page: Playwright page whose request context asks for the code.
 *   email: address the email code sign-in is requested for.
 *
 * Returns:
 *   The response of POST /_api/signin.
 */
async function requestSignInCode(page, email) {
  return apiFetchOnion(page.request, `${fiderBaseUrl}/_api/signin`, { method: "POST", data: { email } });
}

exports.register = function () {
  test("login methods: with SSO on the sign-in modal offers the SSO entry and no email form", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await openSignIn(page);
    const control = page.locator(SIGN_IN_CONTROL);
    if (loginMethodSso) {
      await expect(control.getByRole("link", { name: /continue with/i }).first(), "the SSO entry must render on the sign-in modal").toBeVisible();
    }
    if (!loginMethodNative) {
      await expect(control.locator("input"), "the email code form must be gone while native sign-in is off").toHaveCount(0);
    }
  });

  test("login methods: the administrator keeps the email code sign-in while it is off for everyone else (break-glass)", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(loginMethodNative, "LOGIN_METHOD_NATIVE_ENABLED=true offers the email code sign-in to every account");
    expect(adminEmail, "ADMIN_EMAIL must be set in the Playwright env file").toBeTruthy();
    expect(biberEmail, "BIBER_EMAIL must be set in the Playwright env file").toBeTruthy();

    await openSignIn(page);
    const control = page.locator(SIGN_IN_CONTROL);
    await control.locator("a.text-bold").first().click();
    await expect(control.locator("input").first(), "the administrator bypass must reveal the email code form").toBeVisible({
      timeout: resolveTimeout(15_000),
    });

    expect((await requestSignInCode(page, biberEmail)).ok(), "an account without the administrator role must get no email sign-in code").toBe(false);
    expect((await requestSignInCode(page, adminEmail)).status(), "the administrator must get an email sign-in code").toBe(200);
  });
};
