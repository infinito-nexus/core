const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const source = path.resolve(__dirname, "../../../../../../roles/svc-ai-freellmapi/files/javascript/reconcile_admin.js");
const modulePromise = Promise.resolve(require(source));
const desired = { email: "admin@example.test", password: "new-password" };

function fixture(account) {
  let user = account;
  const calls = [];
  let sessions = ["existing-session"];
  return {
    calls,
    get user() { return user; },
    get sessions() { return sessions; },
    normalizeEmail: (email) => email.trim().toLowerCase(),
    userCount: () => user ? 1 : 0,
    accountEmail: () => user.email,
    createUser(email, password) {
      calls.push("create");
      user = { userId: 7, email, password };
    },
    verifyCredentials(email, password) {
      return user && user.email === email && user.password === password ? { userId: user.userId, email } : null;
    },
    resetUserPassword(password) {
      calls.push("reset");
      user.password = password;
      sessions = [];
      return { userId: user.userId, email: user.email };
    },
    updateEmail(id, password, email) {
      assert.equal(id, user.userId);
      assert.equal(password, user.password);
      calls.push("email");
      user.email = email;
      return true;
    },
  };
}

test("first deploy creates once; identical redeploy makes no account writes", async () => {
  const { reconcileAdmin } = await modulePromise;
  const auth = fixture(null);
  assert.equal(reconcileAdmin(desired, auth), true);
  assert.equal(reconcileAdmin(desired, auth), false);
  assert.deepEqual(auth.calls, ["create"]);
});

test("unchanged credentials preserve sessions and normalize inventory email", async () => {
  const { reconcileAdmin } = await modulePromise;
  const auth = fixture({ userId: 7, ...desired });
  assert.equal(reconcileAdmin({ ...desired, email: " ADMIN@example.test " }, auth), false);
  assert.deepEqual(auth.calls, []);
  assert.deepEqual(auth.sessions, ["existing-session"]);
});

test("password rotation invalidates sessions exactly once", async () => {
  const { reconcileAdmin } = await modulePromise;
  const auth = fixture({ userId: 7, email: desired.email, password: "old-password" });
  assert.equal(reconcileAdmin(desired, auth), true);
  assert.deepEqual(auth.sessions, []);
  assert.equal(reconcileAdmin(desired, auth), false);
  assert.deepEqual(auth.calls, ["reset"]);
});

test("email and password rotation retain the existing account identity", async () => {
  const { reconcileAdmin } = await modulePromise;
  const auth = fixture({ userId: 42, email: "old@example.test", password: "old-password" });
  assert.equal(reconcileAdmin(desired, auth), true);
  assert.equal(auth.user.userId, 42);
  assert.equal(reconcileAdmin(desired, auth), false);
  assert.deepEqual(auth.calls, ["reset", "email"]);
});

test("email-only rotation does not reset the password", async () => {
  const { reconcileAdmin } = await modulePromise;
  const auth = fixture({ userId: 7, ...desired, email: "old@example.test" });
  assert.equal(reconcileAdmin(desired, auth), true);
  assert.deepEqual(auth.calls, ["email"]);
});

test("multiple accounts and invalid input fail before any mutation", async () => {
  const { reconcileAdmin } = await modulePromise;
  const auth = fixture({ userId: 7, ...desired });
  auth.userCount = () => 2;
  assert.throws(() => reconcileAdmin(desired, auth));
  assert.throws(() => reconcileAdmin({ ...desired, password: "short" }, auth));
  assert.deepEqual(auth.calls, []);
});

test("failed email update fails loudly and can converge on the next deploy", async () => {
  const { reconcileAdmin } = await modulePromise;
  const auth = fixture({ userId: 7, email: "old@example.test", password: "old-password" });
  const updateEmail = auth.updateEmail;
  auth.updateEmail = () => false;
  assert.throws(() => reconcileAdmin(desired, auth));
  auth.updateEmail = updateEmail;
  assert.equal(reconcileAdmin(desired, auth), true);
  assert.equal(reconcileAdmin(desired, auth), false);
  assert.deepEqual(auth.calls, ["reset", "email"]);
});

const issuedKey = "freellmapi-0123456789abcdef0123456789abcdef";

function httpFixture(identity, apiKey = issuedKey) {
  const requests = [];
  return {
    requests,
    async request(url, options) {
      requests.push({ url, options });
      if (url.endsWith("/login")) return { status: 200, json: async () => ({ email: desired.email, token: "test-session" }) };
      if (url.endsWith("/me")) return { status: 200, json: async () => ({ email: identity }) };
      if (url.endsWith("/api-key")) return { status: 200, json: async () => ({ apiKey }) };
      return { status: 200 };
    },
  };
}

test("HTTP validation authenticates, reads the issued key and removes its session", async () => {
  const { validateLogin } = await modulePromise;
  const http = httpFixture(desired.email);
  const apiKey = await validateLogin({ admin: desired, base_url: "http://localhost:3001/", timeout_ms: 1000 }, http.request);
  assert.equal(apiKey, issuedKey);
  assert.deepEqual(http.requests.map((r) => new URL(r.url).pathname), [
    "/api/auth/login",
    "/api/auth/me",
    "/api/settings/api-key",
    "/api/auth/logout",
  ]);
  assert.deepEqual(JSON.parse(http.requests[0].options.body), desired);
  assert.equal(http.requests[1].options.headers.Authorization, "Bearer test-session");
  assert.equal(http.requests[2].options.headers.Authorization, "Bearer test-session");
});

test("missing issued key rejects the deploy and still logs out", async () => {
  const { validateLogin } = await modulePromise;
  const http = httpFixture(desired.email, "");
  await assert.rejects(validateLogin({ admin: desired, base_url: "http://localhost:3001", timeout_ms: 1000 }, http.request));
  assert.ok(http.requests.at(-1).url.endsWith("/logout"));
});

test("wrong HTTP identity rejects the deploy and still logs out", async () => {
  const { validateLogin } = await modulePromise;
  const http = httpFixture("wrong@example.test");
  await assert.rejects(validateLogin({ admin: desired, base_url: "http://localhost:3001", timeout_ms: 1000 }, http.request));
  assert.ok(http.requests.at(-1).url.endsWith("/logout"));
});

