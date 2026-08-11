/**
 * Keycloak OIDC login helpers, plus Keycloak Admin REST API helpers for
 * Playwright specs that need to manipulate group membership directly
 * (RBAC-tier tests across web-app-* roles).
 *
 *   `performKeycloakLoginForm(target, username, password)`
 *     Fills the Keycloak login form on `target` (a `Page` OR a
 *     `FrameLocator`) and clicks sign-in. Tolerates both the
 *     role-based selector strategy (`getByRole({ name: /username|
 *     email/i })`, etc.) and the legacy input-name selector strategy
 *     (`input[name='username']`, etc.) so iframe-embedded Keycloak
 *     forms work without branching at the call site. Does NOT assert
 *     post-login navigation.
 *
 *   `performKeycloakLogin(page, username, password, canonicalDomain)`
 *     Calls `performKeycloakLoginForm` and additionally polls the
 *     page URL until it contains `canonicalDomain`, asserting the
 *     OAuth2-Proxy / app callback completes.
 *
 *   `performKeycloakLoginExpectingDenial(page, username, password, canonicalDomain)`
 *     Drives the form with credentials expected to be REJECTED
 *     (insufficient privileges, forbidden role, denied app) and
 *     asserts the round-trip ends on a denial state (Keycloak error
 *     page, the same authorization endpoint with an error indicator,
 *     or a 401 / 403 on the relying party after the callback).
 *     Returns the resulting URL so callers can assert additional
 *     details if needed.
 *
 *   `keycloakAdminToken(request, keycloakBaseUrl, username, password, opts)`
 *     Password-grant token fetch against Keycloak's own bootstrap realm
 *     (default `master`/`admin-cli`, both overridable via `opts` since
 *     they are deployment-configurable, not framework constants).
 *
 *   `keycloakResolveGroupId(request, keycloakBaseUrl, realmName, accessToken, groupPath)`
 *     Resolves a group's internal id from its human-readable path.
 *
 *   `keycloakAdminAddUserToGroup(request, keycloakBaseUrl, realmName, targetGroupPath, username, adminUsername, adminPassword, opts)`
 *     Idempotent group join; returns whether this call performed it.
 *
 *   `keycloakRemoveUserFromGroupViaRest(request, keycloakBaseUrl, realmName, adminUsername, adminPassword, groupPath, username, opts)`
 *     Best-effort group removal (throws on lookup failure, no-ops if the
 *     user/group is already gone).
 */

const { expect } = require("@playwright/test");

// SPOT for the role-side OIDC adapter readiness contract. A role whose
// `templates/javascript/oidc.js.j2` wraps its Login link in a JS click
// handler (e.g. `keycloak.login()` with PKCE) MUST set this flag on
// `window` after the click interceptor is wired, so persona helpers can
// click the link without racing the adapter.
const OIDC_LOGIN_READY_FLAG = "__oidcLoginReady";

async function performKeycloakLoginForm(target, username, password) {
  const usernameField = target
    .getByRole("textbox", { name: /username|email/i })
    .or(target.locator("input[name='username'], input#username"))
    .first();
  const passwordField = target
    .getByRole("textbox", { name: /^password$/i })
    .or(target.locator("input[name='password'], input#password"))
    .first();
  const signInButton = target
    .getByRole("button", { name: /sign in|login|log in/i })
    .or(target.locator("input#kc-login, button#kc-login, button[type='submit'], input[type='submit']"))
    .first();

  await usernameField.waitFor({ state: "visible", timeout: 60_000 });
  await usernameField.fill(username);
  await usernameField.press("Tab").catch(() => {});
  await passwordField.fill(password);
  await signInButton.click();
}

