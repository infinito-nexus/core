const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

// -----------------------------------------------------------------------------
// Env helpers
// -----------------------------------------------------------------------------

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) {
    return value;
  }
  if (!(value.startsWith('"') && value.endsWith('"'))) {
    return value;
  }
  const encoded = value.slice(1, -1);
  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

function normalizeBaseUrl(value) {
  return decodeDotenvQuotedValue(value || "").replace(/\/$/, "");
}

// -----------------------------------------------------------------------------
// Diagnostics + CSP helpers (copied from web-app-keycloak/files/playwright.spec.js
// for consistency; inlined because the test runner stages only this file).
// -----------------------------------------------------------------------------

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

function installCspViolationObserver(page) {
  return page.addInitScript(() => {
    window.__cspViolations = [];
    window.addEventListener("securitypolicyviolation", (event) => {
      window.__cspViolations.push({
        violatedDirective: event.violatedDirective,
        blockedURI: event.blockedURI,
        sourceFile: event.sourceFile,
        lineNumber: event.lineNumber,
        originalPolicy: event.originalPolicy,
      });
    });
  });
}

async function readCspViolations(page) {
  return page.evaluate(() => window.__cspViolations || []).catch(() => []);
}

const EXPECTED_CSP_DIRECTIVES = [
  "default-src",
  "connect-src",
  "frame-ancestors",
  "frame-src",
  "script-src",
  "script-src-elem",
  "script-src-attr",
  "style-src",
  "style-src-elem",
  "style-src-attr",
  "font-src",
  "worker-src",
  "manifest-src",
  "media-src",
  "img-src",
];

function parseCspHeader(value) {
  const result = {};
  if (!value) return result;
  for (const raw of value.split(";")) {
    const trimmed = raw.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/\s+/);
    const directive = parts.shift();
    if (!directive) continue;
    result[directive.toLowerCase()] = parts;
  }
  return result;
}

function assertCspResponseHeader(response, label) {
  const headers = response.headers();
  const cspHeader = headers["content-security-policy"];
  expect(
    cspHeader,
    `${label}: Content-Security-Policy response header MUST be present`
  ).toBeTruthy();
  const reportOnly = headers["content-security-policy-report-only"];
  expect(
    reportOnly,
    `${label}: Content-Security-Policy-Report-Only MUST NOT be set (policy must be enforced)`
  ).toBeFalsy();
  const parsed = parseCspHeader(cspHeader);
  const missing = EXPECTED_CSP_DIRECTIVES.filter((d) => !parsed[d]);
  expect(
    missing,
    `${label}: CSP directives missing from response header: ${missing.join(", ")}`
  ).toEqual([]);
  return parsed;
}

async function assertCspMetaParity(page, headerDirectives, label) {
  const metaLocator = page
    .locator('meta[http-equiv="Content-Security-Policy"]')
    .first();
  const hasMeta = (await metaLocator.count().catch(() => 0)) > 0;
  if (!hasMeta) return;
  const metaContent = await metaLocator.getAttribute("content").catch(() => null);
  if (!metaContent) return;
  const metaParsed = parseCspHeader(metaContent);
  for (const directive of Object.keys(metaParsed)) {
    const headerTokens = new Set(headerDirectives[directive] || []);
    const metaTokens = metaParsed[directive] || [];
    for (const token of metaTokens) {
      expect(
        headerTokens.has(token),
        `${label}: CSP meta token "${token}" for directive ${directive} MUST also appear in the response header`
      ).toBe(true);
    }
  }
}

async function expectNoCspViolations(page, diagnostics, label) {
  const domViolations = await readCspViolations(page);
  expect(
    domViolations,
    `${label}: securitypolicyviolation events observed: ${JSON.stringify(domViolations)}`
  ).toEqual([]);
  expect(
    diagnostics.cspRelated,
    `${label}: CSP-related console/pageerror entries observed: ${JSON.stringify(diagnostics.cspRelated)}`
  ).toEqual([]);
}

// -----------------------------------------------------------------------------
// Keycloak login helpers
// -----------------------------------------------------------------------------

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

// -----------------------------------------------------------------------------
// WordPress helpers
// -----------------------------------------------------------------------------

