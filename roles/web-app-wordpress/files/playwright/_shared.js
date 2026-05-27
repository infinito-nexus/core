const { expect } = require("@playwright/test");

const {
  decodeDotenvQuotedValue,
  installCspViolationObserver,
  normalizeBaseUrl,
} = require("./personas");

const env = {
  appBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL || ""),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  wpBaseUrl: normalizeBaseUrl(process.env.WORDPRESS_BASE_URL || ""),
  oidcIssuerUrl: decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
  rbacGroupPathPrefix: decodeDotenvQuotedValue(process.env.RBAC_GROUP_PATH_PREFIX),
  multisiteEnabled:
    (process.env.WORDPRESS_MULTISITE_ENABLED || "").toLowerCase() === "true",
  discourseBaseUrl: normalizeBaseUrl(process.env.DISCOURSE_BASE_URL || ""),
  discourseApiKey: decodeDotenvQuotedValue(process.env.DISCOURSE_API_KEY),
  discourseApiUsername: decodeDotenvQuotedValue(process.env.DISCOURSE_API_USERNAME),
};

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const cspRelated = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
    if (/content security policy|csp/i.test(message.text())) {
      cspRelated.push({ source: "console", text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    const text = String(error);
    pageErrors.push(text);
    if (/content security policy|csp/i.test(text)) {
      cspRelated.push({ source: "pageerror", text });
    }
  });
  return { consoleErrors, pageErrors, cspRelated };
}

async function fillKeycloakLoginForm(page, username, password) {
  const usernameField = page
    .locator("input[name='username'], input#username")
    .first();
  const passwordField = page
    .locator("input[name='password'], input#password")
    .first();
  const signInButton = page
    .locator(
      "input#kc-login, button#kc-login, button[type='submit'], input[type='submit']"
    )
    .first();
  await expect(
    usernameField,
    "Expected Keycloak username field to be visible"
  ).toBeVisible({ timeout: 60_000 });
  await usernameField.fill(username);
  await passwordField.fill(password);
  await signInButton.click();
}

// WP uses login_type=auto — visiting wp-login.php triggers OIDC redirect when
// there's no WP session. We land at Keycloak, sign in, and get redirected
// back to /wp-admin/.
async function wpAdminLoginViaOidc(page, wpBaseUrl, username, password) {
  await page.goto(`${wpBaseUrl}/wp-login.php`, { waitUntil: "domcontentloaded" });
  const url = page.url();
  if (!url.includes(wpBaseUrl)) {
    await fillKeycloakLoginForm(page, username, password);
  }
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected redirect back to ${wpBaseUrl}/wp-admin after OIDC login`,
    })
    .toContain("/wp-admin");
}

// Client-side sign-out: clearing cookies achieves the same test-isolation
// goal as wp-login.php?action=logout but avoids the OIDC plugin's
// `redirect_on_logout: true` SLO-confirmation hop which is fragile to
// navigate out of inside a Playwright flow.
async function wpSignOut(page, wpBaseUrl) {
  await page.context().clearCookies().catch(() => {});
  await page.goto(`${wpBaseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => {});
}

async function keycloakAdminOpenUserProfile(
  page,
  keycloakBaseUrl,
  realmName,
  username
) {
  await page.goto(`${keycloakBaseUrl}/admin/master/console/#/${realmName}/users`, {
    waitUntil: "domcontentloaded",
  });
  const searchInput = page
    .locator("input[placeholder*='Search'], input[name='search']")
    .first();
  await expect(searchInput).toBeVisible({ timeout: 60_000 });
  await searchInput.fill(username);
  await searchInput.press("Enter");
  const userRowLink = page
    .locator("table a, [role='gridcell'] a, a[data-testid='user-row']")
    .filter({ hasText: new RegExp(`^${username}$`, "i") })
    .first();
  await expect(userRowLink).toBeVisible({ timeout: 60_000 });
  await userRowLink.click();
  await expect
    .poll(() => page.url(), {
      timeout: 30_000,
      message: `Expected Keycloak user profile URL after clicking "${username}"`,
    })
    .toMatch(/\/users\/[^/]+/);
}

// Scope strictly to role=tab so we don't accidentally hit the left-nav
// "Groups" link, which would navigate away from the user profile back
// to the Groups overview.
async function keycloakAdminOpenUserGroupsTab(page) {
  const groupsTab = page
    .locator("[role='tab']")
    .filter({ hasText: /^Groups$/ })
    .first();
  await expect(groupsTab).toBeVisible({ timeout: 30_000 });
  await groupsTab.click();
  await expect
    .poll(() => page.url(), {
      timeout: 30_000,
      message: "Expected Keycloak user profile to switch to the Groups tab",
    })
    .toMatch(/\/users\/[^/]+\/groups/);
}

