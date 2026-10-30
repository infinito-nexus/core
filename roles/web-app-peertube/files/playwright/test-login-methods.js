const { test, expect } = require("@playwright/test");

const { apiGetOnion, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const nativeLoginOffered = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const registrationOffered = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";

function register(shared) {
  test("login methods: with SSO on /login offers the OIDC entry and no disabled entry", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const base = shared.env.peertubeBaseUrl.replace(/\/$/, "");

    const config = await (await apiGetOnion(page.request, `${base}/api/v1/config`)).json();
    expect(config.signup.allowed, "PEERTUBE_SIGNUP_ENABLED must follow the registration method").toBe(registrationOffered);
    expect(
      config.client.menu.login.redirectOnSingleExternalAuth,
      "the header login link must hand over to Keycloak exactly when the OIDC entry is the only one",
    ).toBe(!nativeLoginOffered);

    await gotoOnion(page, `${base}/login`);
    await expect(page.locator("my-login a.external-login-block").first(), "expected the OIDC plugin entry").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    const username = page.locator("my-login input#username");
    if (nativeLoginOffered) {
      await expect(username, "expected the local form the native method keeps").toBeVisible();
    } else {
      await expect(username, "the local form must stay hidden while native is off").toBeHidden();
    }
    if (!registrationOffered) {
      await expect(page.locator("my-login a[href='/signup']").filter({ visible: true })).toHaveCount(0);
    }
  });
}

module.exports = { register };