async function performKeycloakLogin(page, username, password, canonicalDomain) {
  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected redirect back to ${canonicalDomain} after Keycloak login`,
    })
    .toContain(canonicalDomain);
}

// Click a role's in-app Login link to start the OIDC chain. Waits for
// the role's adapter to signal readiness (OIDC_LOGIN_READY_FLAG) before
// clicking, so the click hits the JS-wrapped handler (which stores
// PKCE state) and not the raw `href` (which would skip PKCE and break
// the post-login token exchange on PKCE-enforced clients). The 15s
// fallback covers roles whose Login link is purely static. Returns
// true when the navigation reached `openid-connect/auth`.
//
// The persona MUST pass `strictLink` (exact-match locator, e.g. accessible
// name `^\s*login\s*$/i`) AND `looseLink` (substring locator). The helper
// prefers the strict match — that targets the role's OWN Login button
// (e.g. nextcloud's plain `<a>Login</a>`) — and only falls back to the
// loose match when no strict candidate is visible. Without this two-pass
// approach, `sys-front-inj-all`-injected dashboard navbars in oauth2-proxy
// roles trap the substring match and redirect the persona to the dashboard
// flow instead of the role's own auth chain.
async function clickOidcLoginLink(page, strictLink, looseLink) {
  const strictVisible = await strictLink
    .waitFor({ state: "visible", timeout: 20_000 })
    .then(() => true)
    .catch(() => false);
  const loginLink = strictVisible ? strictLink : looseLink;
  if (!strictVisible) {
    const looseVisible = await loginLink
      .waitFor({ state: "visible", timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (!looseVisible) return false;
  }

  await page
    .waitForFunction(
      (flag) => window[flag] === true,
      OIDC_LOGIN_READY_FLAG,
      { timeout: 15_000 },
    )
    .catch(() => {});
  await loginLink.click().catch(() => {});
  await page
    .waitForURL(/openid-connect\/auth/, { timeout: 15_000 })
    .catch(() => {});
  return page.url().includes("openid-connect/auth");
}

async function performKeycloakLoginExpectingDenial(page, username, password, canonicalDomain) {
  await performKeycloakLoginForm(page, username, password);

  await page.waitForLoadState("domcontentloaded", { timeout: 60_000 }).catch(() => {});

  const finalUrl = page.url();
  const denied =
    /access[\s_-]?denied|forbidden|not[\s_-]?authori[sz]ed|unauthori[sz]ed/i.test(
      await page.content().catch(() => ""),
    ) ||
    /openid-connect\/auth/.test(finalUrl) ||
    !finalUrl.includes(canonicalDomain);

  expect(
    denied,
    `Expected ${username} to be DENIED at ${canonicalDomain} after Keycloak login (got URL ${finalUrl})`,
  ).toBe(true);

  return finalUrl;
}

async function keycloakAdminToken(
  request,
  keycloakBaseUrl,
  username,
  password,
  { adminRealm = "master", adminClientId = "admin-cli" } = {},
) {
  const tokenResp = await request.post(
    `${keycloakBaseUrl}/realms/${encodeURIComponent(adminRealm)}/protocol/openid-connect/token`,
    {
      form: {
        client_id: adminClientId,
        grant_type: "password",
        username,
        password,
      },
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    },
  );
  if (!tokenResp.ok()) {
    throw new Error(
      `Keycloak admin token request failed: ${tokenResp.status()} ${await tokenResp.text()}`,
    );
  }
  const json = await tokenResp.json();
  if (!json.access_token) {
    throw new Error("Keycloak admin token response missing access_token");
  }
  return json.access_token;
}

// Resolves a group's internal Keycloak id from its human-readable path
// (e.g. "/roles/web-app-wazuh/administrator"). Tries the direct
// group-by-path admin endpoint first, since it is a single request; some
// Keycloak versions 404 that endpoint for paths containing certain
// characters, so on failure this falls back to walking the group tree one
// path segment at a time (list top-level groups filtered by name, then
// each subsequent segment's children), matching by exact name at each
// depth, and returns the id of the final matched segment.
async function keycloakResolveGroupId(request, keycloakBaseUrl, realmName, accessToken, groupPath) {
  const headers = { Authorization: `Bearer ${accessToken}` };
  const trimmed = groupPath.replace(/^\//, "");
  const byPath = await request.get(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/group-by-path/${trimmed}`,
    { headers },
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
    const url =
      parentId === null
        ? `${keycloakBaseUrl}/admin/realms/${realmName}/groups?max=500&search=${encodeURIComponent(wanted)}`
        : `${keycloakBaseUrl}/admin/realms/${realmName}/groups/${parentId}/children?max=500`;
    const resp = await request.get(url, { headers });
    if (!resp.ok()) {
      throw new Error(
        `Keycloak groups lookup failed at segment ${i} (${wanted}): ${resp.status()} ${await resp.text()}`,
      );
    }
    const items = await resp.json();
    let match;
    if (parentId === null) {
      // The top-level search endpoint returns full subtrees, not just
      // direct matches, so walk each returned tree looking for `wanted`
      // at depth 0 only - a same-named descendant deeper in the tree
      // MUST NOT be mistaken for the top-level segment.
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
      throw new Error(`Keycloak group "${groupPath}" not found while resolving segment "${wanted}"`);
    }
    parentId = match.id;
  }
  return parentId;
}

