const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-gitea/files/playwright/test-workspaces.js");
const TEST_NAME = "gitea workspaces: only the store writes main";
const BASE = "https://gitea.example.org";
const ONION_BASE = `http://tea.git.${"a".repeat(56)}.onion`;
const TOR_PROXY = "socks5://tor.invalid:9050";
const TOR_PROXY_REMOTE_DNS = "socks5h://tor.invalid:9050";
const STORE = "workspace-store";
const HEAD = "0123456789abcdef0123456789abcdef01234567";
const MEMBERSHIP_REMOVAL = "await asAdmin().del(`/teams/${teamId}/members/${member.username}`)";
const TOR_PROXY_SETTINGS = ", ...torProxySettings(remote)]";
const identity = (value) => value;

Object.assign(process.env, {
  GITEA_WORKSPACES_ORGANIZATION: "workspaces",
  GITEA_WORKSPACES_STORE_USERNAME: STORE,
  GITEA_WORKSPACES_STORE_SCOPES: "write:organization,write:repository,read:user",
  GITEA_SSH_PORT: "2201",
  CANONICAL_DOMAIN: "example.org",
  ADMIN_USERNAME: "administrator",
  ADMIN_PASSWORD: "unit-test-only",
});

/**
 * Args:
 *   actual: the value under test.
 *   message: the message the spec attaches to it.
 *
 * Returns:
 *   The matchers the spec calls; each throws an Error carrying `message`, as `@playwright/test` does.
 */
function expect(actual, message) {
  const check = (passed, detail) => {
    if (!passed) throw new Error(`${message ?? "expectation"}: ${detail}`);
  };
  return {
    toBe: (expected) => check(Object.is(actual, expected), `expected ${expected}, got ${actual}`),
    toEqual: (expected) =>
      check(JSON.stringify(actual) === JSON.stringify(expected), `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`),
    toContain: (expected) => check(actual.includes(expected), `expected an entry ${expected}`),
    toThrow: () => {
      let threw = false;
      try {
        actual();
      } catch {
        threw = true;
      }
      check(threw, "expected a throw");
    },
  };
}

/**
 * Args:
 *   calls: collects { args, env } of every git call.
 *
 * Returns:
 *   A `node:child_process` whose `execFileSync` stands in for git, ssh and ssh-keygen: ssh-keygen writes a public
 *   key, a clone creates its directory, rev-parse answers HEAD, and a push over HTTPS, the member's path, is refused.
 */
function fakeChildProcess(calls) {
  return {
    execFileSync(command, args, options) {
      if (command === "git") {
        calls.push({ args, env: options?.env });
      }
      if (command === "ssh-keygen") {
        fs.writeFileSync(`${args[args.indexOf("-f") + 1]}.pub`, "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIunit unit\n");
      } else if (command === "git" && args[0] === "clone") {
        fs.mkdirSync(args[args.length - 1], { recursive: true });
      } else if (command === "git" && args[0] === "rev-parse") {
        return Buffer.from(`${HEAD}\n`);
      } else if (command === "git" && args[0] === "push" && options?.env?.GIT_CONFIG_KEY_0 === "http.extraHeader") {
        throw new Error("User permission denied for writing.");
      }
      return Buffer.from("");
    },
  };
}

/**
 * Returns:
 *   `request`, a request fixture whose `fetch` answers the routes of the spec like Gitea 28.2.0; `users` and `teams`,
 *   the accounts and team memberships it holds. Like Gitea, a team member is an organization member until its last
 *   team membership or that team is gone, and deleting a user who is still an organization member answers 422
 *   (services/user/user.go DeleteUser, ErrUserHasOrgs).
 */
