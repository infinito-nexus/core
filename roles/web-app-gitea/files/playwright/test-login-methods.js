const { test, expect } = require("@playwright/test");

const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("break-glass: with SSO on the local administrator reaches the API through basic authentication", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const username = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
    const password = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
    const response = await apiGetOnion(page.request, `${shared.env.gitEaBaseUrl.replace(/\/$/, "")}/api/v1/user`, {
      headers: { Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}` },
    });
    expect(response.status(), "basic authentication with the local password must stay open as the break-glass path").toBe(200);
    const account = await response.json();
    expect(account.login, "the account behind the break-glass credentials").toBe(username);
    expect(account.is_admin, "the break-glass account must hold Gitea admin rights").toBe(true);
  });

  test("login methods: with SSO on Gitea offers only the SSO entry", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const { native, ldap, passkey, openid2, registration } = shared.loginMethods;
    // nocheck: playwright-sso-ldap-gate -- gates on the login methods that keep Gitea's sign-in page, inside the sso service gate
    test.skip(
      native || ldap || passkey || openid2,
      "an inventory override keeps a second sign-in method, so Gitea renders its sign-in page",
    );
    const base = shared.env.gitEaBaseUrl.replace(/\/$/, "");
    const host = new URL(base).hostname;
    const hops = [];
    const renderedSignInPages = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.hostname === host) hops.push(url.pathname);
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.hostname === host && url.pathname === "/user/login" && response.status() === 200) {
        renderedSignInPages.push(response.url());
      }
    });

    await gotoOnion(page, `${base}/explore/repos`);
    await expect(
      page.locator('#navbar a[href*="/user/sign_up"]'),
      "the navbar offers a Register entry exactly when local self-registration is on",
    ).toHaveCount(registration ? 1 : 0);

    await shared.signIn(
      page,
      decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
      decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
    );
    expect(
      hops.some((path) => path.startsWith("/user/oauth2/")),
      "Gitea must hand /user/login straight to its single OAuth source",
    ).toBe(true);
    expect(
      renderedSignInPages,
      "Gitea must never render its sign-in page: no password form, passkey or OpenID 2.0 entry is offered",
    ).toEqual([]);
  });
};