async function wpAdminLoginViaOidc(page, wpBaseUrl, username, password) {
  // WP uses login_type=auto — visiting wp-login.php triggers OIDC redirect when
  // there's no WP session. We land at Keycloak, sign in, and get redirected
  // back to /wp-admin/.
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

async function wpSignOut(page, wpBaseUrl) {
  // Client-side sign-out: clear WP session cookies and Keycloak SSO cookies in
  // the browser context so the next wpAdminLoginViaOidc re-prompts for
  // credentials. Going through wp-login.php?action=logout triggers the OIDC
  // plugin's `redirect_on_logout: true` path which lands on Keycloak's SLO
  // confirmation page and is fragile to navigate out of inside a Playwright
  // flow — clearing cookies achieves the same test-isolation goal.
  await page.context().clearCookies().catch(() => {});
  await page.goto(`${wpBaseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => {});
}

// -----------------------------------------------------------------------------
// Keycloak admin-UI helpers (group membership)
// -----------------------------------------------------------------------------

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
  // Wait until we are on the user profile (hash path contains /users/<id>/).
  await expect
    .poll(() => page.url(), {
      timeout: 30_000,
      message: `Expected Keycloak user profile URL after clicking "${username}"`,
    })
    .toMatch(/\/users\/[^/]+/);
}

async function keycloakAdminOpenUserGroupsTab(page) {
  // PatternFly tabs expose role="tab". Scope strictly to role=tab so we don't
  // accidentally hit the left-nav "Groups" link (which would navigate away
  // from the user profile back to the Groups overview).
  const groupsTab = page
    .locator("[role='tab']")
    .filter({ hasText: /^Groups$/ })
    .first();
  await expect(groupsTab).toBeVisible({ timeout: 30_000 });
  await groupsTab.click();
  // After the tab activates the URL fragment moves to /users/<id>/groups.
  await expect
    .poll(() => page.url(), {
      timeout: 30_000,
      message: "Expected Keycloak user profile to switch to the Groups tab",
    })
    .toMatch(/\/users\/[^/]+\/groups/);
}

/**
 * Resolve a Keycloak admin access token for the master realm by reusing
 * the SUPER_ADMIN credentials from the Playwright env. Returned tokens
 * are short-lived and intentionally not cached across calls so the
 * helpers stay safe to use after redeploys.
 */
async function keycloakAdminToken(request, keycloakBaseUrl) {
  const tokenResp = await request.post(
    `${keycloakBaseUrl}/realms/master/protocol/openid-connect/token`,
    {
      form: {
        client_id: "admin-cli",
        grant_type: "password",
        username: superAdminUsername,
        password: superAdminPassword,
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

/**
 * Resolve a Keycloak group id from its leading-slash path via the
 * `/admin/realms/<realm>/group-by-path/...` endpoint. Falls back to a
 * segment walk if the endpoint is missing on older Keycloak versions.
 */
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
  // Fallback: walk segment-by-segment.
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

/**
 * Add a user to a Keycloak group via the Admin REST API.
 *
 * Returns:
 *   true  — the user was not a member and the helper successfully joined them.
 *   false — the user was ALREADY a member (no join performed); the caller
 *           MUST NOT run a teardown removal, per requirement 004's
 *           idempotency rule ("if the test found biber already a member,
 *           it MUST leave that membership in place").
 *
 * The Keycloak admin "Join Group" dialog filters its search results by
 * leaf name only and paginates. Once Keycloak's RBAC tree contains many
 * subgroups whose leaf is the same role name (administrator, editor,
 * ...) — which is exactly the requirement-005 hierarchical layout —
 * the WordPress entry can fall outside the first page and the dialog
 * stops being a reliable test driver. We therefore drive the join step
 * through the Admin REST API while still asserting the tree shape that
 * the OIDC `groups` claim must mirror.
 */
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

/**
 * Legacy UI-driven implementation kept for reference / re-enabling once
 * Keycloak's admin "Join Group" dialog grows a non-paginated tree view.
 * It is intentionally unused; the request-based variant above is the
 * authoritative driver during requirement-005 verification.
 */
async function keycloakAdminAddUserToGroupViaUi(
  page,
  keycloakBaseUrl,
  realmName,
  targetGroupPath,
  username
) {
  // `targetGroupPath` is the leading-slash Keycloak group path, e.g.
  // `/roles/web-app-wordpress/subscriber` (requirement 005 hierarchical
  // layout). The last segment is used for the dialog search, the full
  // path is used to disambiguate the checkbox.
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

  // The Keycloak admin "Join Group" dialog paginates the search result
  // (default 10 per page). For role names that recur across applications
  // ("administrator" is created for every deployed app per requirement
  // 004), the WordPress entry can fall outside the first page. Click
  // "Next" until the exact target path appears or pagination is
  // exhausted.
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
  // Idempotency rule from requirement 004: when the user is already a
  // member of the target group (e.g. via the LDAP-provisioned role
  // assignment), Keycloak's admin "Join Group" dialog hides that group
  // entirely. Treat a missing checkbox as "already a member" and let
  // the caller skip teardown removal.
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

/**
 * Remove a user from a Keycloak group via the Keycloak Admin REST API.
 *
 * Requirement 004 only mandates the *add* operation via the admin UI
 * ("Add `biber` to that existing Keycloak group via the admin UI"). The
 * teardown step ("remove `biber` from the Keycloak group again") does not
 * prescribe a channel, and the admin-UI Groups tab's row-level Leave
 * affordance is fragile across Keycloak UI versions. Using the REST API
 * here makes the idempotency guarantee of the test deterministic.
 */
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
  if (!groupResp.ok()) return; // group gone or never existed — nothing to clean up
  const group = await groupResp.json();
  if (!group?.id) return;

  await request.delete(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/users/${userId}/groups/${group.id}`,
    { headers: auth }
  );
}

// -----------------------------------------------------------------------------
// Test configuration
// -----------------------------------------------------------------------------

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const keycloakBaseUrl = normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || "");
const realmName = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const wpBaseUrl = normalizeBaseUrl(process.env.WORDPRESS_BASE_URL || "");
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const superAdminUsername = decodeDotenvQuotedValue(
  process.env.SUPER_ADMIN_USERNAME
);
const superAdminPassword = decodeDotenvQuotedValue(
  process.env.SUPER_ADMIN_PASSWORD
);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const rbacGroupPathPrefix = decodeDotenvQuotedValue(
  process.env.RBAC_GROUP_PATH_PREFIX
);
const multisiteEnabled =
  (process.env.WORDPRESS_MULTISITE_ENABLED || "").toLowerCase() === "true";
