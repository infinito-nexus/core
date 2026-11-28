const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "http://jenkins.example.org";
const CRUMB = { crumbRequestField: "Jenkins-Crumb", crumb: "crumb-of-the-session" };
const identity = (value) => value;
const registers = new Proxy(() => undefined, { get: () => () => undefined });

const { queueBuild, deleteJob } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-jenkins/files/playwright/test-rbac-roles.js"),
  ["queueBuild", "deleteJob"],
  {
    "@playwright/test": { test: registers, expect: () => undefined },
    "./timeouts": { resolveTimeout: identity },
    "./personas": { decodeDotenvQuotedValue: identity, normalizeBaseUrl: identity, gotoOnion: async () => undefined },
    "./jenkins-login": { baseUrl: BASE },
  },
  {},
);

/**
 * Args:
 *   method: the HTTP method of the request.
 *   url: the absolute URL of the request.
 *   headers: the request headers.
 *
 * Returns:
 *   The status Jenkins answers on a job's build endpoint: 405 for anything but POST, 403 for a POST without the
 *   session crumb, 201 for a queued build.
 */
function buildEndpoint(method, url, headers) {
  if (!new URL(url).pathname.endsWith("/build")) return 404;
  if (method !== "POST") return 405;
  return headers[CRUMB.crumbRequestField] === CRUMB.crumb ? 201 : 403;
}

/**
 * Args:
 *   crumb: the record /crumbIssuer/api/json answers, or null when the controller issues no crumb.
 *   answer: maps method, URL and headers of every other request to the status Jenkins answers.
 *
 * Returns:
 *   A page stand-in whose `request` answers like Jenkins, and the list `calls` of every request it received.
 */
function jenkinsPage(crumb, answer) {
  const calls = [];
  const respond = (status, body) => ({
    ok: () => status >= 200 && status < 300,
    status: () => status,
    json: async () => body,
  });
  const request = {
    get: async (url, options) => {
      calls.push({ method: "GET", url, options });
      if (url === `${BASE}/crumbIssuer/api/json`) return crumb ? respond(200, crumb) : respond(404, {});
      return respond(answer("GET", url, (options && options.headers) || {}), {});
    },
    post: async (url, options) => {
      calls.push({ method: "POST", url, options });
      return respond(answer("POST", url, (options && options.headers) || {}), {});
    },
  };
  return { page: { request }, calls };
}

test("queueBuild POSTs to the job's build endpoint with the session crumb and returns the 201 of a queued build", async () => {
  const { page, calls } = jenkinsPage(CRUMB, buildEndpoint);

  assert.equal(await queueBuild(page, "infinito rbac"), 201);

  const builds = calls.filter((call) => new URL(call.url).pathname.endsWith("/build"));
  assert.deepEqual(
    builds.map((call) => `${call.method} ${call.url}`),
    [`POST ${BASE}/job/infinito%20rbac/build?delay=0sec`],
  );
  assert.equal(builds[0].options.maxRedirects, 0);
});

test("queueBuild returns the refusal Jenkins answers instead of a queued build when the session holds no crumb", async () => {
  const { page } = jenkinsPage(null, buildEndpoint);

  assert.equal(await queueBuild(page, "infinito-rbac"), 403);
});

test("deleteJob sends the session crumb and tolerates a job that is already gone", async () => {
  const { page, calls } = jenkinsPage(CRUMB, () => 404);

  await deleteJob(page, "infinito-rbac");

  const removal = calls.find((call) => call.url === `${BASE}/job/infinito-rbac/doDelete`);
  assert.equal(removal.method, "POST");
  assert.equal(removal.options.headers[CRUMB.crumbRequestField], CRUMB.crumb);
});

test("deleteJob fails on a removal Jenkins refuses", async () => {
  const { page } = jenkinsPage(CRUMB, () => 500);

  await assert.rejects(deleteJob(page, "infinito-rbac"), /Deleting job infinito-rbac answered 500/);
});