// Returned tokens are short-lived and intentionally not cached across
// calls so the helpers stay safe to use after redeploys.
async function keycloakAdminToken(request, keycloakBaseUrl) {
  const tokenResp = await request.post(
    `${keycloakBaseUrl}/realms/master/protocol/openid-connect/token`,
    {
      form: {
        client_id: "admin-cli",
        grant_type: "password",
        username: env.superAdminUsername,
        password: env.superAdminPassword,
      },
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    }
  );
  if (!tokenResp.ok()) {
    throw new Error(
      `Keycloak admin token request failed: ${tokenResp.status()} ${await tokenResp.text()}`
    );
  }
  const json = await tokenResp.json();
  if (!json.access_token) {
    throw new Error("Keycloak admin token response missing access_token");
  }
  return json.access_token;
}

// Resolve via /admin/realms/<realm>/group-by-path/...; fall back to a
// segment walk if the endpoint is missing on older Keycloak versions.
async function keycloakResolveGroupId(
  request,
  keycloakBaseUrl,
  realmName,
  accessToken,
  groupPath
) {
  const headers = { Authorization: `Bearer ${accessToken}` };
  const trimmed = groupPath.replace(/^\//, "");
  const byPath = await request.get(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/group-by-path/${trimmed}`,
    { headers }
  );
  if (byPath.ok()) {
    const group = await byPath.json();
    if (group?.id) return group.id;
  }
  const segments = trimmed.split("/").filter((s) => s !== "");
  if (segments.length === 0) {
    throw new Error(`Empty Keycloak group path: ${groupPath}`);
  }
  let parentId = null;
  for (let i = 0; i < segments.length; i++) {
    const wanted = segments[i];
    const url = parentId === null
      ? `${keycloakBaseUrl}/admin/realms/${realmName}/groups?max=500&search=${encodeURIComponent(wanted)}`
      : `${keycloakBaseUrl}/admin/realms/${realmName}/groups/${parentId}/children?max=500`;
    const resp = await request.get(url, { headers });
    if (!resp.ok()) {
      throw new Error(
        `Keycloak groups lookup failed at segment ${i} (${wanted}): ${resp.status()} ${await resp.text()}`
      );
    }
    const items = await resp.json();
    let match = null;
    if (parentId === null) {
      const walk = (nodes, depth) => {
        for (const n of nodes) {
          if (depth === 0 && n.name === wanted) return n;
          if (n.subGroups && n.subGroups.length) {
            const r = walk(n.subGroups, depth - 1);
            if (r) return r;
          }
        }
        return null;
      };
      match = walk(items, 0);
    } else {
      match = items.find((n) => n.name === wanted) || null;
    }
    if (!match) {
      throw new Error(
        `Keycloak group "${groupPath}" not found while resolving segment "${wanted}"`
      );
    }
    parentId = match.id;
  }
  return parentId;
}

// Returns:
//   true  — the user was not a member and the helper joined them.
//   false — the user was ALREADY a member; caller MUST NOT teardown-remove
//           (auto-add idempotency contract).
//
// The Keycloak admin "Join Group" dialog filters by leaf name only and
// paginates. Once the RBAC tree contains many subgroups whose leaf is
// the same role name, the WordPress entry can fall outside the first
// page and the dialog stops being a reliable test driver. We drive the
// join through the Admin REST API while still asserting the tree shape
// that the OIDC `groups` claim must mirror.
async function keycloakAdminAddUserToGroup(
  page,
  keycloakBaseUrl,
  realmName,
  targetGroupPath,
  username
) {
  const request = page.context().request;
  const accessToken = await keycloakAdminToken(request, keycloakBaseUrl);
  const headers = { Authorization: `Bearer ${accessToken}` };

  const userResp = await request.get(
    `${keycloakBaseUrl}/admin/realms/${realmName}/users?username=${encodeURIComponent(username)}&exact=true`,
    { headers }
  );
  if (!userResp.ok()) {
    throw new Error(
      `Keycloak user lookup failed: ${userResp.status()} ${await userResp.text()}`
    );
  }
  const users = await userResp.json();
  const user = users.find((u) => u.username === username);
  if (!user) {
    throw new Error(`Keycloak user "${username}" not found`);
  }

  const groupId = await keycloakResolveGroupId(
    request,
    keycloakBaseUrl,
    realmName,
    accessToken,
    targetGroupPath
  );

  const memberResp = await request.get(
    `${keycloakBaseUrl}/admin/realms/${realmName}/users/${user.id}/groups?max=500`,
    { headers }
  );
  if (!memberResp.ok()) {
    throw new Error(
      `Keycloak user-groups lookup failed: ${memberResp.status()} ${await memberResp.text()}`
    );
  }
  const currentGroups = await memberResp.json();
  if (currentGroups.some((g) => g.id === groupId || g.path === targetGroupPath)) {
    return false;
  }

  const joinResp = await request.put(
    `${keycloakBaseUrl}/admin/realms/${realmName}/users/${user.id}/groups/${groupId}`,
    { headers }
  );
  if (!joinResp.ok()) {
    throw new Error(
      `Keycloak join-group failed (user=${username}, group=${targetGroupPath}): ${joinResp.status()} ${await joinResp.text()}`
    );
  }
  return true;
}

// Legacy UI-driven variant kept for re-enabling once Keycloak's admin
// "Join Group" dialog grows a non-paginated tree view. The REST variant
// above is the authoritative driver; this one is preserved through the
// module export so eslint sees it as "used".
async function keycloakAdminAddUserToGroupViaUi(
  page,
  keycloakBaseUrl,
  realmName,
  targetGroupPath,
  username
) {
  const pathSegments = targetGroupPath.replace(/^\//, "").split("/");
  const searchTerm = pathSegments[pathSegments.length - 1];

  await keycloakAdminOpenUserProfile(page, keycloakBaseUrl, realmName, username);
  await keycloakAdminOpenUserGroupsTab(page);

  const joinButton = page
    .locator("button")
    .filter({ hasText: /join\s*group/i })
    .first();
  await expect(
    joinButton,
    "Expected the 'Join Group' button on the user's Groups tab"
  ).toBeVisible({ timeout: 30_000 });
  await joinButton.click();

  const dialog = page.getByRole("dialog", { name: /join groups/i }).first();
  await expect(dialog).toBeVisible({ timeout: 30_000 });

  const dialogSearchBox = dialog.getByRole("textbox", { name: /search/i }).first();
  await expect(dialogSearchBox).toBeVisible({ timeout: 30_000 });
  await dialogSearchBox.fill(searchTerm);
  await dialogSearchBox.press("Enter");

  // The Keycloak admin "Join Group" dialog paginates (default 10/page);
  // for role names that recur across applications, the WordPress entry
  // can fall outside the first page. Click "Next" until the exact target
  // path appears or pagination is exhausted.
  const targetCheckbox = dialog
    .getByRole("checkbox", { name: targetGroupPath, exact: true })
    .first();
  for (let pageIndex = 0; pageIndex < 10; pageIndex++) {
    if (await targetCheckbox.isVisible().catch(() => false)) {
      break;
    }
    const nextButton = dialog
      .getByRole("button", { name: /^next/i })
      .first();
    const nextVisible = await nextButton.isVisible().catch(() => false);
    const nextEnabled = nextVisible
      ? await nextButton.isEnabled().catch(() => false)
      : false;
    if (!nextEnabled) {
      break;
    }
    await nextButton.click();
    await page.waitForTimeout(500);
  }
  // When the user is already a member, Keycloak's "Join Group" dialog
  // hides that group entirely. Treat a missing checkbox as "already a
  // member" and let the caller skip teardown removal.
  const targetCheckboxVisible = await targetCheckbox
    .isVisible()
    .catch(() => false);
  if (!targetCheckboxVisible) {
    await dialog
      .getByRole("button", { name: /^cancel|^close$/i })
      .first()
      .click()
      .catch(() => {});
    await expect(dialog).toBeHidden({ timeout: 30_000 });
    return false;
  }

  if (await targetCheckbox.isDisabled()) {
    await dialog
      .getByRole("button", { name: /^close$/i })
      .first()
      .click()
      .catch(() => {});
    await expect(dialog).toBeHidden({ timeout: 30_000 });
    return false;
  }

  await targetCheckbox.check();
  const confirmJoin = dialog.getByRole("button", { name: /^join$/i }).first();
  await expect(confirmJoin).toBeEnabled({ timeout: 30_000 });
  await confirmJoin.click();
  await expect(dialog).toBeHidden({ timeout: 30_000 });
  const lastSegment = pathSegments[pathSegments.length - 1];
  const membershipRow = page
    .locator("tr, li")
    .filter({ hasText: new RegExp(lastSegment) })
    .first();
  await expect(
    membershipRow,
    `Expected "${targetGroupPath}" to appear as a membership on the user's Groups tab after joining.`
  ).toBeVisible({ timeout: 30_000 });
  return true;
}

// REST teardown: the admin-UI Groups tab's row-level Leave affordance is
// fragile across Keycloak UI versions; the REST API keeps the
// idempotency guarantee deterministic.
async function keycloakRemoveUserFromGroupViaRest(
  request,
  keycloakBaseUrl,
  realmName,
  adminUsername,
  adminPassword,
  groupPath,
  username
) {
  const tokenResp = await request.post(
    `${keycloakBaseUrl}/realms/master/protocol/openid-connect/token`,
    {
      form: {
        client_id: "admin-cli",
        grant_type: "password",
        username: adminUsername,
        password: adminPassword,
      },
    }
  );
  if (!tokenResp.ok()) {
    throw new Error(
      `Admin token request failed (${tokenResp.status()}): ${await tokenResp.text()}`
    );
  }
  const { access_token: accessToken } = await tokenResp.json();
  const auth = { Authorization: `Bearer ${accessToken}` };

  const usersResp = await request.get(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/users?username=${encodeURIComponent(username)}&exact=true`,
    { headers: auth }
  );
  const users = await usersResp.json();
  const userId = users?.[0]?.id;
  if (!userId) return;

  const groupResp = await request.get(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/group-by-path/${groupPath.replace(/^\//, "")}`,
    { headers: auth }
  );
  if (!groupResp.ok()) return;
  const group = await groupResp.json();
  if (!group?.id) return;

  await request.delete(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/users/${userId}/groups/${group.id}`,
    { headers: auth }
  );
}

async function discourseApiRequest(request, path, init = {}) {
  if (!env.discourseBaseUrl) {
    throw new Error("DISCOURSE_BASE_URL is not set");
  }
  if (!env.discourseApiKey) {
    throw new Error("DISCOURSE_API_KEY is not set");
  }
  const headers = {
    "Api-Key": env.discourseApiKey,
    "Api-Username": env.discourseApiUsername || "system",
    Accept: "application/json",
    ...(init.headers || {}),
  };
  const url = `${env.discourseBaseUrl}${path}`;
  const method = (init.method || "GET").toUpperCase();
  if (method === "GET") {
    return request.get(url, { headers });
  }
  if (method === "DELETE") {
    return request.delete(url, { headers });
  }
  throw new Error(`discourseApiRequest: unsupported method ${method}`);
}

async function discourseSearchTopicByTitle(request, title) {
  const resp = await discourseApiRequest(
    request,
    `/search.json?q=${encodeURIComponent(title)}`
  );
  if (!resp.ok()) return null;
  const body = await resp.json();
  const topics = Array.isArray(body?.topics) ? body.topics : [];
  return topics.find((t) => (t.title || "").trim() === title.trim()) || null;
}

async function discourseDeleteTopic(request, topicId) {
  if (!topicId) return;
  await discourseApiRequest(request, `/t/${topicId}.json`, {
    method: "DELETE",
  }).catch(() => {});
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(env.appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(env.keycloakBaseUrl, "KEYCLOAK_BASE_URL must be set").toBeTruthy();
  expect(env.realmName, "KEYCLOAK_REALM_NAME must be set").toBeTruthy();
  expect(env.wpBaseUrl, "WORDPRESS_BASE_URL must be set").toBeTruthy();
  expect(env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(env.superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
  expect(env.superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();
  expect(env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(env.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(env.rbacGroupPathPrefix, "RBAC_GROUP_PATH_PREFIX must be set").toBeTruthy();
  await page.context().clearCookies();
  await installCspViolationObserver(page);
}

module.exports = {
  env,
  attachDiagnostics,
  fillKeycloakLoginForm,
  wpAdminLoginViaOidc,
  wpSignOut,
  keycloakAdminToken,
  keycloakResolveGroupId,
  keycloakAdminAddUserToGroup,
  keycloakAdminOpenUserProfile,
  keycloakAdminOpenUserGroupsTab,
  keycloakAdminAddUserToGroupViaUi,
  keycloakRemoveUserFromGroupViaRest,
  discourseApiRequest,
  discourseSearchTopicByTitle,
  discourseDeleteTopic,
  beforeEach,
};
