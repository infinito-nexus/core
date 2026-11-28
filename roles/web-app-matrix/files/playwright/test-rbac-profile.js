const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue } = require("./personas");

const STALE_DISPLAY_NAME = "infinito-stale-display-name";

function mxidOf(shared, username) {
  return `@${username.toLowerCase()}:${shared.env.matrixServerName}`;
}

function adminUserUrl(shared, username) {
  return `${shared.env.matrixBaseUrl}/_synapse/admin/v2/users/${encodeURIComponent(mxidOf(shared, username))}`;
}

async function adminGetUser(request, shared, auth, username) {
  const response = await request.get(adminUserUrl(shared, username), {
    headers: auth,
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  if (response.status() === 404) return null;
  expect(response.status(), `Synapse admin API lookup of ${username} must succeed`).toBe(200);
  return response.json();
}

async function logout(request, shared, auth) {
  await request
    .post(`${shared.env.matrixBaseUrl}/_matrix/client/v3/logout`, {
      headers: auth,
      data: {},
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    })
    .catch(() => {});
}

async function signInBiberInFreshContext(browser, shared) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await shared.installCspViolationObserver(page);
    await shared.signInViaElementOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");
  } finally {
    await ctx.close().catch(() => {});
  }
}

exports.register = function (shared) {
  test("rbac: the Synapse admin flag follows the administrator role", async ({ request }) => {
    const { adminUsername, adminPassword, biberUsername } = shared.env;
    const session = await shared.loginViaApi(request, adminUsername, adminPassword);
    try {
      const admin = await adminGetUser(request, shared, session.auth, adminUsername);
      expect(admin, "the administrator must own a Synapse account").not.toBeNull();
      expect(Boolean(admin.admin), "the administrator MUST be a Synapse server admin").toBe(true);
      const biber = await adminGetUser(request, shared, session.auth, biberUsername);
      if (biber) {
        expect(
          Boolean(biber.admin),
          "biber holds no administrator role and MUST NOT be a Synapse server admin",
        ).toBe(false);
      }
    } finally {
      await logout(request, shared, session.auth);
    }
  });

  test("profile: biber's OIDC login resyncs the display name and binds the email", async ({ browser, request }) => {
    shared.skipUnlessServiceEnabled("sso");
    const { adminUsername, adminPassword, biberUsername, biberEmail } = shared.env;
    expect(biberEmail, "BIBER_EMAIL must be set").toBeTruthy();
    const session = await shared.loginViaApi(request, adminUsername, adminPassword);
    try {
      if (!(await adminGetUser(request, shared, session.auth, biberUsername))) {
        await signInBiberInFreshContext(browser, shared);
      }
      const staleResponse = await request.put(adminUserUrl(shared, biberUsername), {
        headers: session.auth,
        data: { displayname: STALE_DISPLAY_NAME },
        failOnStatusCode: false,
        timeout: resolveTimeout(30_000),
      });
      expect(staleResponse.status(), "setting a stale display name on biber must succeed").toBe(200);

      await signInBiberInFreshContext(browser, shared);

      const biber = await adminGetUser(request, shared, session.auth, biberUsername);
      expect(biber, "biber must own a Synapse account after the OIDC login").not.toBeNull();
      expect(
        biber.displayname,
        "sso.update_profile_information MUST replace the stale display name with the IdP name claim",
      ).not.toBe(STALE_DISPLAY_NAME);
      expect(biber.displayname, "biber's display name must not be empty").toBeTruthy();
      const emails = (biber.threepids || [])
        .filter((threepid) => threepid.medium === "email")
        .map((threepid) => String(threepid.address).toLowerCase());
      expect(emails, "email_template MUST bind biber's IdP email as a 3PID").toContain(biberEmail.toLowerCase());
    } finally {
      await logout(request, shared, session.auth);
    }
  });

  test("biber: the LDAP login takes the display name from the directory full name", async ({ request }) => {
    shared.skipUnlessServiceEnabled("ldap");
    shared.skipUnlessServiceDisabled("sso");
    test.skip(
      decodeDotenvQuotedValue(process.env.MATRIX_FLAVOR) !== "ansible",
      "only the ansible flavor wires the Synapse LDAP password provider",
    );
    const { adminUsername, adminPassword, biberUsername, biberPassword, biberDirectoryFullName } = shared.env;
    expect(biberDirectoryFullName, "BIBER_DIRECTORY_FULL_NAME must be set").toBeTruthy();
    const biberSession = await shared.loginViaApi(request, biberUsername, biberPassword);
    await logout(request, shared, biberSession.auth);
    const session = await shared.loginViaApi(request, adminUsername, adminPassword);
    try {
      const biber = await adminGetUser(request, shared, session.auth, biberUsername);
      expect(biber, "biber must own a Synapse account after the LDAP login").not.toBeNull();
      expect(
        biber.displayname,
        "the LDAP provider MUST name biber after LDAP.USER.ATTRIBUTES.FULLNAME",
      ).toBe(biberDirectoryFullName);
    } finally {
      await logout(request, shared, session.auth);
    }
  });
};