function fakeGitea() {
  const users = new Set([STORE]);
  const teams = new Map();
  let nextId = 1;
  const inOrganization = (username) => [...teams.values()].some((members) => members.has(username));
  const routes = [
    ["POST", /^\/users\/[^/]+\/tokens$/, () => [201, { id: nextId++, sha1: `sha-${nextId}` }]],
    ["POST", /^\/orgs\/[^/]+\/repos$/, () => [201, {}]],
    ["POST", /^\/repos\/[^/]+\/[^/]+\/(branch_protections|keys)$/, () => [201, {}]],
    [
      "POST",
      /^\/orgs\/[^/]+\/teams$/,
      () => {
        const id = nextId++;
        teams.set(id, new Set());
        return [201, { id }];
      },
    ],
    ["PUT", /^\/teams\/\d+\/repos\/[^/]+\/[^/]+$/, () => [204, {}]],
    [
      "POST",
      /^\/admin\/users$/,
      (_match, data) => {
        users.add(data.username);
        return [201, {}];
      },
    ],
    [
      "PUT",
      /^\/teams\/(\d+)\/members\/([^/]+)$/,
      (match) => {
        teams.get(Number(match[1])).add(match[2]);
        return [204, {}];
      },
    ],
    [
      "DELETE",
      /^\/teams\/(\d+)\/members\/([^/]+)$/,
      (match) => {
        const members = teams.get(Number(match[1]));
        if (!members || !users.has(match[2])) return [404, {}];
        members.delete(match[2]);
        return [204, {}];
      },
    ],
    ["DELETE", /^\/teams\/(\d+)$/, (match) => (teams.delete(Number(match[1])) ? [204, {}] : [404, {}])],
    [
      "DELETE",
      /^\/admin\/users\/([^/]+)$/,
      (match) => {
        if (!users.has(match[1])) return [404, {}];
        if (inOrganization(match[1])) return [422, { message: "user still has membership of organizations" }];
        users.delete(match[1]);
        return [204, {}];
      },
    ],
    ["DELETE", /^\/repos\/[^/]+\/[^/]+\/branches\/main$/, () => [403, {}]],
    ["DELETE", /^\/repos\/[^/]+\/[^/]+$/, () => [204, {}]],
    ["DELETE", /^\/users\/[^/]+\/tokens\/\d+$/, () => [204, {}]],
    ["PATCH", /^\/repos\/[^/]+\/[^/]+\/(branches|branch_protections)\/main$/, () => [403, {}]],
    ["GET", /^\/repos\/[^/]+\/[^/]+\/branches\/main$/, () => [200, { commit: { id: HEAD } }]],
    [
      "GET",
      /^\/repos\/[^/]+\/[^/]+\/branch_protections\/main$/,
      () => [200, { enable_push: true, enable_push_whitelist: true, push_whitelist_deploy_keys: true, enable_force_push: false }],
    ],
  ];
  const request = {
    fetch: async (url, options) => {
      const route = new URL(url).pathname.replace(/^\/api\/v1/, "");
      const entry = routes.find(([method, pattern]) => method === options.method && pattern.test(route));
      assert.ok(entry, `the fake Gitea serves no ${options.method} ${route}`);
      const [status, body] = entry[2](route.match(entry[1]), options.data);
      return { status: () => status, json: async () => body };
    },
  };
  return { request, users, teams };
}

/**
 * Args:
 *   file: the spec file to load.
 *   base: the Gitea base URL the runner hands the spec.
 *   calls: collects { args, env } of every git call the test makes.
 *
 * Returns:
 *   The body of its test TEST_NAME.
 */
function testBody(file, base, calls) {
  const bodies = new Map();
  const registrar = Object.assign((name, body) => bodies.set(name, body), {
    describe: (_name, define) => define(),
    skip: () => undefined,
    setTimeout: () => undefined,
  });
  const globals = { Buffer, console };
  loadInternals(
    file,
    [],
    {
      "node:child_process": fakeChildProcess(calls),
      "node:crypto": require("node:crypto"),
      "node:fs": fs,
      "node:os": os,
      "node:path": path,
      "@playwright/test": { test: registrar, expect },
      "./personas": {
        decodeDotenvQuotedValue: identity,
        isOnionUrl: (url) => new URL(url).hostname.endsWith(".onion"),
        normalizeBaseUrl: identity,
        requireDotenvValue: identity,
      },
      "./timeouts": { resolveTimeout: identity },
    },
    globals,
  );
  globals.module.exports.register({ env: { gitEaBaseUrl: base } });
  assert.ok(bodies.has(TEST_NAME), `the spec registers ${TEST_NAME}`);
  return bodies.get(TEST_NAME);
}

