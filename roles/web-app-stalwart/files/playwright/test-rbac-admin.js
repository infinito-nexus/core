const { test, expect } = require("@playwright/test");

const { safeSkipUnlessEnabled } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const {
  appBaseUrl,
  adminUsername,
  biberUsername,
  stalwartAdminUsername,
  stalwartAdminPassword,
} = require("./env");

const SYSTEM_ADMINISTRATOR = "System Administrator";

async function managementCall(request, methodCalls) {
  const response = await request.post(`${appBaseUrl}/jmap/`, {
    headers: {
      Authorization: `Basic ${Buffer.from(`${stalwartAdminUsername}:${stalwartAdminPassword}`).toString("base64")}`,
      "Content-Type": "application/json",
    },
    data: { using: ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"], methodCalls },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "the recovery administrator must reach the management JMAP API").toBe(200);
  return (await response.json()).methodResponses;
}

function holdsRole(account, roleId) {
  return Boolean(account && account.roles && account.roles.roleIds && account.roles.roleIds[roleId]);
}

test("rbac: System Administrator follows the administrator members", async ({ request }) => {
  safeSkipUnlessEnabled("sso");
  const [roles, accounts] = await managementCall(request, [
    ["x:Role/get", { ids: null }, "roles"],
    ["x:Account/get", { ids: null }, "accounts"],
  ]);
  const adminRole = roles[1].list.find((role) => role.description === SYSTEM_ADMINISTRATOR);
  expect(adminRole, `Stalwart must expose the built-in ${SYSTEM_ADMINISTRATOR} role`).toBeTruthy();
  const users = accounts[1].list.filter((account) => account["@type"] === "User");

  const admin = users.find((account) => account.name === adminUsername);
  expect(admin, "the administrator must own a Stalwart account").toBeTruthy();
  expect(holdsRole(admin, adminRole.id), `the administrator MUST hold ${SYSTEM_ADMINISTRATOR}`).toBe(true);

  const biber = users.find((account) => account.name === biberUsername);
  if (biber) {
    expect(
      holdsRole(biber, adminRole.id),
      `biber holds no administrator role and MUST NOT hold ${SYSTEM_ADMINISTRATOR}`,
    ).toBe(false);
  }
});
