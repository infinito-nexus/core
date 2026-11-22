const { randomUUID } = require("node:crypto");
const { resolveTimeout } = require("./timeouts");
const { apiFetchOnion, keycloakAdminToken, requireDotenvValue, withLdapAttributes } = require("./personas");

const CLEANUP_DEADLINE_MS = 30_000;

/**
 * Run `body` while the directory entry of `username` holds the mailbox address the RBAC sync timer gives a user created at runtime.
 *
 * Args:
 *   username: login of a user Keycloak wrote into the directory.
 *   body: async function receiving the mailbox address.
 *
 * Returns:
 *   the value `body` resolves to.
 */
async function withMailbox(username, body) {
  const dn = requireDotenvValue(process.env.LDAP_USER_DN_TEMPLATE, "LDAP_USER_DN_TEMPLATE").replace("<uid>", username);
  const attribute = requireDotenvValue(process.env.LDAP_MAIL_ATTRIBUTE, "LDAP_MAIL_ATTRIBUTE");
  const address = `${username}@${requireDotenvValue(process.env.DOMAIN_PRIMARY, "DOMAIN_PRIMARY")}`;
  return withLdapAttributes(dn, { [attribute]: address }, () => body(address));
}

function withDeadline(promise, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`${label} exceeded ${CLEANUP_DEADLINE_MS} ms`)), resolveTimeout(CLEANUP_DEADLINE_MS)),
    ),
  ]);
}

async function createKeycloakUser(request, env, person) {
  const token = await keycloakAdminToken(request, env.keycloakBaseUrl, env.keycloakAdminUsername, env.keycloakAdminPassword);
  const response = await apiFetchOnion(request, `${env.keycloakBaseUrl}/admin/realms/${encodeURIComponent(env.keycloakRealm)}/users`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    data: {
      username: person.username,
      firstName: person.firstName,
      lastName: person.lastName,
      email: person.email,
      emailVerified: true,
      enabled: true,
      credentials: [{ type: "password", value: person.password, temporary: false }],
    },
  });
  if (response.status() !== 201) {
    throw new Error(`Keycloak user creation failed: ${response.status()} ${await response.text()}`);
  }
  return response.headers()["location"].split("/").pop();
}

async function deleteKeycloakUser(request, env, userId) {
  const token = await keycloakAdminToken(request, env.keycloakBaseUrl, env.keycloakAdminUsername, env.keycloakAdminPassword);
  const response = await apiFetchOnion(request, `${env.keycloakBaseUrl}/admin/realms/${encodeURIComponent(env.keycloakRealm)}/users/${userId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (![204, 404].includes(response.status())) {
    throw new Error(`Keycloak user deletion failed: ${response.status()} ${await response.text()}`);
  }
}

async function deletePenpotProfile(page, env) {
  const response = await apiFetchOnion(page.request, `${env.baseUrl}/api/rpc/command/delete-profile?_fmt=json`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    data: {},
  });
  if (!response.ok()) {
    throw new Error(`Penpot profile deletion failed: ${response.status()} ${await response.text()}`);
  }
}

exports.register = (shared) => {
  const { test, expect, skipUnlessServiceEnabled, env } = shared;

  test("OIDC: a first login registers the Penpot profile with the Keycloak name and e-mail claims", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    const mailbox = requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox";
    test.setTimeout(resolveTimeout(240_000));
    expect(env.keycloakBaseUrl, "KEYCLOAK_BASE_URL must be set").toBeTruthy();
    expect(env.keycloakRealm, "KEYCLOAK_REALM_NAME must be set").toBeTruthy();
    expect(env.keycloakAdminUsername, "KEYCLOAK_ADMIN_USERNAME must be set").toBeTruthy();
    expect(env.keycloakAdminPassword, "KEYCLOAK_ADMIN_PASSWORD must be set").toBeTruthy();
    expect(env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    const suffix = randomUUID().replace(/[^a-z1-9]/g, "").slice(0, 6);
    const person = {
      username: `penpot${suffix}`,
      firstName: "Penpot",
      lastName: `Profile ${suffix}`,
      email: `penpot${suffix}@${env.canonicalDomain}`.toLowerCase(),
      password: `Pw-${randomUUID()}!`,
    };
    const expectedName = `${person.firstName} ${person.lastName}`;

    const admin = await browser.newContext({ ignoreHTTPSErrors: true });
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    let userId = "";
    let registered = false;
    try {
      userId = await createKeycloakUser(admin.request, env, person);

      const register = async (claimedEmail) => {
        await shared.penpotOidcAuthenticate(page, person.username, person.password);
        expect(shared.onOidcRegistration(page), `a first OIDC login of ${person.username} must land on the Penpot registration form`).toBe(true);
        const prefilled = await shared.confirmFirstOidcSignIn(page, expectedName);
        expect(prefilled, "the registration form must carry the name claim Keycloak sent").toBe(expectedName);
        await shared.assertAuthenticated(page);
        registered = true;

        const profile = await shared.penpotProfile(page);
        expect(profile.email, "the Penpot profile must carry the e-mail claim Keycloak sent").toBe(claimedEmail);
        expect(profile.fullname, "the Penpot profile must carry the name claim Keycloak sent").toBe(expectedName);
      };
      if (mailbox) {
        await withMailbox(person.username, register);
      } else {
        await register(person.email);
      }
    } finally {
      if (registered) {
        await withDeadline(deletePenpotProfile(page, env), `deleting the Penpot profile of ${person.username}`).catch((err) =>
          console.warn(`Cleanup of the Penpot profile ${person.email} failed: ${err}`),
        );
      }
      if (userId) {
        await withDeadline(deleteKeycloakUser(admin.request, env, userId), `deleting the Keycloak user ${person.username}`).catch((err) =>
          console.warn(`Cleanup of the Keycloak user ${person.username} failed: ${err}`),
        );
      }
      await context.clearCookies().catch(() => {});
      await context.close().catch(() => {});
      await admin.close().catch(() => {});
    }
  });
};