// Adds `username` to the group at `targetGroupPath`, fetching its own
// admin token internally. Returns true when this call performed the join
// (caller MUST tear down), false when the user was already a member
// (caller MUST NOT remove it, since removal would then affect membership
// this call did not grant).
async function keycloakAdminAddUserToGroup(
  request,
  keycloakBaseUrl,
  realmName,
  targetGroupPath,
  username,
  adminUsername,
  adminPassword,
  opts = {},
) {
  const accessToken = await keycloakAdminToken(request, keycloakBaseUrl, adminUsername, adminPassword, opts);
  const headers = { Authorization: `Bearer ${accessToken}` };

  const userResp = await request.get(
    `${keycloakBaseUrl}/admin/realms/${realmName}/users?username=${encodeURIComponent(username)}&exact=true`,
    { headers },
  );
  if (!userResp.ok()) {
    throw new Error(`Keycloak user lookup failed: ${userResp.status()} ${await userResp.text()}`);
  }
  const users = await userResp.json();
  const user = users.find((u) => u.username === username);
  if (!user) {
    throw new Error(`Keycloak user "${username}" not found`);
  }

  const groupId = await keycloakResolveGroupId(request, keycloakBaseUrl, realmName, accessToken, targetGroupPath);

  const memberResp = await request.get(
    `${keycloakBaseUrl}/admin/realms/${realmName}/users/${user.id}/groups?max=500`,
    { headers },
  );
  if (!memberResp.ok()) {
    throw new Error(`Keycloak user-groups lookup failed: ${memberResp.status()} ${await memberResp.text()}`);
  }
  const currentGroups = await memberResp.json();
  if (currentGroups.some((g) => g.id === groupId || g.path === targetGroupPath)) {
    return false;
  }

  const joinResp = await request.put(
    `${keycloakBaseUrl}/admin/realms/${realmName}/users/${user.id}/groups/${groupId}`,
    { headers },
  );
  if (!joinResp.ok()) {
    throw new Error(
      `Keycloak join-group failed (user=${username}, group=${targetGroupPath}): ${joinResp.status()} ${await joinResp.text()}`,
    );
  }
  return true;
}

async function keycloakRemoveUserFromGroupViaRest(
  request,
  keycloakBaseUrl,
  realmName,
  adminUsername,
  adminPassword,
  groupPath,
  username,
  opts = {},
) {
  const accessToken = await keycloakAdminToken(request, keycloakBaseUrl, adminUsername, adminPassword, opts);
  const auth = { Authorization: `Bearer ${accessToken}` };

  const usersResp = await request.get(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/users?username=${encodeURIComponent(username)}&exact=true`,
    { headers: auth },
  );
  const users = await usersResp.json();
  const userId = users?.[0]?.id;
  if (!userId) return;

  const groupResp = await request.get(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/group-by-path/${groupPath.replace(/^\//, "")}`,
    { headers: auth },
  );
  if (!groupResp.ok()) return;
  const group = await groupResp.json();
  if (!group?.id) return;

  await request.delete(
    `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/users/${userId}/groups/${group.id}`,
    { headers: auth },
  );
}

module.exports = {
  OIDC_LOGIN_READY_FLAG,
  performKeycloakLoginForm,
  performKeycloakLogin,
  clickOidcLoginLink,
  performKeycloakLoginExpectingDenial,
  keycloakAdminToken,
  keycloakResolveGroupId,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
};
