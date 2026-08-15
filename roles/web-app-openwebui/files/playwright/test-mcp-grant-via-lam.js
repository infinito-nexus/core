const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { performKeycloakLoginForm } = require("./personas");

const LDAP_MEMBER_ATTRIBUTE = "member";

function firstExpectedServer(shared) {
  const servers = (shared.env.mcpExpectedServers || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  expect(
    servers.length,
    "the deploy must have discovered at least one MCP server when the mcp service is enabled"
  ).toBeGreaterThan(0);
  return servers.slice().sort()[0];
}

async function servedToolIds(page, shared) {
  const token = await page.evaluate(() => window.localStorage.getItem("token"));
  expect(token, "OpenWebUI must store a session token after login").toBeTruthy();

  const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
  const response = await page.request.get(`${base}/api/v1/tools/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(
    response.ok(),
    `the tool list must answer the signed-in user (HTTP ${response.status()})`
  ).toBeTruthy();
  return JSON.stringify(await response.json());
}

async function signInToLam(page, shared) {
  await page.goto(`${shared.env.lamBaseUrl.replace(/\/+$/, "")}/`);

  if (/\/protocol\/openid-connect\//.test(page.url())) {
    await performKeycloakLoginForm(
      page,
      shared.env.adminUsername,
      shared.env.adminPassword
    );
  }

  await expect(
    page,
    "LAM must be reached after the SSO hop, not left on the identity provider"
  ).not.toHaveURL(/\/protocol\/openid-connect\//, { timeout: 60_000 });

  const passwordField = page
    .locator("input[type='password'], input[name='passwd'], input#passwd")
    .first();
  await expect(
    passwordField,
    "LAM must present its own login form after the SSO hop; the proxy does not bind to LDAP for us"
  ).toBeVisible({ timeout: 60_000 });

  const userSelect = page.getByRole("combobox", { name: /user ?name/i }).first();
  if (await userSelect.isVisible().catch(() => false)) {
    const bindRdnValue = shared.env.ldapBindDn.split(",")[0].split("=").slice(1).join("=");
    await userSelect.selectOption({ label: bindRdnValue });
  }

  await passwordField.fill(shared.env.ldapBindPassword);
  await page.getByRole("button", { name: /login|anmelden/i }).first().click();

  await expect(
    passwordField,
    "LAM must accept the bind credential instead of returning its login form"
  ).toBeHidden({ timeout: 60_000 });
}

async function addMemberViaLamTree(page, shared, groupCn, username) {
  const base = shared.env.lamBaseUrl.replace(/\/+$/, "");
  const groupDn = `cn=${groupCn},${shared.env.ldapRoleDnBase}`;
  const dnParam = encodeURIComponent(Buffer.from(groupDn, "utf8").toString("base64"));
  await page.goto(`${base}/lam/templates/tools/treeView.php?dn=${dnParam}`);

  await expect(
    page.getByText(new RegExp(`cn=${groupCn}\\b`)).first(),
    `LAM must open the ${groupCn} role group; an empty tree here means the LDAP bind did not take`
  ).toBeVisible({ timeout: 60_000 });

  const addValue = page
    .getByRole("link", { name: new RegExp(`add\\s+value|${LDAP_MEMBER_ATTRIBUTE}`, "i") })
    .first();
  await expect(
    addValue,
    `LAM must offer an editable ${LDAP_MEMBER_ATTRIBUTE} attribute on ${groupCn}`
  ).toBeVisible({ timeout: 30_000 });
  await addValue.click();

  const memberField = page
    .locator(`input[name*='${LDAP_MEMBER_ATTRIBUTE}'], textarea[name*='${LDAP_MEMBER_ATTRIBUTE}']`)
    .last();
  await expect(
    memberField,
    `LAM must expose an input for the new ${LDAP_MEMBER_ATTRIBUTE} value`
  ).toBeVisible({ timeout: 30_000 });
  await memberField.fill(`uid=${username},${shared.env.ldapUserDnBase}`);

  await page
    .getByRole("button", { name: /save|update|change/i })
    .first()
    .click();

  await expect(
    page.getByText(new RegExp(`uid=${username}\\b`)).first(),
    `LAM must show ${username} among the ${LDAP_MEMBER_ATTRIBUTE} values after saving`
  ).toBeVisible({ timeout: 60_000 });
}

exports.register = function (shared) {
  test("biber gains MCP access only once the administrator grants it in LAM", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("mcp");
    test.skip(
      !shared.env.lamBaseUrl,
      "LAM_BASE_URL is empty; web-app-lam is not in this deployment's inventory"
    );
    test.setTimeout(420_000);

    const server = firstExpectedServer(shared);
    const groupCn = `${server}-mcp`;

    await shared.signInViaDashboardOidc(
      page,
      shared.env.biberUsername,
      shared.env.biberPassword,
      "biber"
    );
    expect(
      await servedToolIds(page, shared),
      `${server} is granted to its mcp group, which biber is not in yet, so its tools must not be served`
    ).not.toContain(server);
    await shared.expectSignInRequiredAfterLogout(page);

    await page.context().clearCookies();
    await signInToLam(page, shared);
    await addMemberViaLamTree(page, shared, groupCn, shared.env.biberUsername);
    await page.context().clearCookies();

    await shared.signInViaDashboardOidc(
      page,
      shared.env.biberUsername,
      shared.env.biberPassword,
      "biber"
    );
    expect(
      await servedToolIds(page, shared),
      `biber now holds ${groupCn}; absence here means the groups claim, the OIDC group mapping or the access grant is wrong`
    ).toContain(server);
  });
};
