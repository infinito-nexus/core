const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, withLdapGroupMember } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const env = {
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  biberDn: decodeDotenvQuotedValue(process.env.BIBER_LDAP_DN),
  administratorGroupDn: decodeDotenvQuotedValue(process.env.LDAP_ADMINISTRATOR_GROUP_DN),
  restrictedGroupDn: decodeDotenvQuotedValue(process.env.LDAP_RESTRICTED_GROUP_DN),
};

async function signInAsBiber(request, shared) {
  const credentials = Buffer.from(`${env.biberUsername}:${env.biberPassword}`).toString("base64");
  const response = await request.get(`${shared.env.gitEaBaseUrl.replace(/\/$/, "")}/api/v1/user`, {
    headers: { Authorization: `Basic ${credentials}`, Accept: "application/json" },
    timeout: resolveTimeout(30_000),
  });
  const body = await response.text();
  expect(response.ok(), `biber must sign in to Gitea through the LDAP source, got ${response.status()}: ${body.slice(0, 300)}`).toBe(true);
  return JSON.parse(body);
}

function skipUnlessLdapLogin(shared) {
  skipUnlessServiceEnabled("ldap");
  // nocheck: playwright-sso-ldap-gate -- gates on the ldap login method, which is off under SSO while the ldap service stays on
  test.skip(
    !shared.loginMethods.ldap,
    "LOGIN_METHOD_LDAP_ENABLED=false: LDAP accounts sign in through Keycloak's LDAP federation, not Gitea's LDAP source",
  );
}

async function withBiberInGroup(browser, groupDn, body) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    await withLdapGroupMember(groupDn, env.biberDn, () => body(context.request));
  } finally {
    await context.close().catch(() => {});
  }
}

exports.register = function (shared) {
  test("biber: without a Gitea role, biber signs in as a regular Gitea user", async ({ browser }) => {
    skipUnlessLdapLogin(shared);
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const self = await signInAsBiber(context.request, shared);
      expect(self.login, "the LDAP source must resolve biber's own account").toBe(env.biberUsername);
      expect(self.is_admin, "a realm user outside the administrator role group must not be a Gitea administrator").toBe(false);
      expect(self.restricted, "a realm user outside the restricted role group must not be restricted").toBe(false);
    } finally {
      await context.close().catch(() => {});
    }
  });

  test("biber: membership in the administrator group makes biber a Gitea administrator", async ({ browser }) => {
    skipUnlessLdapLogin(shared);
    await withBiberInGroup(browser, env.administratorGroupDn, async (request) => {
      await expect
        .poll(async () => (await signInAsBiber(request, shared)).is_admin, {
          timeout: resolveTimeout(60_000),
          message: `biber in ${env.administratorGroupDn} must become a Gitea administrator at the next sign-in`,
        })
        .toBe(true);
    });
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      await expect
        .poll(async () => (await signInAsBiber(context.request, shared)).is_admin, {
          timeout: resolveTimeout(60_000),
          message: "leaving the administrator role group must revoke the Gitea administrator flag at the next sign-in",
        })
        .toBe(false);
    } finally {
      await context.close().catch(() => {});
    }
  });

  test("biber: membership in the restricted group makes biber a restricted Gitea user", async ({ browser }) => {
    skipUnlessLdapLogin(shared);
    await withBiberInGroup(browser, env.restrictedGroupDn, async (request) => {
      await expect
        .poll(async () => (await signInAsBiber(request, shared)).restricted, {
          timeout: resolveTimeout(60_000),
          message: `biber in ${env.restrictedGroupDn} must become a restricted Gitea user at the next sign-in`,
        })
        .toBe(true);
    });
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      await expect
        .poll(async () => (await signInAsBiber(context.request, shared)).restricted, {
          timeout: resolveTimeout(60_000),
          message: "leaving the restricted role group must lift the restriction at the next sign-in",
        })
        .toBe(false);
    } finally {
      await context.close().catch(() => {});
    }
  });
};
