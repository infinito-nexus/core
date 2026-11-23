const crypto = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { requireDotenvValue } = require("./personas");
const { strictFlag } = require("./personas/utils/workspace");
const workspaces = require("./workspace-fixture");

const LABEL = "locked-template";
const TOKEN_LABEL = "task token";
const TEMPLATE = "start all";
const MARKER_ENVIRONMENT = "playwright realign start all";
const SIGN_IN_MS = 2 * 60_000;
const REQUEST_MS = 30_000;
const WORKSPACE_MS = 30 * 60_000;
const PROBE_MS = 10 * 60_000;
const LOCKED_FLAGS = ["allow_override_args_in_task", "allow_override_branch_in_task", "allow_parallel_tasks"];
const JWT_AUDIENCE = "openbao";
const SURVEY_TARGET = "env";
const KEY_SET_PATH = "/.well-known/jwks.json";
const PRIVATE_KEY_MEMBERS = ["d", "p", "q", "dp", "dq", "qi", "k"];
const JWT_VERIFIER = `import base64, hashlib, json, os, sys
P = 2**256 - 2**224 + 2**192 + 2**96 - 1
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296, 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)
def add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    if a == b:
        slope = (3 * a[0] * a[0] - 3) * pow(2 * a[1], -1, P) % P
    else:
        slope = (b[1] - a[1]) * pow(b[0] - a[0], -1, P) % P
    x = (slope * slope - a[0] - b[0]) % P
    return (x, (slope * (a[0] - x) - a[1]) % P)
def mul(k, point):
    result = None
    while k:
        if k & 1:
            result = add(result, point)
        point = add(point, point)
        k >>= 1
    return result
def decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
def verifies(signed, signature, key):
    q = (int.from_bytes(decode(key["x"]), "big"), int.from_bytes(decode(key["y"]), "big"))
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if len(signature) != 64 or not (0 < r < N and 0 < s < N):
        return False
    e = int.from_bytes(hashlib.sha256(signed.encode()).digest(), "big")
    w = pow(s, -1, N)
    point = add(mul(e * w % N, G), mul(r * w % N, q))
    return point is not None and point[0] % N == r
header, payload, signature = os.environ["SEMAPHORE_JWT"].split(".")
head = json.loads(decode(header))
key = next((k for k in json.loads(decode(sys.argv[1]))["keys"] if k.get("kid") == head.get("kid")), None)
usable = key is not None and head.get("alg") == "ES256" and key.get("crv") == "P-256"
claims = json.loads(decode(payload))
tampered = base64.urlsafe_b64encode(json.dumps({**claims, "template_id": -1}).encode()).decode().rstrip("=")
print("PROBE jwt-header " + json.dumps(head, sort_keys=True))
print("PROBE jwt-claims " + json.dumps(claims, sort_keys=True))
print("PROBE jwt-verified " + str(usable and verifies(f"{header}.{payload}", decode(signature), key)).lower())
print("PROBE jwt-tampered-verified " + str(usable and verifies(f"{header}.{tampered}", decode(signature), key)).lower())
`;
const JWT_PROBE_SCRIPT = ["set -euo pipefail", "exec python3 - \"$@\" <<'PY'", JWT_VERIFIER, "PY", ""].join("\n");
const OVERRIDE_PROBE_SCRIPT = [
  "set -u",
  "printf 'PROBE branch %s\\n' \"$(git rev-parse --abbrev-ref HEAD)\"",
  "printf 'PROBE inventory %s\\n' \"${SEMAPHORE_TASK_DETAILS_INVENTORY_ID:-none}\"",
  "",
].join("\n");
const TASK_ARGUMENT = "task-argument";
const TASK_BRANCH = "playwright-task-branch";

function issuer() {
  return requireDotenvValue(process.env.SEMAPHORE_JWT_ISSUER, "SEMAPHORE_JWT_ISSUER");
}

/**
 * Args:
 *   context: a browser context.
 *
 * Returns:
 *   The keys of the key set the canonical origin serves.
 */
async function keySet(context) {
  const url = `${new URL(issuer()).origin}${KEY_SET_PATH}`;
  const response = await workspaces.http(context, "GET", url);
  await workspaces.expectStatus(response, [200], `${TOKEN_LABEL}: GET ${url}`);
  return (await response.json()).keys || [];
}

/**
 * Args:
 *   run: a finished probe run.
 *   kind: the first word after `PROBE`.
 *   what: the run the failure message names.
 *
 * Returns:
 *   The one value the probe printed for `kind`.
 */
