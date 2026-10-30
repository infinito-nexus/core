const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const directoryOffered = process.env.LOGIN_METHOD_LDAP_ENABLED === "true";

exports.register = function (shared) {
  test("login methods: the local administrator signs in through the Taiga API with SSO on", async ({ request }) => {
    shared.skipUnlessServiceEnabled("sso");
    const response = await request.post(`${shared.getTaigaUrls().expectedTaigaBaseUrl}/api/v1/auth`, {
      data: { type: "normal", username: shared.env.adminUsername, password: shared.env.adminPassword },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(response.status(), "the break-glass API login of the local administrator must answer 200").toBe(200);
    expect((await response.json()).auth_token, "the break-glass API login must issue a Taiga auth token").toBeTruthy();
  });

  test("login methods: with SSO on the LDAP backend answers only while the ldap method is on", async ({ request }) => {
    shared.skipUnlessServiceEnabled("sso");
    const login = await shared.taigaLdapLogin(request, shared.env.adminUsername, shared.env.adminPassword);
    expect(login.status === 200, `the LDAP login answered ${login.status}`).toBe(directoryOffered);
  });
};
