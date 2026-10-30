const { apiFetchOnion, decodeDotenvQuotedValue, requireDotenvValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const teamId = decodeDotenvQuotedValue(requireDotenvValue(process.env.PENPOT_RBAC_TEAM_ID, "PENPOT_RBAC_TEAM_ID"));
const teamName = decodeDotenvQuotedValue(requireDotenvValue(process.env.PENPOT_RBAC_TEAM_NAME, "PENPOT_RBAC_TEAM_NAME"));

function flag(permissions, name) {
  const kebab = name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
  return permissions[name] ?? permissions[kebab];
}

exports.register = (shared) => {
  const { test, expect, skipUnlessServiceDisabled, skipUnlessServiceEnabled, env, penpotNativeLogin, penpotLdapLogin } = shared;

  async function platformTeam(page) {
    const response = await apiFetchOnion(page.request, `${env.baseUrl}/api/rpc/command/get-teams?_fmt=json`, { method: "GET" });
    expect(response.status(), "Expected get-teams to answer for the signed-in administrator").toBe(200);
    const team = (await response.json()).find((candidate) => candidate.id === teamId);
    expect(team, "the deploy must create the shared platform team").toBeTruthy();
    expect(team.name).toBe(teamName);
    return team;
  }

  test("administrator: signs in over LDAP and owns the shared platform team", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(120_000));
    await penpotLdapLogin(page, env.adminEmail, env.adminPassword);
    const team = await platformTeam(page);
    expect(flag(team.permissions, "isOwner"), "the platform administrator must own the shared team").toBe(true);
  });

  test("administrator: signs in with the native password and owns the shared platform team", async ({ page }) => {
    skipUnlessServiceDisabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(120_000));
    await penpotNativeLogin(page, env.adminEmail, env.adminPassword);
    const team = await platformTeam(page);
    expect(flag(team.permissions, "isOwner"), "the platform administrator must own the shared team").toBe(true);
  });
};