function probeValue(run, kind, what) {
  const values = workspaces.probeLines(run, kind);
  expect(values, `${what}: the probe must print exactly one ${kind} line`).toHaveLength(1);
  return values[0];
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *
 * Returns:
 *   The identity apply returned for unlock ws-<id>, whose provision project holds the probe ws-<id>.
 */
function provisionIdentity(fixture) {
  const name = `unlock ws-${fixture.workspace}`;
  const identity = fixture.result.templates[name];
  expect(identity, `${TOKEN_LABEL}: workspace apply must return the template "${name}"`).toBeTruthy();
  return identity;
}

exports.register = function (shared) {
  test("task token: the key set answers on the canonical origin", async ({ page }) => {
    test.setTimeout(resolveTimeout(2 * REQUEST_MS));
    const keys = await keySet(page.context());
    expect(keys.length, `${TOKEN_LABEL}: ${issuer()}${KEY_SET_PATH} must list at least one key`).toBeGreaterThan(0);
    for (const key of keys) {
      expect(Boolean(key.kty), `${TOKEN_LABEL}: key ${key.kid} of the key set must name its type`).toBe(true);
      expect(
        PRIVATE_KEY_MEMBERS.filter((member) => member in key),
        `${TOKEN_LABEL}: key ${key.kid} of the key set must be a public key`,
      ).toEqual([]);
    }
  });

  test("task token: a task receives a token for its own project and template", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(2 * WORKSPACE_MS + PROBE_MS + 20 * REQUEST_MS));
    await workspaces.withWorkspace(shared, browser, TOKEN_LABEL, "", async (fixture) => {
      const identity = provisionIdentity(fixture);
      const keys = await keySet(fixture.context);
      const what = `${TOKEN_LABEL}: probe ws-${fixture.workspace}`;
      const run = await workspaces.runProbe(
        shared,
        fixture,
        identity.project_id,
        JWT_PROBE_SCRIPT,
        [Buffer.from(JSON.stringify({ keys })).toString("base64url")],
        what,
      );
      workspaces.expectSucceeded(run, what);
      const header = JSON.parse(probeValue(run, "jwt-header", what));
      expect(
        keys.map((key) => key.kid),
        `${what}: the token must name a key of the key set, it names ${header.kid}`,
      ).toContain(header.kid);
      const claims = JSON.parse(probeValue(run, "jwt-claims", what));
      expect(
        {
          project_id: claims.project_id,
          template_id: claims.template_id,
          task_id: claims.task_id,
          aud: [...new Set([].concat(claims.aud))],
          iss: claims.iss,
        },
        `${what}: the token must name the task, its project and template, the audience ${JWT_AUDIENCE} and the configured issuer`,
      ).toEqual({
        project_id: identity.project_id,
        template_id: run.task.template_id,
        task_id: run.task.id,
        aud: [JWT_AUDIENCE],
        iss: issuer(),
      });
      expect(probeValue(run, "jwt-verified", what), `${what}: the token's signature must verify against the key set`).toBe("true");
      expect(
        probeValue(run, "jwt-tampered-verified", what),
        `${what}: the probe's verifier must refuse the same signature over a changed template_id`,
      ).toBe("false");
    });
  });

  test("locked template: run-time overrides do not reach the script", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(2 * WORKSPACE_MS + PROBE_MS + 20 * REQUEST_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const project = provisionIdentity(fixture).project_id;
      const probe = await workspaces.namedTemplate(shared, fixture.page, project, `probe ws-${fixture.workspace}`);
      const repository = await shared.api(fixture.page, "GET", `/project/${project}/repositories/${probe.repository_id}`);
      const inventory = await shared.api(fixture.page, "GET", `/project/${project}/inventory/${probe.inventory_id}`);
      const other = await shared.api(fixture.page, "POST", `/project/${project}/inventory`, {
        ...inventory,
        id: undefined,
        name: `${LABEL} ws-${fixture.workspace}`,
      });
      cleanup(() => shared.api(fixture.page, "DELETE", `/project/${project}/inventory/${other.id}`));
      const task = await shared.api(fixture.page, "POST", `/project/${project}/tasks`, {
        template_id: probe.id,
        environment: JSON.stringify({ PROBE_SCRIPT: OVERRIDE_PROBE_SCRIPT, PROBE_ARGS: "" }),
        arguments: JSON.stringify([TASK_ARGUMENT]),
        inventory_id: other.id,
        git_branch: TASK_BRANCH,
      });
      const what = `${LABEL}: task ${task.id} of the locked probe ws-${fixture.workspace} started with its own arguments, inventory and branch`;
      let run;
      try {
        run = await workspaces.awaitTask(shared, fixture.page, project, task.id, PROBE_MS, what);
      } finally {
        await shared.stopUnfinishedTask(fixture.page, project, task.id);
      }
      workspaces.expectSucceeded(run, `${what}, where probe.sh refuses any argument that reaches it`);
      expect(workspaces.probeLines(run, "branch"), `${what}: the script must run on the template's branch`).toEqual([repository.git_branch]);
      expect(
        workspaces.probeLines(run, "inventory"),
        `${what}: Semaphore must run the script with the template's inventory, which it hands a shell task as SEMAPHORE_TASK_DETAILS_INVENTORY_ID`,
      ).toEqual([String(probe.inventory_id)]);
    });
  });

  /**
   * Args:
   *   page: a page carrying the break-glass session.
   *
   * Returns:
   *   The app-control `project` and its template `start all` as the API returns it.
   */
  async function startAll(page) {
    const projects = await shared.api(page, "GET", "/projects");
    const project = projects.find((candidate) => candidate.name === shared.env.projectName);
    expect(project, `${LABEL}: the app-control project "${shared.env.projectName}" must exist`).toBeTruthy();
    const named = (await shared.api(page, "GET", `/project/${project.id}/templates`)).filter((template) => template.name === TEMPLATE);
    expect(named, `${LABEL}: the project "${project.name}" must hold exactly one template "${TEMPLATE}"`).toHaveLength(1);
    return { project, template: await shared.api(page, "GET", `/project/${project.id}/templates/${named[0].id}`) };
  }

  /**
   * Args:
   *   page: a page carrying the break-glass session.
   *   projectId: the app-control project.
   *
   * Returns:
   *   Every marker environment a first pass left in the project.
   */
  async function markers(page, projectId) {
    return (await shared.api(page, "GET", `/project/${projectId}/environment`)).filter((environment) => environment.name === MARKER_ENVIRONMENT);
  }

  /**
   * Args:
   *   page: a page carrying the break-glass session.
   *   projectId: the app-control project.
   */
  async function dropMarkers(page, projectId) {
    for (const marker of await markers(page, projectId)) {
      await shared.api(page, "DELETE", `/project/${projectId}/environment/${marker.id}`);
    }
  }

  test("locked template: a deploy realigns a template changed by hand", async ({ page }) => {
    const updatePass = strictFlag(process.env.DEPLOY_IS_UPDATE, "DEPLOY_IS_UPDATE");
    test.setTimeout(resolveTimeout(SIGN_IN_MS + 20 * REQUEST_MS));
    await shared.signInViaBreakglassApi(page, shared.env.breakglassUsername, shared.env.breakglassPassword, LABEL);
    const { project, template } = await startAll(page);

    if (!updatePass) {
      await dropMarkers(page, project.id);
      const marker = `${LABEL} ${crypto.randomUUID()}`;
      await shared.api(page, "PUT", `/project/${project.id}/templates/${template.id}`, {
        ...template,
        allow_parallel_tasks: true,
        description: marker,
      });
      try {
        const changed = await shared.api(page, "GET", `/project/${project.id}/templates/${template.id}`);
        expect(
          [changed.allow_parallel_tasks, changed.description],
          `${LABEL}: the hand change of "${TEMPLATE}" must land before the next deploy realigns it`,
        ).toEqual([true, marker]);
        await shared.api(page, "POST", `/project/${project.id}/environment`, {
          project_id: project.id,
          name: MARKER_ENVIRONMENT,
          json: "{}",
          env: JSON.stringify({ REALIGN_TEMPLATE_ID: String(template.id), REALIGN_MARKER: marker }),
          password: null,
          secrets: [],
        });
      } catch (error) {
        await shared
          .api(page, "PUT", `/project/${project.id}/templates/${template.id}`, template)
          .catch((restore) => console.warn(`${LABEL}: restoring "${TEMPLATE}" after the failed first pass failed: ${restore.message}`));
        throw error;
      }
    } else {
      const found = await markers(page, project.id);
      try {
        expect(
          found,
          `${LABEL}: the first pass must have left exactly one marker environment "${MARKER_ENVIRONMENT}" with the hand change it made`,
        ).toHaveLength(1);
        const recorded = JSON.parse(found[0].env);
        expect(recorded.REALIGN_TEMPLATE_ID, `${LABEL}: the deploy must realign "${TEMPLATE}" in place, keeping its id`).toBe(
          String(template.id),
        );
        expect(template.description || "", `${LABEL}: the deploy must rewrite "${TEMPLATE}" from its definition, dropping the hand-set description`).not.toBe(
          recorded.REALIGN_MARKER,
        );
        for (const flag of LOCKED_FLAGS) {
          expect(Boolean(template[flag]), `${LABEL}: the deploy must turn ${flag} of "${TEMPLATE}" off again`).toBe(false);
        }
        expect(
          Boolean(template.jwt_params && template.jwt_params.enabled) && [...new Set([].concat(template.jwt_params.audience))].join() === JWT_AUDIENCE,
          `${LABEL}: "${TEMPLATE}" must issue a task token for ${JWT_AUDIENCE} after the deploy`,
        ).toBe(true);
        expect(Boolean(template.runner_tag), `${LABEL}: "${TEMPLATE}" must name its runner tag after the deploy`).toBe(true);
        expect(
          (template.survey_vars || []).filter((variable) => variable.target !== SURVEY_TARGET).map((variable) => variable.name),
          `${LABEL}: every survey variable of "${TEMPLATE}" must reach the script as an environment variable`,
        ).toEqual([]);
      } finally {
        await dropMarkers(page, project.id);
      }
    }
    await shared.logout(page, LABEL);
  });
};