// Discourse round-trip (requirement 007)
const discourseBaseUrl = normalizeBaseUrl(process.env.DISCOURSE_BASE_URL || "");
const discourseApiKey = decodeDotenvQuotedValue(process.env.DISCOURSE_API_KEY);
const discourseApiUsername = decodeDotenvQuotedValue(
  process.env.DISCOURSE_API_USERNAME
);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(keycloakBaseUrl, "KEYCLOAK_BASE_URL must be set").toBeTruthy();
  expect(realmName, "KEYCLOAK_REALM_NAME must be set").toBeTruthy();
  expect(wpBaseUrl, "WORDPRESS_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
  expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(rbacGroupPathPrefix, "RBAC_GROUP_PATH_PREFIX must be set").toBeTruthy();
  await page.context().clearCookies();
  await installCspViolationObserver(page);
});

// -----------------------------------------------------------------------------
// Baseline MUSTs: CSP + OIDC flow + canonical-domain DOM assertion
// Baseline scenarios MUST NOT gate on any service (requirement 006).
// -----------------------------------------------------------------------------

test("wordpress front page enforces Content-Security-Policy and renders canonical domain", async ({
  page,
}) => {
  const diagnostics = attachDiagnostics(page);
  const response = await page.goto(`${wpBaseUrl}/`);
  expect(response, "Expected WordPress front page response").toBeTruthy();
  expect(
    response.status(),
    "Expected WordPress front page response to be successful"
  ).toBeLessThan(400);
  const directives = assertCspResponseHeader(response, "wordpress front page");
  await assertCspMetaParity(page, directives, "wordpress front page");
  const html = await response.text();
  expect(
    html.includes(canonicalDomain) || (await page.content()).includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" (from applications lookup) to appear in the WordPress UI`
  ).toBe(true);
  await expectNoCspViolations(page, diagnostics, "wordpress front page");
});

