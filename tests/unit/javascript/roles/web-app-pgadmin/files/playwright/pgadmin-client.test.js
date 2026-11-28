const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const calls = [];
const fakeExpect = (subject) => ({
  toBeVisible: async () => calls.push(["visible", subject.name]),
  toBeHidden: async () => calls.push(["hidden", subject.name]),
});

const { csrfHeaders, isMasterPasswordCheck, promptsForMasterPassword, requestUserList, watchMasterPasswordPrompt } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-pgadmin/files/playwright/pgadmin-client.js"),
  ["csrfHeaders", "isMasterPasswordCheck", "promptsForMasterPassword", "requestUserList", "watchMasterPasswordPrompt"],
  {
    "@playwright/test": { expect: fakeExpect },
    "./timeouts": { resolveTimeout: (ms) => ms },
  },
  { URL },
);

const BASE = "https://pgadmin.example.org";
const CSRF = { header: "X-pgA-CSRFToken", token: "token-under-test" };

function response(method, url, body) {
  return { request: () => ({ method: () => method }), url: () => url, json: async () => body };
}

function fakePage(checkBody) {
  const requests = [];
  const dialog = {
    name: "master-password-dialog",
    getByRole: (role, opts) => ({
      click: async () => calls.push(["click", role, opts.name]),
    }),
  };
  return {
    requests,
    waitForFunction: async () => true,
    evaluate: async () => CSRF,
    request: { get: async (url, opts) => requests.push({ url, opts }) },
    waitForResponse: async (predicate) => {
      const answer = response("POST", `${BASE}/browser/master_password`, checkBody);
      assert.equal(predicate(answer), true);
      return answer;
    },
    getByRole: (role) => {
      assert.equal(role, "dialog");
      return { filter: ({ hasText }) => (hasText.test("Set Master Password") ? dialog : null) };
    },
  };
}

test("the user list request carries the session CSRF token and a same-origin Referer", async () => {
  const page = fakePage();
  await requestUserList(page, BASE);
  assert.equal(page.requests.length, 1);
  const [{ url, opts }] = page.requests;
  assert.equal(url, `${BASE}/user_management/user/`);
  assert.equal(opts.headers[CSRF.header], CSRF.token);
  assert.equal(opts.headers.referer, `${BASE}/browser/`);
  assert.equal(opts.maxRedirects, 0);
  assert.equal(opts.failOnStatusCode, false);
});

test("the CSRF headers take the header name pgAdmin publishes", () => {
  assert.deepEqual({ ...csrfHeaders({ header: "X-Other", token: "t" }, BASE) }, { "X-Other": "t", referer: `${BASE}/browser/` });
});

test("only the POST to /browser/master_password is the check that raises the dialog", () => {
  assert.equal(isMasterPasswordCheck(response("POST", `${BASE}/browser/master_password`)), true);
  assert.equal(isMasterPasswordCheck(response("POST", `${BASE}/browser/master_password?x=1`)), true);
  assert.equal(isMasterPasswordCheck(response("GET", `${BASE}/browser/master_password`)), false);
  assert.equal(isMasterPasswordCheck(response("POST", `${BASE}/authenticate/login`)), false);
});

test("pgAdmin prompts only when it reports no key present", () => {
  assert.equal(promptsForMasterPassword({ data: { present: false, reset: false } }), true);
  assert.equal(promptsForMasterPassword({ data: { present: true } }), false);
  assert.equal(promptsForMasterPassword({ data: null }), false);
  assert.equal(promptsForMasterPassword(null), false);
});

test("a raised master password dialog is left with Cancel and must close", async () => {
  calls.length = 0;
  await watchMasterPasswordPrompt(fakePage({ data: { present: false } }))();
  assert.deepEqual(calls, [
    ["visible", "master-password-dialog"],
    ["click", "button", "Cancel"],
    ["hidden", "master-password-dialog"],
  ]);
});

test("a session that holds its key gets no dialog handling", async () => {
  calls.length = 0;
  await watchMasterPasswordPrompt(fakePage({ data: { present: true } }))();
  assert.deepEqual(calls, []);
});
