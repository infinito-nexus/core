const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

const nativeOffered = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const directoryOffered = process.env.LOGIN_METHOD_LDAP_ENABLED === "true";
const registrationOffered = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";

exports.register = (shared) => {
  const { test, expect, skipUnlessServiceEnabled, env, loginRoute } = shared;

  test("login methods: with SSO on the sign-in page offers only the enabled entries", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await gotoOnion(page, loginRoute(env.baseUrl));
    await expect(page.getByText("OpenID", { exact: true }), "expected the Penpot OpenID entry").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
    await expect(page.getByLabel(/work email/i)).toHaveCount(nativeOffered || directoryOffered ? 1 : 0);
    await expect(page.getByTestId("login-submit")).toHaveCount(nativeOffered ? 1 : 0);
    await expect(page.getByTestId("forgot-password")).toHaveCount(nativeOffered ? 1 : 0);
    await expect(page.getByRole("button", { name: /^LDAP$/i })).toHaveCount(directoryOffered ? 1 : 0);
    await expect(page.getByTestId("register-submit")).toHaveCount(registrationOffered ? 1 : 0);
  });
};
