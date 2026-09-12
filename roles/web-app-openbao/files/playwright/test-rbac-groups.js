const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const baseUrl = normalizeBaseUrl(process.env.OPENBAO_BASE_URL || "");
const kvMount = decodeDotenvQuotedValue(process.env.OPENBAO_KV_MOUNT || "");
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME || "");
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || "");
const lamBaseUrl = normalizeBaseUrl(process.env.LAM_BASE_URL || "");
const lamOauth2Fronted = String(process.env.LAM_OAUTH2_FRONTED || "").toLowerCase() === "true";
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const ldapAdminPassword = decodeDotenvQuotedValue(process.env.LDAP_ADMIN_PASSWORD || "");
const groupDnTemplate = decodeDotenvQuotedValue(process.env.LDAP_RBAC_GROUP_DN_TEMPLATE || "");
const userDnTemplate = decodeDotenvQuotedValue(process.env.LDAP_USER_DN_TEMPLATE || "");

const RBAC_ROLES = ["administrator", "operator", "reader"];
const PROBE_PATH = `${kvMount}/data/playwright/rbac-probe`;
const POLICY_PATH = "sys/policies/acl/operator";

const groupDn = (role) => groupDnTemplate.replace("<role>", role);
const biberDn = () => userDnTemplate.replace("<uid>", biberUsername);
const groupCn = (role) => groupDn(role).replace(/^cn=/, "").split(",")[0];
const rootSuffix = () => groupDn("administrator").split(",").slice(-2).join(",");

test.use({ ignoreHTTPSErrors: true });

