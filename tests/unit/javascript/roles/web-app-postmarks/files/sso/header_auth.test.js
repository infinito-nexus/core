const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const SOURCE = path.join(
  PROJECT_ROOT,
  "roles/web-app-postmarks/files/sso/header_auth.js",
);
const proxyHeaderSso = require(SOURCE).default;

const SSO_KEYS = ["PROXY_HEADER_SSO", "PROXY_HEADER_SSO_ADMIN_GROUP"];
const OWNER = "administrator";

function run({ env = {}, headers = {}, session = {} } = {}) {
  const saved = SSO_KEYS.map((key) => [key, process.env[key]]);
  SSO_KEYS.forEach((key) => delete process.env[key]);
  Object.assign(process.env, env);

  const lower = Object.fromEntries(
    Object.entries(headers).map(([name, value]) => [name.toLowerCase(), value]),
  );
  const req = { get: (name) => lower[name.toLowerCase()], session };
  let next = 0;
  try {
    proxyHeaderSso(req, {}, () => {
      next += 1;
    });
  } finally {
    saved.forEach(([key, value]) => {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    });
  }
  return { session: req.session, next };
}

test("the trusted username header opens the owner session", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true" },
    headers: { "X-Forwarded-Preferred-Username": OWNER },
  });
  assert.deepEqual(call.session, { loggedIn: true, ssoUser: OWNER });
  assert.equal(call.next, 1);
});

test("the preferred username wins over the plain forwarded user", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true" },
    headers: {
      "X-Forwarded-Preferred-Username": OWNER,
      "X-Forwarded-User": "someone-else",
    },
  });
  assert.equal(call.session.ssoUser, OWNER);
});

test("an email-only identity is still proof enough", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true" },
    headers: { "X-Forwarded-Email": "owner@example.test" },
  });
  assert.deepEqual(call.session, {
    loggedIn: true,
    ssoUser: "owner@example.test",
  });
});

test("a request without an identity is left untouched", () => {
  const anonymous = run({ env: { PROXY_HEADER_SSO: "true" } });
  assert.deepEqual(anonymous.session, {});
  assert.equal(anonymous.next, 1);

  const blank = run({
    env: { PROXY_HEADER_SSO: "true" },
    headers: { "X-Forwarded-User": "   " },
  });
  assert.deepEqual(blank.session, {});
  assert.equal(blank.next, 1);
});

test("headers the proxy does not overwrite cannot inject an identity", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true" },
    headers: {
      "X-Auth-Request-User": "attacker",
      "X-Auth-Request-Preferred-Username": "attacker",
      "Remote-User": "attacker",
    },
  });
  assert.deepEqual(call.session, {});
  assert.equal(call.next, 1);
});

test("the bridge stays off until PROXY_HEADER_SSO is switched on", () => {
  const headers = { "X-Forwarded-Preferred-Username": OWNER };
  ["", "false", "0", "off", "no"].forEach((value) => {
    const call = run({ env: { PROXY_HEADER_SSO: value }, headers });
    assert.deepEqual(call.session, {}, `PROXY_HEADER_SSO=${value}`);
    assert.equal(call.next, 1);
  });
  assert.deepEqual(run({ headers }).session, {});
});

test("every spelling of yes switches the bridge on", () => {
  const headers = { "X-Forwarded-Preferred-Username": OWNER };
  ["true", "TRUE", "1", "yes", "On"].forEach((value) => {
    const call = run({ env: { PROXY_HEADER_SSO: value }, headers });
    assert.equal(call.session.loggedIn, true, `PROXY_HEADER_SSO=${value}`);
  });
});

test("an identity outside the admin group gets no session", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true", PROXY_HEADER_SSO_ADMIN_GROUP: "admins" },
    headers: {
      "X-Forwarded-Preferred-Username": OWNER,
      "X-Forwarded-Groups": "users,guests",
    },
  });
  assert.deepEqual(call.session, {});
  assert.equal(call.next, 1);
});

test("a missing group header gets no session rather than a free pass", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true", PROXY_HEADER_SSO_ADMIN_GROUP: "admins" },
    headers: { "X-Forwarded-Preferred-Username": OWNER },
  });
  assert.deepEqual(call.session, {});
  assert.equal(call.next, 1);
});

test("a group name that merely starts with the admin group does not match", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true", PROXY_HEADER_SSO_ADMIN_GROUP: "admins" },
    headers: {
      "X-Forwarded-Preferred-Username": OWNER,
      "X-Forwarded-Groups": "admins-readonly",
    },
  });
  assert.deepEqual(call.session, {});
  assert.equal(call.next, 1);
});

test("the admin group is matched case-sensitively", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true", PROXY_HEADER_SSO_ADMIN_GROUP: "admins" },
    headers: {
      "X-Forwarded-Preferred-Username": OWNER,
      "X-Forwarded-Groups": "ADMINS",
    },
  });
  assert.deepEqual(call.session, {});
  assert.equal(call.next, 1);
});

test("group membership is read through Keycloak's leading slash", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true", PROXY_HEADER_SSO_ADMIN_GROUP: "admins" },
    headers: {
      "X-Forwarded-Preferred-Username": OWNER,
      "X-Forwarded-Groups": "users, /admins",
    },
  });
  assert.deepEqual(call.session, { loggedIn: true, ssoUser: OWNER });
});

test("a request reaching the bridge before the session store passes through", () => {
  const call = run({
    env: { PROXY_HEADER_SSO: "true" },
    headers: { "X-Forwarded-Preferred-Username": OWNER },
    session: null,
  });
  assert.equal(call.session, null);
  assert.equal(call.next, 1);
});
