const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

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

  const usernameField = page
    .locator("input[name='username'], input#username, input[name='user']")
    .first();
  await expect(
    usernameField,
    "LAM's LDAP bind form must expose a user field"
  ).toBeVisible({ timeout: 60_000 });

  const passwordField = page
    .locator("input[type='password'], input[name='passwd'], input#passwd")
    .first();
  await expect(
    passwordField,
    "LAM's LDAP bind form must expose a password field"
  ).toBeVisible({ timeout: 30_000 });

  await usernameField.fill(shared.env.ldapBindDn);
  await passwordField.fill(shared.env.ldapBindPassword);
  await page
    .locator("button[type='submit'], input[type='submit']")
    .first()
    .click();

  await expect(
    page.locator("body"),
    "LAM must leave its login form after a successful bind"
  ).not.toContainText(/login\s*failed|wrong\s*password|invalid\s*credentials/i, {
    timeout: 60_000,
  });
}

async function addMemberViaLamTree(page, shared, groupCn, username) {
  const base = shared.env.lamBaseUrl.replace(/\/+$/, "");
  await page.goto(`${base}/templates/tree/treeView.php`);

  const groupNode = page.getByRole("link", { name: new RegExp(`cn=${groupCn}\\b`) }).first();
  await expect(
    groupNode,
    `LAM's directory tree must show the ${groupCn} role group`
  ).toBeVisible({ timeout: 60_000 });
  await groupNode.click();

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
  await memberField.fill(`cn=${username},${shared.env.ldapUserDnBase}`);

  await page
    .locator("button[type='submit'], input[type='submit']")
    .filter({ hasText: /save|update|change/i })
    .first()
    .click();

  await expect(
    page.locator("body"),
    "LAM must confirm the directory write rather than report an error"
  ).not.toContainText(/error|failed|denied/i, { timeout: 60_000 });
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