/**
 * Args:
 *   old: text the spec holds exactly once.
 *   replacement: its replacement.
 *
 * Returns:
 *   The path of a planted copy of the spec, for a negative control.
 */
function planted(old, replacement) {
  const source = fs.readFileSync(SPEC, "utf8");
  assert.equal(source.split(old).length, 2, `the plant ${old} must occur exactly once`);
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "gitea-workspaces-plant-"));
  const file = path.join(directory, "test-workspaces.js");
  fs.writeFileSync(file, source.replace(old, replacement));
  return file;
}

/**
 * Args:
 *   file: the spec file to run.
 *   base: the Gitea base URL the runner hands the spec.
 *
 * Returns:
 *   The http.proxy setting of each HTTPS git call TEST_NAME makes while the runner provides TOR_PROXY, undefined
 *   where a call has none.
 */
async function httpsGitProxies(file, base) {
  const calls = [];
  process.env.PLAYWRIGHT_PROXY = TOR_PROXY;
  try {
    await testBody(file, base, calls)({ request: fakeGitea().request });
  } finally {
    delete process.env.PLAYWRIGHT_PROXY;
  }
  const https = calls.filter(({ env }) => env?.GIT_CONFIG_KEY_0 === "http.extraHeader");
  assert.ok(https.length > 0, "the test must talk HTTPS git to Gitea");
  return https.map(({ env }) => {
    const settings = Array.from({ length: Number(env.GIT_CONFIG_COUNT) }, (_, index) => [
      env[`GIT_CONFIG_KEY_${index}`],
      env[`GIT_CONFIG_VALUE_${index}`],
    ]);
    return Object.fromEntries(settings)["http.proxy"];
  });
}

test("only the store writes main: the cleanup ends the team membership before it deletes the member", async () => {
  const gitea = fakeGitea();

  await testBody(SPEC, BASE, [])({ request: gitea.request });

  assert.deepEqual([...gitea.users], [STORE], "the probe member must be deleted");
  assert.equal(gitea.teams.size, 0, "the probe team must be deleted");
});

test("negative control: deleting the member while it still sits in the team answers 422", async () => {
  const file = planted(MEMBERSHIP_REMOVAL, "({ status: () => 204 })");
  try {
    await assert.rejects(
      testBody(file, BASE, [])({ request: fakeGitea().request }),
      /cleanup failed: user playwright-member-\S+ must be removed or already gone, got 422/,
    );
  } finally {
    fs.rmSync(path.dirname(file), { recursive: true, force: true });
  }
});

test("HTTPS git to an onion Gitea goes through the runner's Tor proxy, which resolves the .onion name", async () => {
  const proxies = await httpsGitProxies(SPEC, ONION_BASE);

  assert.deepEqual(proxies, proxies.map(() => TOR_PROXY_REMOTE_DNS));
});

test("HTTPS git to a clearnet Gitea stays off the Tor proxy", async () => {
  const proxies = await httpsGitProxies(SPEC, BASE);

  assert.deepEqual(proxies, proxies.map(() => undefined));
});

test("negative control: HTTPS git without the Tor proxy setting reaches an onion Gitea through no proxy", async () => {
  const file = planted(TOR_PROXY_SETTINGS, "]");
  try {
    const proxies = await httpsGitProxies(file, ONION_BASE);

    assert.notDeepEqual(proxies, proxies.map(() => TOR_PROXY_REMOTE_DNS));
  } finally {
    fs.rmSync(path.dirname(file), { recursive: true, force: true });
  }
});