async function signInToLam(page) {
  await gotoOnion(page, `${lamBaseUrl}/lam/templates/login.php`, { waitUntil: "load" });

  if (lamOauth2Fronted) {
    const keycloakUsername = page.locator("input[name='username'], input#username").first();
    if (await keycloakUsername.isVisible().catch(() => false)) {
      await keycloakUsername.fill(adminUsername);
      await page.locator("input[name='password'], input#password").first().fill(adminPassword);
      await page
        .locator("button[type='submit'], input[name='login'], input[type='submit']")
        .first()
        .click({ timeout: resolveTimeout(30_000) });
      await page.waitForLoadState("networkidle");
    }
  }

  const lamPassword = page.locator("input[name='passwd'], input#passwd").first();
  await expect(lamPassword, "LAM must present its bind-password form").toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await lamPassword.fill(ldapAdminPassword);
  await page
    .locator("button[type='submit'], input[type='submit']")
    .first()
    .click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("networkidle");

  await expect(
    page.locator("a[href*='list.php?type=user']").first(),
    "the administrator must reach LAM's account menu after signing in",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

// LAM's group list only renders posixGroup entries, and the RBAC role groups are
// groupOfNames under ou=roles, so the members are edited through the Multi edit
// tool, which applies an attribute operation to every entry matching a filter.
async function setGroupMembership(page, role, operation) {
  await gotoOnion(page, `${lamBaseUrl}/lam/templates/tools/multiEdit.php`, { waitUntil: "load" });
  await page.waitForLoadState("networkidle");

  await page.locator("select#suffix").selectOption(rootSuffix());
  await page.locator("input#filter").fill(`(cn=${groupCn(role)})`);
  await page.locator("select#op_0").selectOption(operation);
  await page.locator("input#attr_0").fill("member");
  await page.locator("input#val_0").fill(biberDn());

  await page.locator("#btn_applyChanges").click({ timeout: resolveTimeout(30_000) });
}

// LAM applies the change asynchronously, so the directory is only consistent
// some time after the click. Poll the effect rather than the tool's own wording.
async function expectTierAfterLam(request, role, present) {
  await expect
    .poll(async () => (await loginAsBiber(request)).policies.includes(role), {
      timeout: resolveTimeout(60_000),
      message: present
        ? `LAM adding ${biberDn()} to ${groupCn(role)} must grant the '${role}' policy`
        : `LAM removing ${biberDn()} from ${groupCn(role)} must revoke the '${role}' policy`,
    })
    .toBe(present);
  return loginAsBiber(request);
}

async function loginAsBiber(request) {
  const response = await request.post(
    `${baseUrl}/v1/auth/ldap/login/${encodeURIComponent(biberUsername)}`,
    { data: { password: biberPassword }, failOnStatusCode: false, timeout: resolveTimeout(30_000) },
  );
  expect(
    response.status(),
    `the LDAP auth method must accept ${biberUsername}, got ${response.status()}`,
  ).toBe(200);
  const body = await response.json();
  return { policies: body.auth.policies || [], token: body.auth.client_token };
}

const writeProbe = (request, token) =>
  request
    .post(`${baseUrl}/v1/${PROBE_PATH}`, {
      headers: { "X-Vault-Token": token },
      data: { data: { probe: "rbac" } },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    })
    .then((r) => r.status());

const readProbe = (request, token) =>
  request
    .get(`${baseUrl}/v1/${PROBE_PATH}`, {
      headers: { "X-Vault-Token": token },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    })
    .then((r) => r.status());

const readPolicy = (request, token) =>
  request
    .get(`${baseUrl}/v1/${POLICY_PATH}`, {
      headers: { "X-Vault-Token": token },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    })
    .then((r) => r.status());

// What each tier must be able to do, read off templates/policies/*.hcl.j2.
const TIER_CAPABILITIES = {
  administrator: async (request, token) => {
    expect(
      await readPolicy(request, token),
      "the administrator tier must read a policy definition",
    ).toBe(200);
  },
  operator: async (request, token) => {
    expect(
      [200, 204],
      "the operator tier must write an application secret",
    ).toContain(await writeProbe(request, token));
    expect(
      await readPolicy(request, token),
      "the operator tier must not read policy definitions",
    ).toBe(403);
  },
  reader: async (request, token) => {
    expect(
      await writeProbe(request, token),
      "the reader tier must not write an application secret",
    ).toBe(403);
    expect(
      [200, 404],
      "the reader tier must be permitted to read the application path",
    ).toContain(await readProbe(request, token));
  },
};

test.describe("rbac: the OpenBao tiers follow LDAP group membership", () => {
  test.describe.configure({ mode: "serial" });

  test("rbac: biber starts outside every OpenBao role group", async ({ request }) => {
    skipUnlessServiceEnabled("ldap");

    const { policies, token } = await loginAsBiber(request);
    for (const role of RBAC_ROLES) {
      expect(policies, `biber must hold no '${role}' policy before any group change`).not.toContain(
        role,
      );
    }
    expect(
      await readPolicy(request, token),
      "a member of no role group must not read policy definitions",
    ).toBe(403);
    expect(
      await writeProbe(request, token),
      "a member of no role group must not write an application secret",
    ).toBe(403);
  });

  for (const role of RBAC_ROLES) {
    test(`rbac: LAM granting the ${role} group hands biber that tier, and revoking takes it back`, async ({
      page,
      request,
    }) => {
      skipUnlessServiceEnabled("ldap");
      test.skip(!isServiceEnabled("lam"), "LAM not deployed (LAM_SERVICE_ENABLED=false)");
      test.setTimeout(resolveTimeout(180_000));

      await signInToLam(page);
      await setGroupMembership(page, role, "add");

      const granted = await expectTierAfterLam(request, role, true);
      for (const other of RBAC_ROLES.filter((candidate) => candidate !== role)) {
        expect(
          granted.policies,
          `biber must not receive the '${other}' policy while only in the ${role} group`,
        ).not.toContain(other);
      }
      await TIER_CAPABILITIES[role](request, granted.token);

      await setGroupMembership(page, role, "del");

      const revoked = await expectTierAfterLam(request, role, false);
      expect(
        await readPolicy(request, revoked.token),
        "a revoked member must not read policy definitions",
      ).toBe(403);
    });
  }
});
