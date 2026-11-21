const crypto = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { requireDotenvValue } = require("./personas");
const { sshEd25519PublicLine } = require("./personas/utils/workspace");
const workspaces = require("./workspace-fixture");

const LABEL = "workspace-logins";
const SETUP_MS = 65 * 60_000;
const CLEANUP_MS = 65 * 60_000;
const RUN_MS = 10 * 60_000;
const DESTROY_MS = 30 * 60_000;
const SSH_PORT = 22;
const HOST_OF_A = "9.9.9.9";
const HOST_OF_B = "1.1.1.1";
const TENANT = "tenant";
const PLATFORM = "platform";
const REFUSED = ["400", "403"];
const OTHER_AUDIENCE = "not-openbao";
const PROBE_TEMPLATE = "probe";
const PRUNE_TEMPLATE = "prune task entities";
const PRUNE_LINE = /^prune task entities: (at|own|kept|deleted) (\S+)(?: until (\S+))?$/;
const PROBE_CALL_MS = 30_000;
const PROBE_TEXT = `set -u
exec python3 - "$@" <<'PY'
import json, os, ssl, sys, urllib.error, urllib.request
addr = os.environ.get("BAO_ADDR", "").rstrip("/")
if not addr:
    print("PROBE env no-bao-addr")
    sys.exit(1)
cafile = os.environ.get("BAO_CACERT") or os.environ.get("PROVISION_CA_FILE") or None
handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=cafile))]
if os.environ.get("EGRESS_PROXY"):
    handlers.append(urllib.request.ProxyHandler({"https": "http://" + os.environ["EGRESS_PROXY"]}))
opener = urllib.request.build_opener(*handlers)
def call(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(addr + "/v1/" + path, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=${resolveTimeout(PROBE_CALL_MS) / 1000}) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except ValueError:
            return error.code, {}
token = None
for step in sys.argv[1:]:
    verb, _, target = step.partition("=")
    if verb == "login":
        mount, _, role = target.partition("/")
        status, answer = call("POST", "auth/" + mount + "/login", None, {"role": role, "jwt": os.environ.get("SEMAPHORE_JWT", "")})
        errors = " ".join(str(error) for error in answer.get("errors") or [])
        token = (answer.get("auth") or {}).get("client_token") if status == 200 else None
        reason = "ok" if status == 200 else ("missing-role" if "could not be found" in errors else "refused")
        print("PROBE login " + target + " " + str(status) + " " + reason)
    else:
        status, _ = call(verb, target, token, {} if verb == "POST" else None)
        print("PROBE call " + verb + " " + target + " " + str(status))
if token:
    call("POST", "auth/token/revoke-self", token, {})
PY
`;

/**
 * Args:
 *   run: a finished probe run.
 *
 * Returns:
 *   `{ logins, calls }`: the status and reason of every login by `<mount>/<role>`,
 *   and the status of every call by `<METHOD> <path>`.
 */
function outcome(run) {
  const logins = Object.fromEntries(
    workspaces.probeLines(run, "login").map((line) => {
      const [target, status, reason] = line.split(" ");
      return [target, { status, reason }];
    }),
  );
  const calls = Object.fromEntries(
    workspaces.probeLines(run, "call").map((line) => {
      const parts = line.split(" ");
      return [`${parts[0]} ${parts[1]}`, parts[2]];
    }),
  );
  return { logins, calls };
}

function expectLogin(run, target, reason, what) {
  const login = outcome(run).logins[target];
  expect(login, `${what}: the probe must report its login to ${target}; output tail:\n${workspaces.outputTail(run.lines)}`).toBeTruthy();
  expect(login.reason, `${what}: the login to ${target} answered ${login.status}`).toBe(reason);
  if (reason !== "ok") {
    expect(REFUSED, `${what}: a refused login to ${target} must answer 400 or 403`).toContain(login.status);
  }
}

function expectCall(run, call, status, what) {
  expect(outcome(run).calls[call], `${what}: ${call}; output tail:\n${workspaces.outputTail(run.lines)}`).toBe(status);
}

/**
 * Args:
 *   run: a finished run of the prune template.
 *
 * Returns:
 *   `at`, the task's clock in ms, `own`, its own entity id, `kept`, every
 *   other task entity id mapped to the ms it turns prunable, and `deleted`.
 */
