const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { performKeycloakLoginForm } = require("./personas");

const LDAP_MEMBER_ATTRIBUTE = "member";
const MEMBER_VALUE_LIST = `#attributeList_${LDAP_MEMBER_ATTRIBUTE}`;
const MEMBER_VALUE_INPUT = `input.lam-attr-${LDAP_MEMBER_ATTRIBUTE}`;
const ADD_VALUE_LINK = "a[onclick*='treeview.addValue']";
const CLEAR_VALUE_LINK = "a[onclick*='treeview.clearValue']";
const SAVE_BUTTON_NAME = /^\s*save\s*$/i;

const CLAIM_PROPAGATION_MS = 120_000;

const PERSONA_CONTEXT = {
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 1100 },
};

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

async function sessionHeaders(page) {
  const token = await page.evaluate(() => window.localStorage.getItem("token"));
  expect(token, "OpenWebUI must store a session token after login").toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

async function servedToolIds(page, shared) {
  const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
  const response = await page.request.get(`${base}/api/v1/tools/`, {
    headers: await sessionHeaders(page),
  });
  expect(
    response.ok(),
    `the tool list must answer the signed-in user (HTTP ${response.status()})`
  ).toBeTruthy();
  return JSON.stringify(await response.json());
}

async function sessionUserId(page, shared) {
  const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
  const response = await page.request.get(`${base}/api/v1/auths/`, {
    headers: await sessionHeaders(page),
  });
  expect(
    response.ok(),
    `the session endpoint must answer the signed-in user (HTTP ${response.status()})`
  ).toBeTruthy();
  const id = (await response.json())?.id;
  expect(id, "OpenWebUI must report the id of the signed-in user").toBeTruthy();
  return id;
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

async function openMemberValueList(page, shared, groupCn) {
  const base = shared.env.lamBaseUrl.replace(/\/+$/, "");
  const groupDn = `cn=${groupCn},${shared.env.ldapRoleDnBase}`;
  const dnParam = encodeURIComponent(Buffer.from(groupDn, "utf8").toString("base64"));
  await page.goto(`${base}/lam/templates/tools/treeView.php?dn=${dnParam}`);

  await expect(
    page.getByRole("heading", { name: new RegExp(`^cn=${groupCn},`) }).first(),
    `LAM must open the ${groupCn} role group; a missing entry heading means the LDAP bind did not take`
  ).toBeVisible({ timeout: 60_000 });

  const memberList = page.locator(MEMBER_VALUE_LIST);
  await expect(
    memberList,
    `LAM must render ${groupCn}'s ${LDAP_MEMBER_ATTRIBUTE} attribute as an editable value list`
  ).toBeVisible({ timeout: 30_000 });
  return memberList;
}

function memberValues(memberList) {
  return memberList
    .locator(MEMBER_VALUE_INPUT)
    .evaluateAll((inputs) => inputs.map((input) => input.value));
}

async function saveLamEntry(page) {
  await page.getByRole("button", { name: SAVE_BUTTON_NAME }).first().click();
}

async function revokeMemberInLam(page, shared, groupCn, memberDn) {
  const memberList = await openMemberValueList(page, shared, groupCn);
  const values = await memberValues(memberList);
  if (!values.includes(memberDn)) {
    return;
  }

  await memberList
    .locator("li")
    .nth(values.indexOf(memberDn))
    .locator(CLEAR_VALUE_LINK)
    .click();
  await saveLamEntry(page);

  await expect
    .poll(() => memberValues(memberList), {
      timeout: 60_000,
      message: `LAM must drop ${memberDn} from ${groupCn}`,
    })
    .not.toContain(memberDn);
}

async function grantMemberInLam(page, shared, groupCn, memberDn) {
  const memberList = await openMemberValueList(page, shared, groupCn);
  expect(
    await memberValues(memberList),
    `${groupCn} must not already list ${memberDn}; the grant under test would prove nothing`
  ).not.toContain(memberDn);

  await memberList.locator(ADD_VALUE_LINK).first().click();
  await memberList.locator(MEMBER_VALUE_INPUT).last().fill(memberDn);
  await saveLamEntry(page);

  await expect
    .poll(() => memberValues(memberList), {
      timeout: 60_000,
      message: `LAM must persist ${memberDn} as a ${LDAP_MEMBER_ATTRIBUTE} of ${groupCn}`,
    })
    .toContain(memberDn);
}

async function grantedGroupId(page, shared, server) {
  const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
  const response = await page.request.get(`${base}/api/v1/configs/tool_servers`, {
    headers: await sessionHeaders(page),
  });
  expect(
    response.ok(),
    `the administrator must read the tool-server config (HTTP ${response.status()})`
  ).toBeTruthy();
  const connection = ((await response.json())?.TOOL_SERVER_CONNECTIONS || []).find(
    (entry) => entry?.info?.id === server
  );
  expect(connection, `${server} must be a configured tool server`).toBeTruthy();
  const groupId = (connection.config?.access_grants || [])[0]?.principal_id;
  expect(groupId, `${server} must name the group its access grant points at`).toBeTruthy();
  return groupId;
}

/**
 * Take one member out of the Open WebUI group an MCP server grants read to.
 *
 * Args:
 *   page: a page holding an administrator session.
 *   shared: the role's shared spec helpers.
 *   groupId: the Open WebUI group carrying the server's access grant.
 *   memberId: the Open WebUI user id to remove.
 *
 * Withdrawing the LDAP membership does not reach Open WebUI on its own: its
 * OIDC sync drops a stale group only while the user's groups claim is
 * non-empty, and a user whose only grant was just withdrawn arrives with an
 * empty one. This write is what makes the revocation visible.
 */
async function dropGroupMember(page, shared, groupId, memberId) {
  const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
  const headers = await sessionHeaders(page);

  const listed = await page.request.post(`${base}/api/v1/groups/id/${groupId}/users`, { headers });
  expect(
    listed.ok(),
    `the administrator must list the members of ${groupId} (HTTP ${listed.status()})`
  ).toBeTruthy();
  if (!(await listed.json()).some((member) => member?.id === memberId)) {
    return;
  }

  const removed = await page.request.post(`${base}/api/v1/groups/id/${groupId}/users/remove`, {
    headers,
    data: { user_ids: [memberId] },
  });
  expect(
    removed.ok(),
    `the administrator must remove the revoked member from ${groupId} (HTTP ${removed.status()})`
  ).toBeTruthy();
}

async function discardSession(page, shared) {
  const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
  if (page.url().startsWith(base)) {
    await page.evaluate(() => window.localStorage.clear());
  }
  await page.context().clearCookies();
}

async function pollBiberTools(page, shared, server, expectServed, resetOnMiss) {
  const deadline = Date.now() + CLAIM_PROPAGATION_MS;
  for (;;) {
    await discardSession(page, shared);
    await shared.signInViaDashboardOidc(
      page,
      shared.env.biberUsername,
      shared.env.biberPassword,
      "biber"
    );
    const userId = await sessionUserId(page, shared);
    const served = await servedToolIds(page, shared);
    if (served.includes(server) === expectServed || Date.now() >= deadline) {
      return { served, userId };
    }
    if (resetOnMiss) {
      await resetOnMiss(userId);
    }
  }
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
    test.setTimeout(600_000);

    const server = firstExpectedServer(shared);
    const groupCn = `${server}-mcp`;
    const memberDn = `uid=${shared.env.biberUsername},${shared.env.ldapUserDnBase}`;

    const browser = page.context().browser();
    const lamPage = await (await browser.newContext(PERSONA_CONTEXT)).newPage();
    const adminPage = await (await browser.newContext(PERSONA_CONTEXT)).newPage();

    await signInToLam(lamPage, shared);
    await shared.signInViaDashboardOidc(
      adminPage,
      shared.env.adminUsername,
      shared.env.adminPassword,
      "administrator"
    );
    const groupId = await grantedGroupId(adminPage, shared, server);

    await revokeMemberInLam(lamPage, shared, groupCn, memberDn);

    let biberId = null;
    try {
      const denied = await pollBiberTools(page, shared, server, false, async (userId) => {
        biberId = userId;
        await dropGroupMember(adminPage, shared, groupId, userId);
      });
      biberId = denied.userId;
      expect(
        denied.served,
        `${server} is granted to ${groupCn}, which biber is not in yet, so its tools must not be served`
      ).not.toContain(server);

      await shared.expectSignInRequiredAfterLogout(page);

      await grantMemberInLam(lamPage, shared, groupCn, memberDn);

      const allowed = await pollBiberTools(page, shared, server, true, null);
      expect(
        allowed.served,
        `biber now holds ${groupCn}; absence here means the groups claim, the OIDC group mapping or the access grant is wrong`
      ).toContain(server);
    } finally {
      await revokeMemberInLam(lamPage, shared, groupCn, memberDn);
      if (biberId) {
        await dropGroupMember(adminPage, shared, groupId, biberId);
      }
    }
  });
};
