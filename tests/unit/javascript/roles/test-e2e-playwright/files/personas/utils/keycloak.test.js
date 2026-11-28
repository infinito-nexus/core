const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const KEYCLOAK_JS = path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/keycloak.js");
const KEYCLOAK = "https://auth.example.test";
const REALM = "main";
const USER_ID = "user-1";
const GROUPS = {
  "baserow-admin": { id: "baserow-admin", name: "administrator", path: "/roles/web-app-baserow/administrator" },
  "baserow-user": { id: "baserow-user", name: "user", path: "/roles/web-app-baserow/user" },
  "prometheus-admin": { id: "prometheus-admin", name: "administrator", path: "/roles/web-app-prometheus/administrator" },
  "matomo-admin": { id: "matomo-admin", name: "administrator", path: "/roles/web-app-matomo/administrator" },
};

/**
 * Args:
 *   body: value the response's `json()` resolves to.
 *   status: HTTP status of the response.
 *
 * Returns:
 *   A Playwright APIResponse double.
 */
function response(body, status = 200) {
  return {
    ok: () => status >= 200 && status < 300,
    status: () => status,
    text: async () => JSON.stringify(body ?? ""),
    json: async () => body,
  };
}

/**
 * Args:
 *   members: ids of the groups the user holds before the call.
 *   cascade: whether a leave also drops every held group of the same name, as Keycloak 26.8.2 does for LDAP role groups.
 *   leaveStatus: HTTP status the leave answers with after its cascade.
 *   refusedJoins: ids of the groups whose join answers 403.
 *
 * Returns:
 *   A request double over a one-user realm that records every join in `joins`.
 */
function fakeKeycloak(members, { cascade, leaveStatus = 204, refusedJoins = [] }) {
  const held = new Set(members);
  const joins = [];
  const membershipPrefix = `${KEYCLOAK}/admin/realms/${REALM}/users/${USER_ID}/groups`;
  const idOf = (url) => url.slice(membershipPrefix.length + 1);
  return {
    held,
    joins,
    post: async () => response({ access_token: "probe-token" }),
    get: async (url) => {
      if (url.includes("/users?username=")) return response([{ id: USER_ID, username: "platformadmin" }]);
      if (url.includes("/group-by-path/")) {
        const wanted = `/${url.split("/group-by-path/")[1]}`;
        return response(Object.values(GROUPS).find((group) => group.path === wanted));
      }
      if (url.startsWith(`${membershipPrefix}?`)) return response([...held].map((id) => GROUPS[id]));
      return response(null, 404);
    },
    delete: async (url) => {
      const target = GROUPS[idOf(url)];
      for (const id of [...held]) {
        const collateral = cascade && GROUPS[id].name === target.name && id !== target.id;
        if (collateral || (id === target.id && leaveStatus < 300)) held.delete(id);
      }
      return response(leaveStatus < 300 ? null : { error: "multiple LDAP objects" }, leaveStatus);
    },
    put: async (url) => {
      const id = idOf(url);
      joins.push(id);
      if (refusedJoins.includes(id)) return response({ error: "forbidden" }, 403);
      held.add(id);
      return response(null, 204);
    },
  };
}

const { keycloakRemoveUserFromGroupViaRest } = loadInternals(KEYCLOAK_JS, ["keycloakRemoveUserFromGroupViaRest"], {}, {});

/**
 * Args:
 *   request: request double from `fakeKeycloak`.
 *   groupPath: path of the group the user leaves.
 *
 * Returns:
 *   The promise of the helper's leave.
 */
function leave(request, groupPath) {
  return keycloakRemoveUserFromGroupViaRest(request, KEYCLOAK, REALM, "admin", "probe-secret", groupPath, "platformadmin", {});
}

test("a leave that cascades to the same-named role groups of other apps joins those groups back", async () => {
  const keycloak = fakeKeycloak(["baserow-admin", "baserow-user", "prometheus-admin", "matomo-admin"], { cascade: true });
  await leave(keycloak, GROUPS["baserow-admin"].path);
  assert.deepEqual([...keycloak.held].sort(), ["baserow-user", "matomo-admin", "prometheus-admin"]);
  assert.deepEqual(keycloak.joins.sort(), ["matomo-admin", "prometheus-admin"]);
});

test("a leave that drops only its own group joins nothing back", async () => {
  const keycloak = fakeKeycloak(["baserow-admin", "baserow-user", "prometheus-admin"], { cascade: false });
  await leave(keycloak, GROUPS["baserow-admin"].path);
  assert.deepEqual([...keycloak.held].sort(), ["baserow-user", "prometheus-admin"]);
  assert.deepEqual(keycloak.joins, []);
});

test("the left group itself is never joined back", async () => {
  const keycloak = fakeKeycloak(["baserow-admin", "prometheus-admin"], { cascade: true });
  await leave(keycloak, GROUPS["baserow-admin"].path);
  assert.equal(keycloak.held.has("baserow-admin"), false);
  assert.equal(keycloak.joins.includes("baserow-admin"), false);
});

test("a 400 leave after a partial cascade still joins the collateral back and then rejects", async () => {
  const keycloak = fakeKeycloak(["baserow-admin", "prometheus-admin", "matomo-admin"], { cascade: true, leaveStatus: 400 });
  await assert.rejects(leave(keycloak, GROUPS["baserow-admin"].path), /leave \/roles\/web-app-baserow\/administrator answered 400/);
  assert.deepEqual(keycloak.joins.sort(), ["matomo-admin", "prometheus-admin"]);
  assert.deepEqual([...keycloak.held].sort(), ["baserow-admin", "matomo-admin", "prometheus-admin"]);
});

test("a rejoin refused mid-loop still attempts every other rejoin and names only the refused group", async () => {
  const keycloak = fakeKeycloak(["baserow-admin", "prometheus-admin", "matomo-admin"], {
    cascade: true,
    refusedJoins: ["prometheus-admin"],
  });
  const rejection = await leave(keycloak, GROUPS["baserow-admin"].path).then(
    () => assert.fail("a refused rejoin must reject the leave"),
    (error) => String(error),
  );
  assert.deepEqual(keycloak.joins.sort(), ["matomo-admin", "prometheus-admin"]);
  assert.equal(keycloak.held.has("matomo-admin"), true);
  assert.match(rejection, /rejoin \/roles\/web-app-prometheus\/administrator answered 403/);
  assert.doesNotMatch(rejection, /web-app-matomo/);
});