function pruneReport(run) {
  const report = { at: null, own: null, kept: {}, deleted: [] };
  for (const line of run.lines) {
    const match = PRUNE_LINE.exec(workspaces.bare(line));
    if (!match) continue;
    if (match[1] === "at") report.at = Date.parse(match[2]);
    if (match[1] === "own") report.own = match[2];
    if (match[1] === "kept") report.kept[match[2]] = Date.parse(match[3]);
    if (match[1] === "deleted") report.deleted.push(match[2]);
  }
  expect([Number.isFinite(report.at), Boolean(report.own)], `${LABEL}: the prune must report its clock and its own entity`).toEqual([
    true,
    true,
  ]);
  return report;
}

function platformProject(fixture, kind) {
  const identity = fixture.result.templates[`${kind} ${fixture.result.alias}`];
  expect(identity, `${LABEL}: apply must report the ${kind} template of ${fixture.result.alias}`).toBeTruthy();
  return identity;
}

exports.register = function (shared) {
  test.describe("workspace task logins", () => {
    test.describe.configure({ retries: 0, mode: "serial" });
    const a = workspaces.workspaceFixture();
    const b = workspaces.workspaceFixture();
    const written = [];
    const hostKey = () => `store/hostkeys/ws-${a.workspace}/${HOST_OF_A}/${SSH_PORT}`;

    async function probe(fixture, projectId, steps, what) {
      const run = await workspaces.runProbe(shared, fixture, projectId, PROBE_TEXT, steps, `${LABEL}: ${what}`);
      workspaces.expectSucceeded(run, `${LABEL}: ${what}`);
      return run;
    }

    async function storeWrite(mount, path, data) {
      const token = await workspaces.storeVaultToken(a.context);
      await workspaces.vaultWrite(a.context, token, mount, path, data);
      written.push([mount, path]);
    }

    /**
     * Args:
     *   fixture: the workspace whose probe template is copied.
     *   steps: the probe steps.
     *
     * Returns:
     *   The finished run of a copy of the workspace's probe template whose task
     *   token names another audience; the copy is deleted afterwards.
     */
    async function otherAudienceProbe(fixture, steps) {
      const projectId = fixture.result.project_id;
      const original = await workspaces.namedTemplate(shared, fixture.page, projectId, PROBE_TEMPLATE);
      const body = { ...(await shared.api(fixture.page, "GET", `/project/${projectId}/templates/${original.id}`)) };
      delete body.id;
      const copy = await shared.api(fixture.page, "POST", `/project/${projectId}/templates`, {
        ...body,
        name: `${PROBE_TEMPLATE} ${crypto.randomBytes(4).toString("hex")}`,
        jwt_params: { enabled: true, audience: OTHER_AUDIENCE },
      });
      try {
        const what = `${LABEL}: a probe whose task token names ${OTHER_AUDIENCE}`;
        const run = await workspaces.runTemplate(
          shared,
          fixture.page,
          projectId,
          copy.id,
          { PROBE_SCRIPT: PROBE_TEXT, PROBE_ARGS: steps.join(" ") },
          RUN_MS,
          what,
        );
        workspaces.expectSucceeded(run, what);
        return run;
      } finally {
        await shared.api(fixture.page, "DELETE", `/project/${projectId}/templates/${copy.id}`);
      }
    }

    test.beforeAll(async ({ browser }) => {
      workspaces.skipUnlessWorkspaces();
      test.setTimeout(resolveTimeout(SETUP_MS));
      await workspaces.openWorkspace(shared, browser, a, `${HOST_OF_A}:${SSH_PORT}`, LABEL);
      await workspaces.openWorkspace(shared, browser, b, `${HOST_OF_B}:${SSH_PORT}`, LABEL);
      const value = { value: crypto.randomBytes(16).toString("hex") };
      await storeWrite(TENANT, `ws-${a.workspace}/x`, value);
      await storeWrite(TENANT, `ws-${a.workspace}-provision/x`, value);
      await storeWrite(TENANT, `ws-${b.workspace}/x`, value);
      await storeWrite(TENANT, `ws-${a.workspace}/usage`, value);
      await storeWrite(PLATFORM, hostKey(), { line: sshEd25519PublicLine() });
    });

    test.afterAll(async () => {
      test.setTimeout(resolveTimeout(CLEANUP_MS));
      const failures = [];
      if (a.context) {
        try {
          const token = await workspaces.storeVaultToken(a.context);
          for (const [mount, path] of written) {
            await workspaces.vaultDestroy(a.context, token, mount, path);
          }
        } catch (error) {
          failures.push(error);
        }
      }
      for (const fixture of [b, a]) {
        if (fixture.context) {
          try {
            await workspaces.closeWorkspace(shared, fixture, LABEL);
          } catch (error) {
            failures.push(error);
          }
        }
      }
      if (failures.length > 0) {
        throw new AggregateError(failures, `${LABEL}: the cleanup failed: ${failures.map((failure) => failure.message).join("; ")}`);
      }
    });

    test("task login: each workspace task logs in only to its own role", async () => {
      test.setTimeout(resolveTimeout(4 * RUN_MS));
      const roleOfA = `jwt/ws-${a.workspace}`;
      expectLogin(await probe(a, a.result.project_id, [`login=${roleOfA}`], "a task of A"), roleOfA, "ok", "a task of A with its own role");
      expectLogin(await probe(b, b.result.project_id, [`login=${roleOfA}`], "a task of B"), roleOfA, "refused", "a task of B with the role of A");
      expectLogin(await otherAudienceProbe(a, [`login=${roleOfA}`]), roleOfA, "refused", `a task of A whose token names ${OTHER_AUDIENCE}`);
      const provisionOfA = `${roleOfA}-provision`;
      expectLogin(
        await probe(a, a.result.project_id, [`login=${provisionOfA}`], "a task of the workspace project of A"),
        provisionOfA,
        "refused",
        "a task of the workspace project of A with the provision role of A",
      );
    });

    test("tenant policy: a deploy token reads only its own subtree", async () => {
      test.setTimeout(resolveTimeout(RUN_MS));
      const reads = [
        [`GET ${TENANT}/data/ws-${a.workspace}/x`, "200"],
        [`GET ${TENANT}/data/ws-${b.workspace}/x`, "403"],
        [`GET ${TENANT}/data/ws-${a.workspace}-provision/x`, "403"],
        [`GET ${PLATFORM}/data/store/x`, "403"],
        ["GET infinito/data/x", "403"],
      ];
      const run = await probe(
        a,
        a.result.project_id,
        [`login=jwt/ws-${a.workspace}`, ...reads.map(([call]) => call.replace(" ", "="))],
        "the deploy token of A",
      );
      expectLogin(run, `jwt/ws-${a.workspace}`, "ok", "the deploy token of A");
      for (const [call, status] of reads) {
        expectCall(run, call, status, "the deploy token of A");
      }
    });

    test("tenant policy: a provision token uses only its own key", async () => {
      test.setTimeout(resolveTimeout(3 * RUN_MS));
      const dns = platformProject(a, "dns");
      const what = `${LABEL}: a dns remove of ${a.result.alias} with nothing to remove`;
      const order = `PW${crypto.randomBytes(5).toString("hex").toUpperCase()}`;
      workspaces.expectSucceeded(
        await workspaces.runTemplate(
          shared,
          a.page,
          dns.project_id,
          dns.template_id,
          { DNS_ACTION: "remove", SALES_ORDER: order, LINE: "1", HOST: HOST_OF_A, DNS_LABEL: `pw${order.toLowerCase()}` },
          RUN_MS,
          what,
        ),
        what,
      );
      const provisionOfA = `jwt/ws-${a.workspace}-provision`;
      expectLogin(
        await probe(a, dns.project_id, [`login=${provisionOfA}`], "the provision probe of A"),
        provisionOfA,
        "refused",
        "a task of the provision project of A outside its bound templates",
      );
      const keys = [
        [`POST transit/datakey/plaintext/ws-${b.workspace}-provision`, "403"],
        [`POST transit/decrypt/ws-${b.workspace}-provision`, "403"],
        [`POST transit/datakey/plaintext/ws-${a.workspace}-provision`, "403"],
      ];
      const run = await probe(
        a,
        a.result.project_id,
        [`login=jwt/ws-${a.workspace}`, ...keys.map(([call]) => call.replace(" ", "="))],
        "the deploy token of A on the provision keys",
      );
      for (const [call, status] of keys) {
        expectCall(run, call, status, "the deploy token of A");
      }
    });

    test("tenant policy: concurrent logins keep their own metadata", async () => {
      test.setTimeout(resolveTimeout(2 * RUN_MS));
      const pairs = [
        [a, b],
        [b, a],
      ];
      const started = await Promise.all(
        pairs.map(async ([own, other]) => {
          const template = await workspaces.namedTemplate(shared, own.page, own.result.project_id, PROBE_TEMPLATE);
          const steps = [`login=jwt/ws-${own.workspace}`, `GET=${TENANT}/data/ws-${own.workspace}/x`, `GET=${TENANT}/data/ws-${other.workspace}/x`];
          const taskId = await workspaces.startTask(shared, own.page, own.result.project_id, template.id, {
            PROBE_SCRIPT: PROBE_TEXT,
            PROBE_ARGS: steps.join(" "),
          });
          return { own, other, taskId };
        }),
      );
      const runs = await Promise.all(
        started.map(async ({ own, other, taskId }) => {
          try {
            const run = await workspaces.awaitTask(shared, own.page, own.result.project_id, taskId, RUN_MS, `${LABEL}: ${own.result.alias}`);
            return { own, other, run };
          } finally {
            await shared.stopUnfinishedTask(own.page, own.result.project_id, taskId);
          }
        }),
      );
      for (const { own, other, run } of runs) {
        const what = `the concurrent task of ${own.result.alias}`;
        workspaces.expectSucceeded(run, `${LABEL}: ${what}`);
        expectLogin(run, `jwt/ws-${own.workspace}`, "ok", what);
        expectCall(run, `GET ${TENANT}/data/ws-${own.workspace}/x`, "200", what);
        expectCall(run, `GET ${TENANT}/data/ws-${other.workspace}/x`, "403", what);
      }
    });

    test("store approle: owns the pinned host keys and no task reads them", async () => {
      test.setTimeout(resolveTimeout(3 * RUN_MS));
      const entry = `GET ${PLATFORM}/data/${hostKey()}`;
      const run = await probe(a, a.result.project_id, [`login=jwt/ws-${a.workspace}`, entry.replace(" ", "=")], "the deploy token of A");
      expectCall(run, entry, "403", "the deploy token of A on its pinned host key");
      for (const [template, role, kind] of [
        ["unlock", `jwt/ws-${a.workspace}-provision`, "provision"],
        ["export", `jwt-export/ws-${a.workspace}`, "export"],
      ]) {
        const project = platformProject(a, template);
        const refused = await probe(a, project.project_id, [`login=${role}`, entry.replace(" ", "=")], `the ${kind} probe of A`);
        expectLogin(refused, role, "refused", `a task of the ${kind} project of A outside its bound template`);
        expectCall(refused, entry, "403", `the ${kind} probe of A on the pinned host key`);
      }
    });

    test("export login: the announcer reads no tenant secret", async () => {
      test.setTimeout(resolveTimeout(2 * RUN_MS));
      const exportProject = platformProject(a, "export").project_id;
      const announce = await workspaces.namedTemplate(shared, a.page, exportProject, "announce owners");
      const what = `${LABEL}: announce owners`;
      workspaces.expectSucceeded(await workspaces.runTemplate(shared, a.page, exportProject, announce.id, {}, RUN_MS, what), what);
      const role = "jwt-export/announce-owners";
      const read = `GET ${TENANT}/data/ws-${a.workspace}/x`;
      const run = await probe(a, exportProject, [`login=${role}`, read.replace(" ", "=")], "the export probe of A");
      expectLogin(run, role, "refused", "a task of the export project of A with the announcer role");
      expectCall(run, read, "403", "the export probe of A");
    });

    test("export login: an export reads only its own workspace", async () => {
      test.setTimeout(resolveTimeout(2 * RUN_MS));
      const exportProject = platformProject(a, "export").project_id;
      const role = `jwt-export/ws-${a.workspace}`;
      expectLogin(await probe(a, exportProject, [`login=${role}`], "the export probe of A"), role, "refused", "the export probe of A outside the export template");
      expectLogin(await probe(b, exportProject, [`login=${role}`], "the export probe of B"), role, "refused", "the export probe of B with the export role of A");
    });

    test("provision login: the dns template reads only its own workspace", async () => {
      test.setTimeout(resolveTimeout(3 * RUN_MS));
      const dnsOfB = platformProject(b, "dns");
      const order = `PW${crypto.randomBytes(5).toString("hex").toUpperCase()}`;
      const what = `${LABEL}: a dns remove of ${b.result.alias}`;
      workspaces.expectSucceeded(
        await workspaces.runTemplate(
          shared,
          b.page,
          dnsOfB.project_id,
          dnsOfB.template_id,
          { DNS_ACTION: "remove", SALES_ORDER: order, LINE: "1", HOST: HOST_OF_B, DNS_LABEL: `pw${order.toLowerCase()}` },
          RUN_MS,
          what,
        ),
        what,
      );
      const role = `jwt/ws-${a.workspace}-provision`;
      const read = `GET ${TENANT}/data/ws-${a.workspace}-provision/dns`;
      const run = await probe(b, dnsOfB.project_id, [`login=${role}`, read.replace(" ", "=")], "the provision probe of B");
      expectLogin(run, role, "refused", "the provision probe of B with the provision role of A");
      expectCall(run, read, "403", "the provision probe of B on the dns credential of A");
    });

    test("usage login: a usage task reads only its own workspace's secret", async () => {
      test.setTimeout(resolveTimeout(2 * RUN_MS));
      const secret = `GET ${TENANT}/data/ws-${a.workspace}/usage`;
      const own = await probe(a, a.result.project_id, [`login=jwt/ws-${a.workspace}`, secret.replace(" ", "=")], "a task of A");
      expectCall(own, secret, "200", "a task of A on its own usage secret");
      const other = await probe(b, b.result.project_id, [`login=jwt/ws-${b.workspace}`, secret.replace(" ", "=")], "a task of B");
      expectLogin(other, `jwt/ws-${b.workspace}`, "ok", "a task of B with its own role");
      expectCall(other, secret, "403", "a task of B on the usage secret of A");
      const store = await workspaces.storeVaultToken(a.context);
      const origin = new URL(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL")).origin;
      const read = await workspaces.http(a.context, "GET", `${origin}/v1/${TENANT}/data/ws-${a.workspace}/usage`, {
        headers: { "X-Vault-Token": store },
      });
      await workspaces.expectStatus(read, [403], `${LABEL}: the store's read of the usage secret of A`);
    });

    test("jwt cleanup: the scheduled prune keeps every young entity", async () => {
      test.setTimeout(resolveTimeout(3 * RUN_MS));
      await probe(a, a.result.project_id, [`login=jwt/ws-${a.workspace}`], "a task of A before the prune");
      const project = await workspaces.namedProject(
        shared,
        a.page,
        requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_PROJECT_NAME, "SEMAPHORE_WORKSPACES_PROJECT_NAME"),
      );
      const template = await workspaces.namedTemplate(shared, a.page, project.id, PRUNE_TEMPLATE);
      const prune = async (what) => {
        const run = await workspaces.runTemplate(shared, a.page, project.id, template.id, {}, RUN_MS, `${LABEL}: ${what}`);
        workspaces.expectSucceeded(run, `${LABEL}: ${what}`);
        return pruneReport(run);
      };
      const first = await prune("the first prune");
      const second = await prune("the second prune");
      const listed = new Set([second.own, ...Object.keys(second.kept)]);
      expect(second.deleted, `${LABEL}: the second prune must not delete the own entity of the first`).not.toContain(first.own);
      expect(listed.has(first.own), `${LABEL}: the own entity of the first prune must still be there`).toBe(true);
      for (const [id, until] of Object.entries(first.kept).filter(([, until]) => until > second.at)) {
        expect(second.deleted, `${LABEL}: the second prune must keep ${id}, young until ${new Date(until).toISOString()}`).not.toContain(id);
        expect(listed.has(id), `${LABEL}: ${id}, young until ${new Date(until).toISOString()}, must still be there`).toBe(true);
      }
    });

    test("task login: destroy removes the workspace roles", async () => {
      test.setTimeout(resolveTimeout(DESTROY_MS + 2 * RUN_MS));
      const roles = [`jwt/ws-${a.workspace}`, `jwt/ws-${a.workspace}-provision`, `jwt/ws-${a.workspace}-zone`];
      const before = await probe(b, b.result.project_id, roles.map((role) => `login=${role}`), "a task of B before A is destroyed");
      for (const role of roles) {
        expectLogin(before, role, "refused", `a task of B on ${role} while A exists`);
      }
      await workspaces.destroyWorkspace(shared, a, LABEL);
      const after = await probe(b, b.result.project_id, roles.map((role) => `login=${role}`), "a task of B after A is destroyed");
      for (const role of roles) {
        expectLogin(after, role, "missing-role", `a login to ${role} after the destroy of A`);
      }
    });
  });
};
