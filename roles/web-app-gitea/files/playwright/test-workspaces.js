const { execFileSync } = require("node:child_process");
const { randomBytes, randomInt, randomUUID } = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const {
  WORKSPACE_RESULT_LINE,
  WORKSPACE_RUN_MS,
  WORKSPACE_TEMPLATE,
  runWorkspaceTask,
  vaultedBreakglassSession,
} = require("./personas/utils/workspace");
const { resolveTimeout } = require("./timeouts");

const SEMAPHORE_POLL_MS = 10_000;

const enabled = process.env.GITEA_WORKSPACES_ENABLED === "true";
const workspacesApply = process.env.SEMAPHORE_WORKSPACES_ENABLED === "true";
const organization = decodeDotenvQuotedValue(process.env.GITEA_WORKSPACES_ORGANIZATION);
const store = decodeDotenvQuotedValue(process.env.GITEA_WORKSPACES_STORE_USERNAME);
const scopes = decodeDotenvQuotedValue(process.env.GITEA_WORKSPACES_STORE_SCOPES);
const tokenPrefix = decodeDotenvQuotedValue(process.env.GITEA_WORKSPACES_STORE_TOKEN_PREFIX);
const sshPort = decodeDotenvQuotedValue(process.env.GITEA_SSH_PORT);
const domain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const admin = {
  username: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  password: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
};

function basic(username, password) {
  return `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`;
}

function headers(authorization, sudo) {
  const out = { Authorization: authorization, "Content-Type": "application/json" };
  if (sudo) {
    out.Sudo = sudo;
  }
  return out;
}

function client(request, base, authorization, sudo) {
  const api = `${base.replace(/\/$/, "")}/api/v1`;
  const call = (method, route, data) =>
    request.fetch(`${api}${route}`, {
      method,
      headers: headers(authorization, sudo),
      data,
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
  return {
    get: (route) => call("GET", route),
    post: (route, data) => call("POST", route, data),
    put: (route, data) => call("PUT", route, data),
    del: (route) => call("DELETE", route),
    patch: (route, data) => call("PATCH", route, data),
  };
}

function suffix() {
  return `${Date.now().toString(36)}${randomInt(36 ** 4).toString(36).padStart(4, "0")}`;
}

function probePassword() {
  return `Pw-${randomBytes(16).toString("hex")}`;
}

async function mintStoreToken(asAdmin) {
  const response = await asAdmin(store).post(`/users/${store}/tokens`, {
    name: `playwright-${suffix()}`,
    scopes: scopes.split(","),
  });
  expect(response.status(), "the administrator mints a probe token for the store").toBe(201);
  const body = await response.json();
  return { id: body.id, value: body.sha1 };
}

function requireTools(names) {
  for (const name of names) {
    try {
      execFileSync("sh", ["-c", `command -v ${name}`], { stdio: "ignore" });
    } catch {
      throw new Error(`${name} must be installed in the Playwright runner for the deploy key test`);
    }
  }
}

function sshKey(directory, name) {
  const file = path.join(directory, name);
  execFileSync("ssh-keygen", ["-q", "-t", "ed25519", "-N", "", "-C", name, "-f", file]);
  return { file, public: fs.readFileSync(`${file}.pub`, "utf8").trim() };
}

function git(args, cwd, key) {
  return execFileSync("git", args, {
    cwd,
    env: {
      ...process.env,
      GIT_SSH_COMMAND: `ssh -i ${key} -p ${sshPort} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null`,
      GIT_TERMINAL_PROMPT: "0",
    },
    stdio: "pipe",
  });
}

function httpsGit(args, cwd, authorization) {
  return execFileSync("git", args, {
    cwd,
    env: {
      ...process.env,
      GIT_CONFIG_COUNT: "1",
      GIT_CONFIG_KEY_0: "http.extraHeader",
      GIT_CONFIG_VALUE_0: `Authorization: ${authorization}`,
      GIT_SSL_NO_VERIFY: "true",
      GIT_TERMINAL_PROMPT: "0",
    },
    stdio: "pipe",
  });
}

function commit(directory, file, message) {
  fs.writeFileSync(path.join(directory, file), `${message}\n`);
  execFileSync("git", ["add", file], { cwd: directory, stdio: "pipe" });
  execFileSync(
    "git",
    ["-c", "user.name=playwright", "-c", "user.email=playwright@example.invalid", "commit", "-qm", message],
    { cwd: directory, stdio: "pipe" },
  );
  return execFileSync("git", ["rev-parse", "HEAD"], { cwd: directory, stdio: "pipe" }).toString().trim();
}

async function withCleanup(body) {
  const steps = [];
  let outcome;
  try {
    outcome = { value: await body((step) => steps.push(step)) };
  } catch (error) {
    outcome = { error };
  }
  const problems = [];
  for (const step of steps.reverse()) {
    try {
      await step();
    } catch (error) {
      problems.push(error.message);
    }
  }
  if (outcome.error) {
    if (problems.length > 0) {
      console.warn(`cleanup after the failure also failed: ${problems.join("; ")}`);
    }
    throw outcome.error;
  }
  if (problems.length > 0) {
    throw new Error(`cleanup failed: ${problems.join("; ")}`);
  }
  return outcome.value;
}

function expectGone(response, what) {
  expect([200, 204, 404], `${what} must be removed or already gone, got ${response.status()}`).toContain(
    response.status(),
  );
}

function semaphoreEnv() {
  return {
    baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.SEMAPHORE_BASE_URL, "SEMAPHORE_BASE_URL")),
    breakglassPath: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SEMAPHORE_PATH, "OPENBAO_PLAYWRIGHT_SEMAPHORE_PATH"),
    openbao: {
      baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL")),
      roleId: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_ROLE_ID, "OPENBAO_PLAYWRIGHT_ROLE_ID"),
      secretId: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SECRET_ID, "OPENBAO_PLAYWRIGHT_SECRET_ID"),
      mount: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_MOUNT, "OPENBAO_PLAYWRIGHT_MOUNT"),
    },
    project: requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_PROJECT, "SEMAPHORE_WORKSPACES_PROJECT"),
  };
}