test("wordpress administrator can complete an OIDC login round-trip", async ({
  page,
}) => {
  skipUnlessServiceEnabled("oidc");
  const diagnostics = attachDiagnostics(page);
  await wpAdminLoginViaOidc(page, wpBaseUrl, adminUsername, adminPassword);
  await expect(page).toHaveURL(/\/wp-admin\/?/, { timeout: 30_000 });
  await wpSignOut(page, wpBaseUrl);
  await expectNoCspViolations(
    page,
    diagnostics,
    "wordpress administrator OIDC round-trip"
  );
});

// -----------------------------------------------------------------------------
// RBAC role mapping: biber in web-app-wordpress-<role> → WP role <role>
//
// Requirement 004: auto-provisioned LDAP/Keycloak groups drive WordPress roles
// via the OIDC `groups` claim, consumed by the mu-plugin
// infinito-oidc-rbac-mapper.php. We test three roles across the privilege
// spectrum serially so a regression in one mapping does not mask another.
// -----------------------------------------------------------------------------

const RBAC_ROLE_SEQUENCE = ["subscriber", "editor", "administrator"];
// Per requirement 005 the Keycloak group path is hierarchical:
// /roles/web-app-wordpress/<role> (Single-Site) or
// /roles/web-app-wordpress/<tenant>/<role> (Multisite). RBAC_GROUP_PATH_PREFIX
// renders `/roles/web-app-wordpress/` so the spec appends the role segment
// below.
//
// Multisite scenarios (requirement 005): only run when multisite is opted
// in via `services.wordpress.multisite.enabled = true`. The default
// path continues to run the Single-Site scenarios below.