async function semaphore(request) {
  const env = semaphoreEnv();
  return vaultedBreakglassSession(request, env.openbao, env, env.project, WORKSPACE_TEMPLATE);
}

function workspaceResult(run, action) {
  expect(run.status, `workspace ${action} task ${run.id} must succeed; its output is in Semaphore`).toBe("success");
  const line = [...run.lines].reverse().find((candidate) => WORKSPACE_RESULT_LINE.test(candidate.trim()));
  expect(line, `workspace ${action} task ${run.id} must print its result as the last JSON line`).toBeTruthy();
  return JSON.parse(line.trim());
}

function keyBody(key) {
  return key.trim().split(/\s+/).slice(0, 2).join(" ");
}

exports.register = function (shared) {
  test.describe("gitea workspaces", () => {
    test.skip(!enabled, "services.gitea.workspaces.enabled is off for this deployment");

    const base = () => shared.env.gitEaBaseUrl;
    const adminAuth = basic(admin.username, admin.password);

    test("gitea workspaces: the deploy creates organization and store account once", async ({ request }) => {
      const asAdmin = client(request, base(), adminAuth);
      const org = await asAdmin.get(`/orgs/${organization}`);
      expect(org.status(), `organization ${organization} must exist`).toBe(200);
      expect((await org.json()).visibility).toBe("private");
      const user = await asAdmin.get(`/users/${store}`);
      expect(user.status(), `account ${store} must exist`).toBe(200);
      expect((await user.json()).is_admin, `${store} must not be a site admin`).toBe(false);
      const teams = await (await asAdmin.get(`/orgs/${organization}/teams?limit=50`)).json();
      const owners = teams.find((team) => team.name === "Owners");
      expect(owners, "the organization keeps its Owners team").toBeTruthy();
      const members = await (await asAdmin.get(`/teams/${owners.id}/members`)).json();
      expect(members.map((member) => member.login)).toEqual([store]);
      const created = await client(request, base(), adminAuth, store).post(`/user/repos`, {
        name: `playwright-own-${suffix()}`,
        private: true,
      });
      expect(created.status(), `${store} must not create a repository of its own`).toBeGreaterThanOrEqual(400);
    });

    test("gitea workspaces: the store account belongs to the workspace organization only", async ({ request }) => {
      const asAdmin = client(request, base(), adminAuth);
      const orgs = await (await asAdmin.get(`/users/${store}/orgs?limit=50`)).json();
      expect(orgs.map((org) => org.username)).toEqual([organization]);
      const repos = await (await asAdmin.get(`/users/${store}/repos?limit=50`)).json();
      expect(repos.filter((repo) => repo.owner.login === store)).toEqual([]);
    });

    test("gitea workspaces: the store token carries exactly three scopes", async ({ request }) => {
      const asStore = client(request, base(), adminAuth, store);
      const tokens = await (await asStore.get(`/users/${store}/tokens?limit=50`)).json();
      const rotated = tokens.filter((token) => token.name.startsWith(tokenPrefix));
      expect(rotated.length, "rotate store credentials must have minted a store token").toBeGreaterThan(0);
      for (const token of rotated) {
        expect([...token.scopes].sort(), `scopes of ${token.name}`).toEqual(scopes.split(",").sort());
      }
    });

    test("gitea workspaces: the store token reaches only the workspace organization", async ({ request }) => {
      const asAdmin = (sudo) => client(request, base(), adminAuth, sudo);
      const token = await mintStoreToken(asAdmin);
      const asStore = client(request, base(), `token ${token.value}`);
      const repository = `ws-playwright-${suffix()}`;
      const other = `playwright-other-${suffix()}`;
      try {
        expect((await asStore.post(`/orgs/${organization}/repos`, { name: repository, private: true })).status()).toBe(201);
        expect(
          (await asStore.post(`/orgs/${organization}/teams`, {
            name: repository,
            permission: "read",
            units_map: { "repo.code": "read" },
            includes_all_repositories: false,
            can_create_org_repo: false,
          })).status(),
        ).toBe(201);
        expect((await asAdmin().post(`/orgs`, { username: other, visibility: "private" })).status()).toBe(201);
        expect((await asAdmin().post(`/orgs/${other}/repos`, { name: "secret", private: true })).status()).toBe(201);
        expect((await asStore.post(`/orgs/${other}/repos`, { name: "intruder", private: true })).status()).toBeGreaterThanOrEqual(400);
        expect((await asStore.post(`/user/repos`, { name: "own", private: true })).status()).toBeGreaterThanOrEqual(400);
        expect((await asStore.get(`/repos/${other}/secret`)).status()).toBe(404);
        expect((await asStore.get(`/admin/users`)).status()).toBe(403);
      } finally {
        await asAdmin().del(`/repos/${organization}/${repository}`);
        const teams = await (await asAdmin().get(`/orgs/${organization}/teams?limit=50`)).json();
        for (const team of teams.filter((entry) => entry.name === repository)) {
          await asAdmin().del(`/teams/${team.id}`);
        }
        await asAdmin().del(`/repos/${other}/secret`);
        await asAdmin().del(`/orgs/${other}`);
        await asAdmin(store).del(`/users/${store}/tokens/${token.id}`);
      }
    });

    test("gitea workspaces: write and read deploy keys do what they say", async ({ request }) => {
      requireTools(["git", "ssh", "ssh-keygen"]);
      const asAdmin = (sudo) => client(request, base(), adminAuth, sudo);
      const token = await mintStoreToken(asAdmin);
      const asStore = client(request, base(), `token ${token.value}`);
      const repository = `ws-playwright-${suffix()}`;
      const directory = fs.mkdtempSync(path.join(os.tmpdir(), "gitea-deploy-keys-"));
      const remote = `ssh://git@${domain}:${sshPort}/${organization}/${repository}.git`;
      try {
        expect((await asStore.post(`/orgs/${organization}/repos`, { name: repository, private: true, auto_init: true })).status()).toBe(201);
        const writer = sshKey(directory, "store");
        const reader = sshKey(directory, "semaphore");
        expect((await asStore.post(`/repos/${organization}/${repository}/keys`, { title: "store", key: writer.public, read_only: false })).status()).toBe(201);
        expect((await asStore.post(`/repos/${organization}/${repository}/keys`, { title: "semaphore", key: reader.public, read_only: true })).status()).toBe(201);
        const pushed = path.join(directory, "pushed");
        git(["clone", remote, pushed], directory, writer.file);
        fs.writeFileSync(path.join(pushed, "inventory.yml"), "all: {}\n");
        git(["add", "inventory.yml"], pushed, writer.file);
        git(["-c", "user.name=store", "-c", "user.email=store@example.invalid", "commit", "-qm", "add inventory"], pushed, writer.file);
        git(["push", "-q", "origin", "HEAD"], pushed, writer.file);
        const cloned = path.join(directory, "cloned");
        git(["clone", remote, cloned], directory, reader.file);
        expect(fs.existsSync(path.join(cloned, "inventory.yml")), "the read key clones what the write key pushed").toBe(true);
        fs.writeFileSync(path.join(cloned, "intrusion.yml"), "all: {}\n");
        git(["add", "intrusion.yml"], cloned, reader.file);
        git(["-c", "user.name=semaphore", "-c", "user.email=semaphore@example.invalid", "commit", "-qm", "intrusion"], cloned, reader.file);
        expect(() => git(["push", "-q", "origin", "HEAD"], cloned, reader.file), "the read-only key must be refused on push").toThrow();
      } finally {
        await asAdmin().del(`/repos/${organization}/${repository}`);
        await asAdmin(store).del(`/users/${store}/tokens/${token.id}`);
        fs.rmSync(directory, { recursive: true, force: true });
      }
    });

    test("gitea workspaces: members read and billing sees nothing", async ({ request }) => {
      const asAdmin = (sudo) => client(request, base(), adminAuth, sudo);
      const token = await mintStoreToken(asAdmin);
      const asStore = client(request, base(), `token ${token.value}`);
      const repository = `ws-playwright-${suffix()}`;
      const people = ["viewer", "owner", "billing"].map((role) => ({
        role,
        username: `playwright-${role}-${suffix()}`,
        password: probePassword(),
      }));
      const repoUrl = `${base().replace(/\/$/, "")}/${organization}/${repository}.git`;
      try {
        expect((await asStore.post(`/orgs/${organization}/repos`, { name: repository, private: true, auto_init: true })).status()).toBe(201);
        const team = await asStore.post(`/orgs/${organization}/teams`, {
          name: repository,
          permission: "read",
          units_map: { "repo.code": "read" },
          includes_all_repositories: false,
          can_create_org_repo: false,
        });
        expect(team.status()).toBe(201);
        const teamId = (await team.json()).id;
        expect((await asStore.put(`/teams/${teamId}/repos/${organization}/${repository}`)).status()).toBe(204);
        for (const person of people) {
          const created = await asAdmin().post(`/admin/users`, {
            username: person.username,
            email: `${person.username}@example.invalid`,
            password: person.password,
            must_change_password: false,
          });
          expect(created.status(), `create ${person.role}`).toBe(201);
          if (person.role !== "billing") {
            expect((await asStore.put(`/teams/${teamId}/members/${person.username}`)).status()).toBe(204);
          }
        }
        for (const person of people) {
          const auth = basic(person.username, person.password);
          const fetchRefs = (service) =>
            request.get(`${repoUrl}/info/refs?service=${service}`, {
              headers: { Authorization: auth },
              failOnStatusCode: false,
              timeout: resolveTimeout(30_000),
            });
          const api = await client(request, base(), auth).get(`/repos/${organization}/${repository}`);
          if (person.role === "billing") {
            expect(api.status(), "a billing-only user must not see the repository").toBe(404);
            continue;
          }
          expect((await fetchRefs("git-upload-pack")).status(), `${person.role} clones over HTTPS`).toBe(200);
          expect((await fetchRefs("git-receive-pack")).status(), `${person.role} is refused on push`).toBeGreaterThanOrEqual(400);
        }
      } finally {
        await asAdmin().del(`/repos/${organization}/${repository}`);
        const teams = await (await asAdmin().get(`/orgs/${organization}/teams?limit=50`)).json();
        for (const entry of teams.filter((candidate) => candidate.name === repository)) {
          await asAdmin().del(`/teams/${entry.id}`);
        }
        for (const person of people) {
          await asAdmin().del(`/admin/users/${person.username}`);
        }
        await asAdmin(store).del(`/users/${store}/tokens/${token.id}`);
      }
    });

    test("gitea workspaces: the read key is core's and the store holds its public half only", async ({ request }) => {
      test.skip(!workspacesApply, "no Semaphore Workspaces project with OpenBao runs beside Gitea, so no workspace apply can start");
      test.setTimeout(resolveTimeout(3 * WORKSPACE_RUN_MS));
      const asAdmin = (sudo) => client(request, base(), adminAuth, sudo);
      const sem = await semaphore(request);
      const workspace = randomUUID();
      const repository = `ws-${workspace}`;
      await withCleanup(async (cleanup) => {
        const token = await mintStoreToken(asAdmin);
        cleanup(async () => expectGone(await asAdmin(store).del(`/users/${store}/tokens/${token.id}`), "the probe token"));
        cleanup(async () => {
          const run = await runWorkspaceTask(sem, workspace, "destroy", SEMAPHORE_POLL_MS);
          expect(run.status, `workspace destroy task ${run.id} of ws-${workspace} must succeed`).toBe("success");
        });
        const first = await runWorkspaceTask(sem, workspace, "apply", SEMAPHORE_POLL_MS);
        const applied = workspaceResult(first, "apply");
        const second = await runWorkspaceTask(sem, workspace, "apply", SEMAPHORE_POLL_MS);
        const reapplied = workspaceResult(second, "apply");
        expect(applied.read_key, "apply must hand over the public half of the read key").toMatch(
          /^ssh-[a-z0-9-]+ [A-Za-z0-9+/]+={0,3}(?: \S+)?$/,
        );
        expect(reapplied.read_key, "a second apply must print the same read key").toBe(applied.read_key);
        for (const run of [first, second]) {
          expect(
            run.lines.some((line) => line.includes("PRIVATE KEY")),
            `the output of workspace task ${run.id} must hold no private key`,
          ).toBe(false);
        }
        const keyIds = new Set(Object.values(applied.templates).map((entry) => entry.ssh_key_id));
        const held = (await sem.call("GET", `/project/${applied.project_id}/keys`)).filter((key) => keyIds.has(key.id));
        expect(held.length, `the key store of ws-${workspace} must hold the key its templates clone with`).toBeGreaterThan(0);
        for (const key of held) {
          expect(key.type, `key ${key.id} of ws-${workspace} must be an SSH key`).toBe("ssh");
          const shown = JSON.stringify(await sem.call("GET", `/project/${applied.project_id}/keys/${key.id}`));
          expect(shown.includes("PRIVATE KEY"), `Semaphore must never hand out the private half of key ${key.id}`).toBe(false);
        }
        const asStore = client(request, base(), `token ${token.value}`);
        expect(
          (await asStore.post(`/orgs/${organization}/repos`, { name: repository, private: true, auto_init: true })).status(),
          `the store creates ${organization}/${repository}`,
        ).toBe(201);
        cleanup(async () => expectGone(await asAdmin().del(`/repos/${organization}/${repository}`), `repository ${repository}`));
        expect(
          (await asStore.post(`/repos/${organization}/${repository}/keys`, {
            title: "semaphore",
            key: applied.read_key,
            read_only: true,
          })).status(),
          "the store registers the read key unchanged as a read-only deploy key",
        ).toBe(201);
        const registered = await (await asStore.get(`/repos/${organization}/${repository}/keys`)).json();
        expect(
          registered.map((key) => [keyBody(key.key), key.read_only]),
          "the repository's only deploy key must be the read key apply printed, read-only",
        ).toEqual([[keyBody(applied.read_key), true]]);
      });
    });

    test("gitea workspaces: only the store writes main", async ({ request }) => {
      requireTools(["git", "ssh", "ssh-keygen"]);
      const asAdmin = (sudo) => client(request, base(), adminAuth, sudo);
      const repository = `ws-playwright-${suffix()}`;
      const member = { username: `playwright-member-${suffix()}`, password: probePassword() };
      const repoApi = `/repos/${organization}/${repository}`;
      const sshRemote = `ssh://git@${domain}:${sshPort}/${organization}/${repository}.git`;
      const httpsRemote = `${base().replace(/\/$/, "")}/${organization}/${repository}.git`;
      const directory = fs.mkdtempSync(path.join(os.tmpdir(), "gitea-protected-main-"));
      await withCleanup(async (cleanup) => {
        cleanup(() => fs.rmSync(directory, { recursive: true, force: true }));
        const token = await mintStoreToken(asAdmin);
        cleanup(async () => expectGone(await asAdmin(store).del(`/users/${store}/tokens/${token.id}`), "the probe token"));
        const asStore = client(request, base(), `token ${token.value}`);
        expect(
          (await asStore.post(`/orgs/${organization}/repos`, {
            name: repository,
            private: true,
            auto_init: true,
            default_branch: "main",
          })).status(),
          `the store creates ${organization}/${repository}`,
        ).toBe(201);
        cleanup(async () => expectGone(await asAdmin().del(repoApi), `repository ${repository}`));
        expect(
          (await asStore.post(`${repoApi}/branch_protections`, {
            rule_name: "main",
            enable_push: true,
            enable_push_whitelist: true,
            push_whitelist_usernames: [],
            push_whitelist_teams: [],
            push_whitelist_deploy_keys: true,
            enable_force_push: false,
          })).status(),
          "the store protects main",
        ).toBe(201);
        const writer = sshKey(directory, "store");
        expect(
          (await asStore.post(`${repoApi}/keys`, { title: "store", key: writer.public, read_only: false })).status(),
          "the store adds its write deploy key",
        ).toBe(201);
        const team = await asStore.post(`/orgs/${organization}/teams`, {
          name: repository,
          permission: "write",
          units_map: { "repo.code": "write" },
          includes_all_repositories: false,
          can_create_org_repo: false,
        });
        expect(team.status(), `the store creates team ${repository} with write`).toBe(201);
        const teamId = (await team.json()).id;
        cleanup(async () => expectGone(await asAdmin().del(`/teams/${teamId}`), `team ${repository}`));
        expect((await asStore.put(`/teams/${teamId}/repos/${organization}/${repository}`)).status()).toBe(204);
        expect(
          (await asAdmin().post(`/admin/users`, {
            username: member.username,
            email: `${member.username}@example.invalid`,
            password: member.password,
            must_change_password: false,
          })).status(),
          "the administrator creates the member",
        ).toBe(201);
        cleanup(async () => expectGone(await asAdmin().del(`/admin/users/${member.username}`), `user ${member.username}`));
        expect((await asStore.put(`/teams/${teamId}/members/${member.username}`)).status()).toBe(204);
        const memberToken = await asAdmin(member.username).post(`/users/${member.username}/tokens`, {
          name: `playwright-${suffix()}`,
          scopes: ["write:repository", "read:user"],
        });
        expect(memberToken.status(), "the administrator mints a token for the member").toBe(201);
        const memberSecret = (await memberToken.json()).sha1;
        const asMember = client(request, base(), `token ${memberSecret}`);
        const memberBasic = basic(member.username, memberSecret);

        const storeClone = path.join(directory, "store");
        git(["clone", "-q", sshRemote, storeClone], directory, writer.file);
        const storeHead = commit(storeClone, "inventory.yml", "store inventory");
        git(["push", "-q", "origin", "HEAD:main"], storeClone, writer.file);

        const memberClone = path.join(directory, "member");
        httpsGit(["clone", "-q", httpsRemote, memberClone], directory, memberBasic);
        commit(memberClone, "member.yml", "member change");
        expect(
          () => httpsGit(["push", "-q", "origin", "HEAD:main"], memberClone, memberBasic),
          "a member with write must be refused on a push to main",
        ).toThrow();
        execFileSync("git", ["reset", "-q", "--hard", "HEAD~2"], { cwd: memberClone, stdio: "pipe" });
        commit(memberClone, "rewrite.yml", "member rewrite");
        expect(
          () => httpsGit(["push", "-q", "--force", "origin", "HEAD:main"], memberClone, memberBasic),
          "a member with write must be refused on a force push to main",
        ).toThrow();
        expect(
          (await asMember.patch(`${repoApi}/branches/main`, { name: "renamed" })).status(),
          "a member must be refused on a rename of main",
        ).toBe(403);
        expect((await asMember.del(`${repoApi}/branches/main`)).status(), "a member must be refused on a delete of main").toBe(403);
        expect(
          (await asMember.patch(`${repoApi}/branch_protections/main`, { enable_push_whitelist: false })).status(),
          "a member must be refused on a change of the protection of main",
        ).toBe(403);

        const branch = await asStore.get(`${repoApi}/branches/main`);
        expect(branch.status(), "main must still exist under its name").toBe(200);
        expect((await branch.json()).commit.id, "main must hold exactly the store's commit").toBe(storeHead);
        const protection = await asStore.get(`${repoApi}/branch_protections/main`);
        expect(protection.status(), "the protection of main must still exist").toBe(200);
        const rule = await protection.json();
        expect(
          [rule.enable_push, rule.enable_push_whitelist, rule.push_whitelist_deploy_keys, rule.enable_force_push],
          "the protection of main must be the one the store set",
        ).toEqual([true, true, true, false]);
      });
    });
  });
};