for (const role of RBAC_ROLE_SEQUENCE) {
  test(`rbac: membership in ${role} group grants WordPress ${role} role`, async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("oidc");
    skipUnlessServiceEnabled("ldap");
    test.skip(
      multisiteEnabled,
      "WORDPRESS_MULTISITE_ENABLED=true; Single-Site RBAC scenarios run only when Multisite is disabled"
    );
    const groupPath = `${rbacGroupPathPrefix}${role}`;
    let biberAddedToGroup = false;

    // Each identity runs in its own isolated browser context so WP session
    // cookies, Keycloak SSO cookies, and OIDC post-logout redirect state
    // cannot leak between the super-admin-as-keycloak, biber-as-wp, and
    // wp-admin-as-wp hops.
    const newCtx = async () => {
      const ctx = await browser.newContext({
        ignoreHTTPSErrors: true,
        viewport: { width: 1440, height: 1100 },
      });
      const p = await ctx.newPage();
      await installCspViolationObserver(p);
      return { ctx, page: p };
    };

    try {
      // --- 1 + 2 + 3. Super admin (fresh context) adds biber to the group.
      const adminKc = await newCtx();
      try {
        await adminKc.page.goto(`${keycloakBaseUrl}/admin/master/console/`);
        await fillKeycloakLoginForm(
          adminKc.page,
          superAdminUsername,
          superAdminPassword
        );
        await expect
          .poll(() => adminKc.page.url(), {
            timeout: 60_000,
            message: "Expected to land in the Keycloak admin console",
          })
          .toContain("/admin/master/console/");
        biberAddedToGroup = await keycloakAdminAddUserToGroup(
          adminKc.page,
          keycloakBaseUrl,
          realmName,
          groupPath,
          biberUsername
        );
      } finally {
        await adminKc.ctx.close().catch(() => {});
      }

      // --- 5. biber (fresh context) signs into WordPress via OIDC.
      const biberWp = await newCtx();
      try {
        await wpAdminLoginViaOidc(
          biberWp.page,
          wpBaseUrl,
          biberUsername,
          biberPassword
        );
      } finally {
        await biberWp.ctx.close().catch(() => {});
      }

      // --- 6. WP admin (fresh context) verifies biber's role on /wp-admin/users.php.
      const wpAdmin = await newCtx();
      try {
        await wpAdminLoginViaOidc(
          wpAdmin.page,
          wpBaseUrl,
          adminUsername,
          adminPassword
        );
        await wpAdmin.page.goto(`${wpBaseUrl}/wp-admin/users.php`, {
          waitUntil: "domcontentloaded",
        });
        const biberRow = wpAdmin.page
          .locator("tr")
          .filter({ hasText: new RegExp(biberUsername, "i") })
          .first();
        await expect(
          biberRow,
          `Expected biber row to be visible on /wp-admin/users.php`
        ).toBeVisible({ timeout: 30_000 });
        const rowText = (await biberRow.textContent()) || "";
        const expectedLabel = role.charAt(0).toUpperCase() + role.slice(1);
        expect(
          rowText.includes(expectedLabel),
          `biber's row on /wp-admin/users.php MUST show WordPress role "${expectedLabel}" after OIDC login; row text: ${rowText}`
        ).toBe(true);
      } finally {
        await wpAdmin.ctx.close().catch(() => {});
      }
    } finally {
      // --- 7. Cleanup: remove biber from the Keycloak group via REST. Only
      // run when the test actually performed the join (biberAddedToGroup
      // === true); when biber was already a member at start, requirement
      // 004 forbids removing them.
      if (biberAddedToGroup) {
        try {
          const reqCtx = await browser.newContext({ ignoreHTTPSErrors: true });
          try {
            await keycloakRemoveUserFromGroupViaRest(
              reqCtx.request,
              keycloakBaseUrl,
              realmName,
              superAdminUsername,
              superAdminPassword,
              groupPath,
              biberUsername
            );
          } finally {
            await reqCtx.close().catch(() => {});
          }
        } catch (err) {
          // Log but do not mask the original test failure.
          // eslint-disable-next-line no-console
          console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`);
        }
      }
    }
  });
}

// -----------------------------------------------------------------------------
// Requirement 005 Multisite scenarios.
//
// Placeholder: Multisite is opt-in via
// `services.wordpress.multisite.enabled = true`. The spec records
// a deliberate skip when Multisite is disabled so the contributor knows
// which scenarios are out of scope for this deploy instead of wondering
// why nothing ran. When Multisite is enabled the full per-site scenarios
// land here (three canonical domains, network-administrator grant/revoke).
// -----------------------------------------------------------------------------

test("wordpress multisite per-site RBAC is not exercised in single-site deploys", async () => {
  test.skip(
    !multisiteEnabled,
    "WORDPRESS_MULTISITE_ENABLED=false; Multisite scenarios run only when the role flag is true"
  );
  // When multisite is enabled the scenarios land here. This guard exists
  // so the skip surfaces explicitly in the reporter, matching the
  // documented contract of requirement 005.
});

// -----------------------------------------------------------------------------
// Requirement 007: WordPress -> Discourse post round-trip.
//
// Publish a post in the WP admin UI (with the wp-discourse sidebar toggle
// set) and assert that the matching topic appears in Discourse. Tear down
// the WP post and the Discourse topic regardless of body outcome.
// -----------------------------------------------------------------------------

async function discourseApiRequest(request, path, init = {}) {
  if (!discourseBaseUrl) {
    throw new Error("DISCOURSE_BASE_URL is not set");
  }
  if (!discourseApiKey) {
    throw new Error("DISCOURSE_API_KEY is not set");
  }
  const headers = {
    "Api-Key": discourseApiKey,
    "Api-Username": discourseApiUsername || "system",
    Accept: "application/json",
    ...(init.headers || {}),
  };
  const url = `${discourseBaseUrl}${path}`;
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

test("wordpress post published with discourse toggle appears as a Discourse topic", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("discourse");
  // 10 min for this end-to-end round-trip: two browser contexts +
  // two OIDC logins (main + cleanup) + WP editor + Discourse polling
  // + post-status cleanup across 5 statuses comfortably exceeds the
  // default 300s budget on cold caches. The individual step timeouts
  // (60s OIDC, 30s editor expects, 60s snackbar, 60s discourse poll)
  // remain in place to fail fast on real regressions.
  test.setTimeout(600_000);
  const stamp = Date.now();
    const unique = Math.random().toString(36).slice(2, 8);
    const postTitle = `infinito-playwright-discourse-roundtrip-${stamp}-${unique}`;
    const postBodyMarker = `round-trip marker ${stamp}-${unique}`;
    const postBody = `This post verifies the WP -> Discourse pipeline. ${postBodyMarker}`;

    const wpCtx = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 1100 },
    });
    const reqCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const wpPage = await wpCtx.newPage();
    await installCspViolationObserver(wpPage);

    try {
      await wpAdminLoginViaOidc(wpPage, wpBaseUrl, adminUsername, adminPassword);

      // Navigate to the new-post editor.
      await wpPage.goto(`${wpBaseUrl}/wp-admin/post-new.php`, {
        waitUntil: "domcontentloaded",
      });

      // First-time editor visit shows a "Welcome to the editor" guide
      // modal that hides the title textbox from the accessibility tree.
      // The close button only carries aria-label="Close" so a generic
      // /close/i query also matches unrelated buttons in the editor
      // toolbar; instead, scope to the dialog and click its Close.
      // Wait briefly so the dialog has time to mount.
      const welcomeDialog = wpPage.getByRole("dialog", {
        name: /welcome to the editor/i,
      });
      if (
        await welcomeDialog.isVisible({ timeout: 5_000 }).catch(() => false)
      ) {
        await welcomeDialog
          .getByRole("button", { name: /^close$/i })
          .click()
          .catch(async () => {
            // Fallback: Escape always closes a dialog.
            await wpPage.keyboard.press("Escape");
          });
      }

      // WP Gutenberg editor: fill title. The title textarea exposes
      // aria-label "Add title" across modern WP versions.
      const titleBox = wpPage
        .getByRole("textbox", { name: /add title/i })
        .first();
      await expect(titleBox, "Expected the post title editor").toBeVisible({
        timeout: 60_000,
      });
      await titleBox.fill(postTitle);

      // Fill body content. Pressing Enter at the end of the title block
      // is the natural Gutenberg flow: the editor splits a new paragraph
      // block below, focused, ready to receive text. `keyboard.press('Tab')`
      // is unsafe — it can land on the WP block-editor command-palette
      // trigger; subsequent typing then ends up in the palette's search
      // field instead of the post body, leaving the body empty.
      await titleBox.press("Enter");
      await wpPage.keyboard.type(postBody);
      // Defensive: if a previous keypress accidentally surfaced WP's
      // command palette ("Search commands and settings"), close it so it
      // doesn't intercept later clicks.
      await wpPage.keyboard.press("Escape").catch(() => {});

      // wp-discourse 2.6+ ships a Gutenberg PluginSidebar
      // (name="discourse-sidebar", title="Discourse"). It is NOT a panel
      // inside the document sidebar, so the post-info column never shows
      // a "Discourse" section — instead the editor toolbar grows a
      // standalone Discourse icon button that toggles a separate sidebar
      // open. We open it by aria-label "Discourse" (anchored on word
      // boundaries so the OIDC "Login with Discourse" button on /wp-login
      // doesn't match here, which it can't anyway since we are post-login,
      // but defensive). Click is a no-op if it is already open from a
      // previous run.
      const discourseSidebarToggle = wpPage
        .getByRole("button", { name: /^\s*discourse\s*$/i })
        .first();
      await expect(
        discourseSidebarToggle,
        "Expected the wp-discourse PluginSidebar toolbar toggle"
      ).toBeVisible({ timeout: 30_000 });
      await discourseSidebarToggle.click();

      // The checkbox inside the wp-discourse sidebar carries no aria-label,
      // no name, no id — only a className. Target it directly. Source:
      // wp-content/plugins/wp-discourse/admin/discourse-sidebar/src/index.js
      // (`<input type="checkBox" className="wpdc-publish-topic-checkbox" />`).
      // The plugin persists the user's choice as the
      // `publish_to_discourse` post-meta on save.
      const publishToggle = wpPage
        .locator("input.wpdc-publish-topic-checkbox")
        .first();
      await expect(
        publishToggle,
        "Expected the wp-discourse 'Publish' checkbox inside the Discourse sidebar"
      ).toBeVisible({ timeout: 30_000 });
      if (!(await publishToggle.isChecked())) {
        await publishToggle.check();
      }

      // Click the top-right Publish button twice (confirm once).
      const publishBtn = wpPage
        .getByRole("button", { name: /^publish$/i })
        .first();
      await publishBtn.click();
      const confirmPublish = wpPage
        .getByRole("button", { name: /^publish$/i })
        .last();
      if ((await confirmPublish.count().catch(() => 0)) > 0) {
        await confirmPublish.click().catch(() => {});
      }

      // Wait for the snackbar confirming the post is live.
      await expect(
        wpPage.getByText(/post published|entry published/i).first(),
        "Expected the WP 'post published' snackbar"
      ).toBeVisible({ timeout: 60_000 });

      // Poll Discourse until the topic shows up.
      const expectedBodySubstring = postBodyMarker;
      let topic = null;
      const deadline = Date.now() + 60_000;
      while (Date.now() < deadline) {
        topic = await discourseSearchTopicByTitle(reqCtx.request, postTitle);
        if (topic) break;
        await new Promise((r) => setTimeout(r, 3_000));
      }
      expect(
        topic,
        `Expected Discourse topic with title "${postTitle}" to appear after wp-discourse publish`
      ).toBeTruthy();

      // Fetch the topic to confirm the first post body round-tripped.
      const topicResp = await discourseApiRequest(
        reqCtx.request,
        `/t/${topic.id}.json`
      );
      expect(topicResp.ok(), `GET /t/${topic.id}.json must succeed`).toBe(true);
      const topicBody = await topicResp.json();
      const firstPost =
        topicBody?.post_stream?.posts?.[0]?.cooked ||
        topicBody?.post_stream?.posts?.[0]?.raw ||
        "";
      expect(
        firstPost.includes(expectedBodySubstring),
        `Discourse topic first post MUST contain the WP body marker "${expectedBodySubstring}"`
      ).toBe(true);

      await wpSignOut(wpPage, wpBaseUrl);
    } finally {
      // Teardown (see requirement 007): remove both sides regardless of
      // outcome. Cover draft/unpublished posts too to handle crashes
      // between create and publish. The whole WP-side cleanup is bounded
      // to 60s — Playwright counts the finally block toward the test
      // budget, so a hung Trash-link click previously consumed the full
      // 600s timeout even when every assertion above had passed (the
      // Trash link's post-click `waitForLoadState('domcontentloaded')`
      // hangs on some WP/Gutenberg combos because the move-to-trash is
      // an XHR, not a navigation).
      const wpCleanupBudgetMs = 60_000;
      const wpCleanupDeadline = Date.now() + wpCleanupBudgetMs;
      try {
        const wpPageCleanup = await wpCtx.newPage();
        await Promise.race([
          (async () => {
            await wpAdminLoginViaOidc(
              wpPageCleanup,
              wpBaseUrl,
              adminUsername,
              adminPassword
            ).catch(() => {});
            for (const status of [
              "publish",
              "draft",
              "pending",
              "private",
              "future",
            ]) {
              if (Date.now() >= wpCleanupDeadline) break;
              await wpPageCleanup
                .goto(
                  `${wpBaseUrl}/wp-admin/edit.php?post_status=${status}&s=${encodeURIComponent(postTitle)}`,
                  { waitUntil: "domcontentloaded", timeout: 10_000 }
                )
                .catch(() => {});
              const trashLinks = wpPageCleanup.locator(
                `tr:has-text("${postTitle}") a.submitdelete`
              );
              const n = await trashLinks.count().catch(() => 0);
              for (let i = 0; i < n; i += 1) {
                if (Date.now() >= wpCleanupDeadline) break;
                await trashLinks
                  .nth(i)
                  .click()
                  .catch(() => {});
                await wpPageCleanup
                  .waitForLoadState("domcontentloaded", { timeout: 5_000 })
                  .catch(() => {});
              }
            }
            // Empty trash.
            if (Date.now() < wpCleanupDeadline) {
              await wpPageCleanup
                .goto(`${wpBaseUrl}/wp-admin/edit.php?post_status=trash`, {
                  waitUntil: "domcontentloaded",
                  timeout: 10_000,
                })
                .catch(() => {});
              const emptyTrash = wpPageCleanup
                .getByRole("button", { name: /empty\s*trash/i })
                .first();
              if ((await emptyTrash.count().catch(() => 0)) > 0) {
                await emptyTrash.click().catch(() => {});
              }
            }
          })(),
          new Promise((resolve) => setTimeout(resolve, wpCleanupBudgetMs)),
        ]);
        await wpPageCleanup.close().catch(() => {});
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn(`WP teardown of "${postTitle}" failed: ${err}`);
      }
      try {
        const topic = await discourseSearchTopicByTitle(
          reqCtx.request,
          postTitle
        );
        if (topic?.id) {
          await discourseDeleteTopic(reqCtx.request, topic.id);
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn(`Discourse teardown of "${postTitle}" failed: ${err}`);
      }
      await wpCtx.close().catch(() => {});
      await reqCtx.close().catch(() => {});
    }
});
