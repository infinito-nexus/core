const crypto = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiFetchOnion,
  decodeDotenvJsonList,
  keycloakAdminAddUserToGroup,
  keycloakAdminCreateUser,
  keycloakAdminDeleteUser,
  keycloakAdminToken,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");
const {
  ANSI,
  TASK_FINISHED,
  WORKSPACE_RESULT_LINE,
  sshEd25519PublicLine,
  strictFlag,
  targetAddressIn,
} = require("./personas/utils/workspace");
const {
  DEPLOY_ORDER,
  DEPLOY_RUN_MS,
  bare,
  commitInventory,
  corePicks,
  deployToSharedTarget,
  expectSucceeded,
  fixtureWorkspaceKey,
  namedTemplate,
  openbaoOrigin,
  pickedCore,
  probeLines,
  requireWorkspaces,
  runProbe,
  runTemplate,
  sharedTargetAddress,
  skipWithoutPlatformHost,
  stageWorkspaceKey,
  storeVaultToken,
  throwawaySshKey,
  vaultRead,
  withWorkspace,
} = require("./workspace-fixture");

const LABEL = "workspace-runners";
const SIGN_IN_MS = 2 * 60_000;
const REQUEST_MS = 30_000;
const WORKSPACE_TASK_MS = 30 * 60_000;
const MEMBERS_TASK_MS = 5 * 60_000;
const PROBE_TASK_MS = 10 * 60_000;
const RUNNER_ONLINE_MS = 5 * 60_000;
const TASK_START_MS = 5 * 60_000;
const APP_CONTROL_TASK_MS = 10 * 60_000;
const TOKEN_LIFETIME_MS = 15 * 60_000;
const BASE_MS = 2 * SIGN_IN_MS + RUNNER_ONLINE_MS + 60 * REQUEST_MS;
const ORGANIZATION_ROLES = ["Owner", "Admin", "Operator", "Billing", "Viewer"];
const MARKER = "workspace.id";
const RESULT_KEYS = ["alias", "project_id", "read_key", "templates", "workspace"];
const READ_KEY_PREFIX = "read ";
const HOST_TEMPLATES = ["deploy", "update", "backup", "restart"];
const PROBE_HOST = "192.0.2.1";
const ZERO_COMMIT = "0".repeat(40);
const TOKEN_PREFIX_LENGTH = 8;
const MEMBER_BRANCH = "member";
const SAFE_LINES_MAX = 40;
const PLATFORM_MOUNT = "platform";
const STORE_SEMAPHORE_PATH = "store/semaphore";
const STORE_GITEA_PATH = "store/gitea";
const ROTATION_TEMPLATE = "rotate store credentials";
const ROTATION_TASK_MS = 10 * 60_000;
const DAY_MS = 24 * 60 * 60_000;
const REVOKE_AFTER_MS = 14 * DAY_MS;
const SEMAPHORE_LIFETIME_MS = 30 * DAY_MS;
const CLOCK_SKEW_MS = 2 * 60_000;
const ENTRY_FIELDS = ["expires_at", "token"];
const RFC3339_OFFSET = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}$/;
const WEEKLY_CRON = /^\d{1,2} \d{1,2} \* \* [0-6]$/;
const PASSED_EXPIRY = "2000-01-01T00:00:00+00:00";
const STORE_TOKEN_PREFIX = "store-";
const STORE_TEMPLATES = ["members", "user", "workspace"];
const RUN_AND_READ = 1 | 128;
const WORKSPACE_PROJECT = /^ws-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const REFUSED_INPUT = "pw-not-a-uuid";
const BANNER = /^TASK \[(.+)\]/;
const ROLE_BANNER = /^TASK \[([a-z0-9-]+) : /;
const STEP_RESULT = /^(ok|changed|skipping|fatal|failed|ignored): \[/;
const SUMMARY = /summary created=(\d+) deleted=(\d+) unchanged=(\d+) gone=(\d+)/;
const CHANGE_LINE = /^(?:change workspace=|semaphore workspace=|semaphore user )/;
const LEFTOVER_PLACES = ["home", "task", "tmp", "socket"];
const LEFTOVER_PATHS = [
  'nonce="$1"',
  'task_dir="$(dirname "${PWD}")"',
  'home="${HOME}/pw-${nonce}"',
  'task="${task_dir}/pw-${nonce}"',
  'tmp="/tmp/pw-${nonce}"',
  'socket="${HOME}/.ssh/cp-${nonce}"',
  "status() {",
  "  if \"${@:2}\"; then printf 'PROBE %s allowed 0\\n' \"$1\"; else printf 'PROBE %s refused 1\\n' \"$1\"; fi",
  "}",
];
const LEFTOVER_WRITE_SCRIPT = [
  "set -u",
  ...LEFTOVER_PATHS,
  'touch "${home}" "${task}" "${tmp}" 2>/dev/null',
  'mkdir -p "${HOME}/.ssh"',
  "python3 -c 'import socket, sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])' \"${socket}\" 2>/dev/null",
  'status write-home test -f "${home}"',
  'status write-task test -f "${task}"',
  'status write-tmp test -f "${tmp}"',
  'status write-socket test -S "${socket}"',
  "",
].join("\n");
const LEFTOVER_READ_SCRIPT = [
  "set -u",
  ...LEFTOVER_PATHS,
  "masters() {",
  '  find "${HOME}" "${task_dir}" /tmp -type s -name "cp-*" 2>/dev/null | grep -q .',
  "}",
  'status left-home test -e "${home}"',
  'status left-task test -e "${task}"',
  'status left-tmp test -e "${tmp}"',
  'status left-socket test -e "${socket}"',
  "status left-masters masters",
  "",
].join("\n");
const SSH_PORT = 22;
const UNLISTED_PUBLIC = "1.1.1.1:443";
const METADATA = "169.254.169.254:80";
const GATEWAY_PORTS = [22, 80, 443];
const HOST_KEY_ERROR = "Host key verification failed";
const AUTH_REFUSED = "Permission denied (publickey";
const KEY_LOADED = "deploy.sh: the SSH key of WORKSPACE_SSH_KEY is in the task agent";
const VAULT_NAME = /VAULT_PASSWORD/;
const VAULT_TRACES = ["DEPLOY_VAULT_PASSWORD", "--password-file", "--vault-password-file", "!vault"];
const CHANGED_STEP = /^changed: \[/;
const EGRESS_SCRIPT = [
  "set -u",
  "hex_ip() {",
  "  printf '%d.%d.%d.%d' \"0x${1:6:2}\" \"0x${1:4:2}\" \"0x${1:2:2}\" \"0x${1:0:2}\"",
  "}",
  "route=\"$(awk 'NR > 1 && $2 == \"00000000\" { print $3; exit }' /proc/net/route)\"",
  "subnet=\"$(awk 'NR > 1 && $2 != \"00000000\" { print $2; exit }' /proc/net/route)\"",
  'gateway="0.0.0.0"',
  'if [ -n "${route}" ]; then',
  '  gateway="$(hex_ip "${route}")"',
  "  printf 'PROBE gateway default\\n'",
  'elif [ -n "${subnet}" ]; then',
  '  network="$(hex_ip "${subnet}")"',
  '  gateway="${network%.*}.$(( ${network##*.} + 1 ))"',
  "  printf 'PROBE gateway subnet\\n'",
  "else",
  "  printf 'PROBE gateway none\\n'",
  "fi",
  'for entry in "$@"; do',
  '  via="${entry%%:*}"',
  '  rest="${entry#*:}"',
  '  check="${rest%%=*}"',
  '  target="${rest#*=}"',
  '  target="${target//GATEWAY/${gateway}}"',
  '  if [ "${via}" = proxy ]; then',
  "    code=\"$(curl -s -o /dev/null -w '%{http_connect}' --connect-timeout 10 --max-time 10 --proxy \"http://${EGRESS_PROXY:-unset}\" --proxytunnel \"telnet://${target}\" </dev/null 2>/dev/null)\"",
  "    expected=200",
  "  else",
  "    code=\"$(curl -s -o /dev/null -w '%{num_connects}' --connect-timeout 5 --max-time 5 --noproxy '*' \"telnet://${target}\" </dev/null 2>/dev/null)\"",
  "    expected=1",
  "  fi",
  '  if [ "${code}" = "${expected}" ]; then verdict=allowed; else verdict=refused; fi',
  "  printf 'PROBE egress %s-%s %s %s\\n' \"${via}\" \"${check}\" \"${verdict}\" \"${code:-000}\"",
  "done",
  "",
].join("\n");
const TWIN_FUNCTIONS = [
  "report() {",
  "  if \"${@:3}\"; then printf 'PROBE %s %s allowed 0\\n' \"$1\" \"$2\"; else printf 'PROBE %s %s refused 1\\n' \"$1\" \"$2\"; fi",
  "}",
  "readable() {",
  '  head -c 1 "$1" >/dev/null 2>&1',
  "}",
  "holds() {",
  '  grep -qxF "$1" <<<"$2"',
  "}",
  "ends_in() {",
  '  grep -qE "/$1\\$" <<<"$2"',
  "}",
  "in_project() {",
  '  [ "$(basename "$(dirname "${PWD}")")" = "project_$1" ]',
  "}",
  "environments() {",
  "  cat /proc/[0-9]*/environ 2>/dev/null | tr '\\0' '\\n'",
  "}",
  "salted() {",
  "  { printf '%s' \"$1\"; cat \"$2\" 2>/dev/null; } | sha256sum | cut -d ' ' -f 1",
  "}",
];
const ISOLATION_SCRIPT = [
  "set -u",
  'origin="$1" own_role="$2" other_role="$3" other_path="$4" other_state="$5" other_runner="$6"',
  'proxy=(--proxy "http://${EGRESS_PROXY:-unset}")',
  "tls=()",
  'if [ -n "${BAO_CACERT:-}" ]; then tls=(--cacert "${BAO_CACERT}"); fi',
  "verdict() {",
  "  if [ \"$2\" = \"$3\" ]; then printf 'PROBE isolation %s allowed %s\\n' \"$1\" \"$2\"; else printf 'PROBE isolation %s refused %s\\n' \"$1\" \"${2:-000}\"; fi",
  "}",
  "login() {",
  "  printf '{\"role\":\"%s\",\"jwt\":\"%s\"}' \"$1\" \"${SEMAPHORE_JWT}\" |",
  "    curl -s -w '\\n%{http_code}' \"${proxy[@]}\" \"${tls[@]}\" --max-time 20 -X POST --data-binary @- \"${origin}/v1/auth/jwt/login\" 2>/dev/null",
  "}",
  'own="$(login "${own_role}")"',
  "token=\"$(printf '%s' \"${own%$'\\n'*}\" | python3 -c 'import json, sys; print((json.load(sys.stdin).get(\"auth\") or {}).get(\"client_token\", \"\"))' 2>/dev/null)\"",
  "verdict login-own \"${own##*$'\\n'}\" 200",
  'other="$(login "${other_role}")"',
  "verdict login-other \"${other##*$'\\n'}\" 200",
  "code=\"$(curl -s -o /dev/null -w '%{http_code}' \"${proxy[@]}\" \"${tls[@]}\" --max-time 20 -H @- \"${origin}/v1/${other_path}\" <<<\"X-Vault-Token: ${token}\" 2>/dev/null)\"",
  'verdict read-other "${code}" 200',
  "code=\"$(curl -s -o /dev/null -w '%{http_code}' \"${proxy[@]}\" --max-time 20 \"${other_state}\" 2>/dev/null)\"",
  'verdict state-other "${code}" 200',
  "code=\"$(curl -s -o /dev/null -w '%{http_connect}' --connect-timeout 10 --max-time 10 \"${proxy[@]}\" --proxytunnel \"telnet://${other_runner}:80\" </dev/null 2>/dev/null)\"",
  'verdict runner-other-proxy "${code}" 200',
  "code=\"$(curl -s -o /dev/null -w '%{num_connects}' --connect-timeout 5 --max-time 5 --noproxy '*' \"telnet://${other_runner}:80\" </dev/null 2>/dev/null)\"",
  'verdict runner-other-direct "${code}" 1',
  "curl -s -o /dev/null \"${proxy[@]}\" \"${tls[@]}\" --max-time 20 -X POST -H @- \"${origin}/v1/auth/token/revoke-self\" <<<\"X-Vault-Token: ${token}\" 2>/dev/null || true",
  ...TWIN_FUNCTIONS,
  'token_file="$7" workspaces_dir="$8" own_project="$9" other_project="${10}" own_workspace="${11}" other_workspace="${12}" salt="${13}" other_digest="${14}"',
  'own_digest="$(salted "${salt}" "${token_file}")"',
  'found="$(python3 - "${salt}" "${own_digest}" "${other_digest}" 2>/dev/null <<\'PY\'',
  "import hashlib",
  "import os",
  "import stat",
  "import sys",
  "salt = sys.argv[1].encode()",
  "wanted = set(sys.argv[2:])",
  'skip = {"/proc", "/sys", "/dev"}',
  'for root, dirs, files in os.walk("/"):',
  "    dirs[:] = [name for name in dirs if os.path.join(root, name) not in skip]",
  "    for name in files:",
  "        path = os.path.join(root, name)",
  "        try:",
  "            info = os.lstat(path)",
  "            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 4096:",
  "                continue",
  '            with open(path, "rb") as handle:',
  "                digest = hashlib.sha256(salt + handle.read()).hexdigest()",
  "        except OSError:",
  "            continue",
  "        if digest in wanted:",
  "            print(digest)",
  "PY",
  ')"',
  'report isolation token-own readable "${token_file}"',
  'report isolation token-own-search holds "${own_digest}" "${found}"',
  'report isolation token-other-search holds "${other_digest}" "${found}"',
  'report isolation hostdir-own test -e "${workspaces_dir}/${own_role}"',
  'report isolation hostdir-other test -e "${workspaces_dir}/${other_role}"',
  "dirs=\"$(find / \\( -path /proc -o -path /sys -o -path /dev \\) -prune -o -type d -name 'project_*' -print 2>/dev/null)\"",
  'report isolation taskdir-own ends_in "project_${own_project}" "${dirs}"',
  'report isolation taskdir-other ends_in "project_${other_project}" "${dirs}"',
  'report isolation env-own holds "WORKSPACE=${own_workspace}" "$(environments)"',
  'report isolation env-other holds "WORKSPACE=${other_workspace}" "$(environments)"',
  "",
].join("\n");
const HOLDER_SCRIPT = [
  "set -u",
  ...TWIN_FUNCTIONS,
  'salt="$1" own_workspace="$2" own_project="$3" token_file="$4" hold="$5"',
  'report holder token-own readable "${token_file}"',
  "printf 'PROBE holder token-digest %s\\n' \"$(salted \"${salt}\" \"${token_file}\")\"",
  'report holder taskdir-own in_project "${own_project}"',
  'report holder env-own holds "WORKSPACE=${own_workspace}" "$(environments)"',
  "printf 'PROBE holder ready 0\\n'",
  'sleep "${hold}"',
  "",
].join("\n");
const HOLDER_OWN = ["token-own", "taskdir-own", "env-own"];
const PROBE_TEMPLATE = "probe";
const SALTED_DIGEST = /^[0-9a-f]{64}$/;
const ISOLATION_OWN = ["token-own", "token-own-search", "taskdir-own", "env-own"];
const ISOLATION_OTHER = [
  "login-other",
  "read-other",
  "state-other",
  "runner-other-proxy",
  "runner-other-direct",
  "token-other-search",
  "hostdir-own",
  "hostdir-other",
  "taskdir-other",
  "env-other",
];
const AGENT_LEFTOVER_SCRIPT = [
  "set -u",
  "found=\"$(find /tmp \"${HOME}\" \"$(dirname \"${PWD}\")\" \\( -name agent.sock -o -name known_hosts \\) 2>/dev/null | grep -c .)\"",
  "if [ \"${found}\" = 0 ]; then printf 'PROBE leftover-agent refused 0\\n'; else printf 'PROBE leftover-agent allowed %s\\n' \"${found}\"; fi",
  "",
].join("\n");
const SAFE_LINE =
  /^(?:failed|fatal: (?!\[)|(?:workspace|members|deploy|host|directory)\.sh: |semaphore_members\.py: |\{"workspace":"[0-9a-f-]+","refused":"[a-z_]+"\}$)/;

function firstLine(error) {
  return String(error && error.message).split("\n")[0];
}

/**
 * Args:
 *   body: async function receiving `cleanup(step)`; the steps run in reverse
 *     order after the body, also when it fails.
 *
 * Returns:
 *   What the body returned; a failed step fails the test unless the body
 *   already failed, then it is reported beside the body's failure.
 */
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
      problems.push(firstLine(error));
    }
  }
  if (outcome.error) {
    if (problems.length > 0) {
      console.warn(`${LABEL}: cleanup after the failure also failed: ${problems.join("; ")}`);
    }
    throw outcome.error;
  }
  if (problems.length > 0) {
    throw new Error(`${LABEL}: cleanup failed: ${problems.join("; ")}`);
  }
  return outcome.value;
}

/**
 * Args:
 *   run: a finished task from `awaitTask`.
 *
 * Returns:
 *   The refusal lines of the scripts and the failed Ansible steps, never the
 *   result body of a step, which may carry credentials.
 */
function safeLines(run) {
  const picked = [];
  run.lines.forEach((line, index) => {
    const trimmed = line.trim();
    const bare = trimmed.replace(/^- /, "").replace(/^["']|["']$/g, "");
    if (SAFE_LINE.test(bare)) {
      picked.push(bare);
      return;
    }
    if (/^fatal: \[/.test(trimmed)) {
      const banner = run.lines.slice(0, index).reverse().find((candidate) => BANNER.test(candidate.trim()));
      picked.push(`${banner ? banner.trim() : "TASK [unknown]"} ${trimmed.split("=>")[0].trim()}`);
    }
  });
  return picked.slice(-SAFE_LINES_MAX).join("\n") || "(none)";
}

function expectStatus(run, status) {
  expect(
    run.status,
    `${LABEL}: ${run.what} (task ${run.id}) must end ${status}, it ended ${run.status}; its refusals and failed steps:\n${safeLines(run)}`,
  ).toBe(status);
}

function lineIndex(run, needle) {
  return run.lines.findIndex((line) => line.includes(needle));
}

function expectLine(run, needle) {
  expect(
    lineIndex(run, needle),
    `${LABEL}: the output of ${run.what} (task ${run.id}) must hold "${needle}"; its refusals and failed steps:\n${safeLines(run)}`,
  ).toBeGreaterThan(-1);
}

function expectNoLine(run, needle) {
  expect(lineIndex(run, needle), `${LABEL}: the output of ${run.what} (task ${run.id}) must not hold "${needle}"`).toBe(-1);
}

function changeLines(run) {
  return run.lines.map((line) => line.trim()).filter((line) => CHANGE_LINE.test(line));
}

/**
 * Args:
 *   run: a finished task from `awaitTask`.
 *   fragment: a part of the task name, unique within the run.
 *
 * Returns:
 *   The result words (ok, changed, skipping, ...) the steps whose banner holds
 *   the fragment printed, in order.
 */
function stepStatuses(run, fragment) {
  const statuses = [];
  let inside = false;
  for (const line of run.lines) {
    const trimmed = line.trim();
    const banner = BANNER.exec(trimmed);
    if (banner) {
      inside = banner[1].includes(fragment);
      continue;
    }
    const result = STEP_RESULT.exec(trimmed);
    if (inside && result) {
      statuses.push(result[1]);
    }
  }
  return statuses;
}

function expectStep(run, fragment, allowed) {
  const statuses = stepStatuses(run, fragment);
  expect(
    statuses.length > 0 && statuses.every((status) => allowed.includes(status)),
    `${LABEL}: the step "${fragment}" of ${run.what} (task ${run.id}) must report ${allowed.join(" or ")}, it reported ${statuses.join(", ") || "nothing"}`,
  ).toBe(true);
}

function organizationSummary(run) {
  const found = run.lines.map((line) => SUMMARY.exec(line)).filter(Boolean);
  expect(
    found.map((match) => match[0]),
    `${LABEL}: ${run.what} (task ${run.id}) must print exactly one organization summary line`,
  ).toHaveLength(1);
  const [created, deleted, unchanged, gone] = found[0].slice(1).map(Number);
  return { created, deleted, unchanged, gone };
}

function resultOf(run) {
  const line = run.lines
    .map((candidate) => candidate.trim())
    .reverse()
    .find((candidate) => WORKSPACE_RESULT_LINE.test(candidate));
  expect(line, `${LABEL}: ${run.what} (task ${run.id}) must print its result line`).toBeTruthy();
  return JSON.parse(line);
}

/**
 * Args:
 *   line: an OpenSSH public key line without comment.
 *
 * Returns:
 *   Its type word, the count of further words, the fields of its wire form
 *   (the first as text, the others as byte lengths) and whether the base64
 *   body is canonical and fully consumed.
 */
function sshPublicShape(line) {
  const [type, body, ...rest] = line.split(" ");
  const bytes = Buffer.from(body || "", "base64");
  const fields = [];
  let offset = 0;
  while (offset + 4 <= bytes.length) {
    const length = bytes.readUInt32BE(offset);
    fields.push(bytes.subarray(offset + 4, offset + 4 + length));
    offset += 4 + length;
  }
  return {
    type,
    words: rest.length,
    fields: fields.map((field, index) => (index === 0 ? field.toString() : field.length)),
    canonical: bytes.toString("base64") === body && offset === bytes.length,
  };
}

function keycloakEnv() {
  return {
    baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL")),
    realm: requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME"),
    username: requireDotenvValue(process.env.SUPER_ADMIN_USERNAME, "SUPER_ADMIN_USERNAME"),
    password: requireDotenvValue(process.env.SUPER_ADMIN_PASSWORD, "SUPER_ADMIN_PASSWORD"),
    opts: {
      adminRealm: requireDotenvValue(process.env.KEYCLOAK_ADMIN_REALM, "KEYCLOAK_ADMIN_REALM"),
      adminClientId: requireDotenvValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID, "KEYCLOAK_ADMIN_CLI_CLIENT_ID"),
    },
  };
}

/**
 * Args:
 *   request: a Playwright request context.
 *   method: the HTTP method.
 *   path: the path below `/admin/realms/<realm>/`.
 *   data: the JSON body, undefined for none.
 *   statuses: the statuses the call may answer.
 *
 * Returns:
 *   `response` and its parsed `body`, null for an empty one.
 */
async function keycloak(request, method, path, data, statuses) {
  const kc = keycloakEnv();
  const token = await keycloakAdminToken(request, kc.baseUrl, kc.username, kc.password, kc.opts);
  let response;
  try {
    response = await apiFetchOnion(request, `${kc.baseUrl}/admin/realms/${encodeURIComponent(kc.realm)}/${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      data,
      failOnStatusCode: false,
      timeout: resolveTimeout(REQUEST_MS),
    });
  } catch (error) {
    // eslint-disable-next-line preserve-caught-error -- the call log of the cause lists the Authorization header
    throw new Error(`${LABEL}: Keycloak ${method} ${path} failed: ${firstLine(error)}`);
  }
  expect(statuses, `${LABEL}: Keycloak ${method} ${path} answered ${response.status()}`).toContain(response.status());
  const body = await response.text();
  return { response, body: body ? JSON.parse(body) : null };
}

async function markedOrganizations(request, workspace) {
  const query = new URLSearchParams({ q: `${MARKER}:${workspace}`, briefRepresentation: "false", first: "0", max: "10" });
  const { body } = await keycloak(request, "GET", `organizations?${query}`, undefined, [200]);
  return body.filter((organization) => organization.attributes?.[MARKER]?.includes(workspace));
}

async function soleOrganization(request, workspace) {
  const marked = await markedOrganizations(request, workspace);
  expect(
    marked.map((organization) => organization.alias),
    `${LABEL}: exactly the organization ws-${workspace} must carry the marker of ${workspace}`,
  ).toEqual([`ws-${workspace}`]);
  return marked[0];
}

async function expectNoOrganization(request, workspace) {
  expect(
    (await markedOrganizations(request, workspace)).map((organization) => organization.alias),
    `${LABEL}: no organization may carry the marker of ${workspace}`,
  ).toEqual([]);
}

async function plantTwin(request, workspace) {
  const alias = `ws-${workspace}-twin`;
  const { response } = await keycloak(
    request,
    "POST",
    "organizations",
    { name: alias, alias, enabled: true, attributes: { [MARKER]: [workspace] } },
    [201],
  );
  return response.headers().location.split("/").pop();
}

async function plantUnmarked(request, workspace) {
  const alias = `ws-${workspace}`;
  const { response } = await keycloak(request, "POST", "organizations", { name: alias, alias, enabled: true }, [201]);
  return response.headers().location.split("/").pop();
}

/**
 * Args:
 *   moment: an RFC 3339 time.
 *   run: a finished task from `awaitTask`.
 *   offsetMs: how long after the task the moment has to lie.
 *   what: how the message names the moment.
 */
function expectAfterRun(moment, run, offsetMs, what) {
  const at = Date.parse(moment);
  const earliest = Date.parse(run.task.start || run.task.created) + offsetMs - CLOCK_SKEW_MS;
  const latest = Date.parse(run.task.end) + offsetMs + CLOCK_SKEW_MS;
  expect(
    at >= earliest && at <= latest,
    `${LABEL}: ${what} (${moment}) must lie ${offsetMs / DAY_MS} days after ${run.what} (task ${run.id})`,
  ).toBe(true);
}

function expectStoreEntry(entry, run, what) {
  expect(Object.keys(entry || {}).sort(), `${LABEL}: ${what} must hold exactly token and expires_at`).toEqual(ENTRY_FIELDS);
  expect(RFC3339_OFFSET.test(entry.expires_at), `${LABEL}: the expires_at of ${what} must be RFC 3339 with a numeric offset`).toBe(
    true,
  );
  expectAfterRun(entry.expires_at, run, REVOKE_AFTER_MS, `the expires_at of ${what}`);
}

function withinRun(moment, run) {
  const at = Date.parse(moment);
  return (
    at >= Date.parse(run.task.start || run.task.created) - CLOCK_SKEW_MS && at <= Date.parse(run.task.end) + CLOCK_SKEW_MS
  );
}

async function deleteOrganization(request, organizationId) {
  await keycloak(request, "DELETE", `organizations/${organizationId}`, undefined, [204, 404]);
}

async function organizationGroups(request, organizationId) {
  const query = new URLSearchParams({ briefRepresentation: "false", first: "0", max: "100" });
  const { body } = await keycloak(request, "GET", `organizations/${organizationId}/groups?${query}`, undefined, [200]);
  return Object.fromEntries(body.map((group) => [group.name, group.id]));
}

async function organizationMemberIds(request, organizationId) {
  const query = new URLSearchParams({ first: "0", max: "100" });
  const { body } = await keycloak(request, "GET", `organizations/${organizationId}/members?${query}`, undefined, [200]);
  return body.map((member) => member.id);
}

async function placeInOrganization(request, organizationId, groupId, userId) {
  await keycloak(request, "POST", `organizations/${organizationId}/members`, JSON.stringify(userId), [201]);
  await keycloak(request, "PUT", `organizations/${organizationId}/groups/${groupId}/members/${userId}`, undefined, [204]);
}

function privateTargetAddress() {
  return targetAddressIn(
    decodeDotenvJsonList(process.env.SEMAPHORE_WORKSPACES_PRIVATE_TARGETS_JSON, "SEMAPHORE_WORKSPACES_PRIVATE_TARGETS_JSON"),
    LABEL,
  );
}

/**
 * Args:
 *   line: the rest of a `PROBE <kind> <check> <verdict> <code>` line.
 *
 * Returns:
 *   `[check, "<verdict> <code>"]`.
 */
function splitVerdict(line) {
  const [check, ...verdict] = line.split(" ");
  return [check, verdict.join(" ")];
}

function hostPort(address, port) {
  return address.includes(":") ? `[${address}]:${port}` : `${address}:${port}`;
}

function hostSurvey(template, probe) {
  const host = { HOST: probe.host, HOST_KEY: probe.hostKey };
  const surveys = {
    deploy: { ...DEPLOY_ORDER, ...host, ROLES: probe.role, INVENTORY_COMMIT: probe.commit },
    update: { ...host, INVENTORY_COMMIT: probe.commit },
    backup: { ...host, INVENTORY_COMMIT: probe.commit },
    restart: host,
  };
  return surveys[template];
}

exports.register = function (shared) {
  const signIn = (page) =>
    shared.signInViaBreakglassApi(page, shared.env.breakglassUsername, shared.env.breakglassPassword, LABEL);

  /**
   * Args:
   *   fixture: the result of `withWorkspace`.
   *   name: deploy, update, backup or restart.
   *   probe: `host`, `hostKey`, `role` and `commit` of `hostSurvey`.
   *   what: the run the failure messages name.
   *
   * Returns:
   *   The output lines of the task, which has to end in error.
   */
  async function hostRun(fixture, name, probe, what) {
    const identity = fixture.result.templates[name];
    expect(identity, `${what}: apply must return the template ${name}`).toBeTruthy();
    const run = await runTemplate(
      shared,
      fixture.page,
      identity.project_id,
      identity.template_id,
      hostSurvey(name, probe),
      PROBE_TASK_MS,
      what,
    );
    expect(run.task.status, `${what}: task ${run.task.id} must end in error`).toBe("error");
    return run.lines;
  }

  /**
   * Args:
   *   fixture: the result of `withWorkspace`.
   *   entries: `<proxy|direct>:<check>=<host>:<port>`, `GATEWAY` standing for the runner's gateway.
   *
   * Returns:
   *   `{<via>-<check>: "<allowed|refused> <code>"}` the egress probe of the workspace printed.
   */
  async function egressVerdicts(fixture, entries) {
    const what = `${LABEL}: the egress probe of ws-${fixture.workspace}`;
    const run = await runProbe(shared, fixture, fixture.result.project_id, EGRESS_SCRIPT, entries, what);
    expectSucceeded(run, what);
    const [gateway] = probeLines(run, "gateway");
    expect(["default", "subnet"], `${what}: the probe must find the runner's gateway, it found ${gateway}`).toContain(gateway);
    return Object.fromEntries(probeLines(run, "egress").map(splitVerdict));
  }

  async function projectIdsNamed(page, name) {
    return (await shared.api(page, "GET", "/projects")).filter((project) => project.name === name).map((project) => project.id);
  }

  async function soleProjectId(page, name) {
    const ids = await projectIdsNamed(page, name);
    expect(ids, `${LABEL}: exactly one Semaphore project must be named "${name}"`).toHaveLength(1);
    return ids[0];
  }

  async function templateIdNamed(page, projectId, name) {
    const ids = (await shared.api(page, "GET", `/project/${projectId}/templates`))
      .filter((template) => template.name === name)
      .map((template) => template.id);
    expect(ids, `${LABEL}: project ${projectId} must hold exactly one template "${name}"`).toHaveLength(1);
    return ids[0];
  }

  async function operations(page) {
    const projectId = await soleProjectId(
      page,
      requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_PROJECT_NAME, "SEMAPHORE_WORKSPACES_PROJECT_NAME"),
    );
    return {
      projectId,
      workspace: await templateIdNamed(page, projectId, "workspace"),
      members: await templateIdNamed(page, projectId, "members"),
      user: await templateIdNamed(page, projectId, "user"),
      rotation: await templateIdNamed(page, projectId, ROTATION_TEMPLATE),
    };
  }

  async function startTask(page, projectId, templateId, survey, extra) {
    const task = await shared.api(page, "POST", `/project/${projectId}/tasks`, {
      template_id: templateId,
      environment: JSON.stringify(survey),
      ...extra,
    });
    return task.id;
  }

  /**
   * Args:
   *   page: a page carrying the administrator session.
   *   projectId: the project of the task.
   *   taskId: the task.
   *   runMs: the longest the task may run, before timeout scaling.
   *   what: how the messages name the task.
   *
   * Returns:
   *   `id`, `what`, `status`, the final `task` and its output `lines` without
   *   colour codes; a task that does not finish in time is stopped.
   */
  async function awaitTask(page, projectId, taskId, runMs, what) {
    let task;
    try {
      await expect
        .poll(
          async () => {
            task = await shared.api(page, "GET", `/project/${projectId}/tasks/${taskId}`);
            return TASK_FINISHED.has(task.status);
          },
          { timeout: resolveTimeout(runMs), intervals: [5_000], message: `${LABEL}: ${what} (task ${taskId}) must finish` },
        )
        .toBe(true);
    } catch (error) {
      await shared
        .stopUnfinishedTask(page, projectId, taskId)
        .catch((stop) => console.warn(`${LABEL}: stopping ${what} (task ${taskId}) failed: ${firstLine(stop)}`));
      throw error;
    }
    const output = await shared.api(page, "GET", `/project/${projectId}/tasks/${taskId}/output`);
    return {
      id: taskId,
      what,
      task,
      status: task.status,
      lines: output.map((entry) => entry.output.replace(ANSI, "").trimEnd()),
    };
  }

  async function runTask(page, projectId, templateId, survey, extra, runMs, what) {
    return awaitTask(page, projectId, await startTask(page, projectId, templateId, survey, extra), runMs, what);
  }

  /**
   * Args:
   *   fixture: the result of `withWorkspace` whose runner holds the task.
   *   args: the positional arguments of `HOLDER_SCRIPT`.
   *   cleanup: the `cleanup` of that `withWorkspace`, which stops the task.
   *   what: the run the failure messages name.
   *
   * Returns:
   *   `held`, `{<check>: "<verdict> <code>"}` the holder printed before it
   *   started to wait, and the `taskId` that keeps waiting.
   */
  async function holdInWorkspace(fixture, args, cleanup, what) {
    const projectId = fixture.result.project_id;
    const template = await namedTemplate(shared, fixture.page, projectId, PROBE_TEMPLATE);
    const survey = { PROBE_SCRIPT: HOLDER_SCRIPT, PROBE_ARGS: args.join(" ") };
    const taskId = await startTask(fixture.page, projectId, template.id, survey, {});
    cleanup(async () => {
      await shared.stopUnfinishedTask(fixture.page, projectId, taskId);
      await awaitTask(fixture.page, projectId, taskId, PROBE_TASK_MS, what);
    });
    let held = {};
    await expect
      .poll(
        async () => {
          const task = await shared.api(fixture.page, "GET", `/project/${projectId}/tasks/${taskId}`);
          const output = await shared.api(fixture.page, "GET", `/project/${projectId}/tasks/${taskId}/output`);
          held = Object.fromEntries(probeLines({ lines: output.map((entry) => entry.output) }, "holder").map(splitVerdict));
          return TASK_FINISHED.has(task.status) || held.ready === "0";
        },
        {
          timeout: resolveTimeout(TASK_START_MS + PROBE_TASK_MS),
          intervals: [5_000],
          message: `${what} (task ${taskId}) must start to hold`,
        },
      )
      .toBe(true);
    expect(held.ready, `${what}: task ${taskId} ended before it held`).toBe("0");
    return { held, taskId };
  }

  function applySurvey(workspace, version, targets) {
    skipWithoutPlatformHost();
    return {
      WORKSPACE: workspace,
      WORKSPACE_ACTION: "apply",
      WORKSPACE_CORE_VERSION: version,
      WORKSPACE_TARGETS: targets,
      WORKSPACE_PLATFORM_TOKENS: "false",
    };
  }

  function applyRun(page, ops, workspace, version, targets) {
    return runTask(
      page,
      ops.projectId,
      ops.workspace,
      applySurvey(workspace, version, targets),
      {},
      WORKSPACE_TASK_MS,
      `workspace apply of ${workspace}`,
    );
  }

  function destroyRun(page, ops, workspace) {
    return runTask(
      page,
      ops.projectId,
      ops.workspace,
      { WORKSPACE: workspace, WORKSPACE_ACTION: "destroy" },
      {},
      WORKSPACE_TASK_MS,
      `workspace destroy of ${workspace}`,
    );
  }

  function membersRun(page, ops, workspace, action, fields) {
    return runTask(
      page,
      ops.projectId,
      ops.members,
      { WORKSPACE: workspace, MEMBERS_ACTION: action, WORKSPACE_SUSPENDED: "false", ...fields },
      {},
      MEMBERS_TASK_MS,
      `members ${action} of ${workspace}`,
    );
  }

  async function membersOk(page, ops, workspace, action, fields) {
    const run = await membersRun(page, ops, workspace, action, fields);
    expectStatus(run, "success");
    return run;
  }

  async function applied(page, ops, workspace, version, targets) {
    const run = await applyRun(page, ops, workspace, version, targets);
    expectStatus(run, "success");
    const result = resultOf(run);
    expect(result.workspace, `${LABEL}: ${run.what} must report its own workspace`).toBe(workspace);
    return { run, result };
  }

  async function destroyed(page, ops, workspace, done) {
    const run = await destroyRun(page, ops, workspace);
    expectStatus(run, "success");
    const result = resultOf(run);
    expect(
      { ...result, stopped_tasks: Number.isInteger(result.stopped_tasks) && result.stopped_tasks >= 0 },
      `${LABEL}: ${run.what} must end with its destroy line and a count of stopped tasks`,
    ).toEqual({ destroyed: true, stopped_tasks: true, workspace });
    done.add(workspace);
    return run;
  }

  /**
   * Args:
   *   page: a page carrying the administrator session.
   *   ops: the Workspaces project and its templates from `operations`.
   *   count: how many fresh workspace ids the body gets.
   *   body: async function receiving `workspaces`, `done` (the ids the body
   *     destroyed itself) and `cleanup`; every other id is destroyed after it.
   */
  async function withWorkspaces(page, ops, count, body) {
    const workspaces = Array.from({ length: count }, () => crypto.randomUUID());
    const done = new Set();
    return withCleanup(async (cleanup) => {
      for (const workspace of workspaces) {
        cleanup(async () => {
          if (done.has(workspace)) {
            return;
          }
          const run = await destroyRun(page, ops, workspace);
          if (run.status !== "success") {
            throw new Error(`destroy of ${workspace} ended ${run.status}: ${safeLines(run)}`);
          }
        });
      }
      return body({ workspaces, done, cleanup });
    });
  }

  async function runnersNamed(page, name) {
    return (await shared.api(page, "GET", "/runners")).filter((runner) => runner.name === name);
  }

  async function awaitRunnerOnline(page, alias) {
    let rows = [];
    await expect
      .poll(
        async () => {
          rows = await runnersNamed(page, alias);
          return rows.map((row) => row.status).join(",");
        },
        {
          timeout: resolveTimeout(RUNNER_ONLINE_MS),
          intervals: [5_000],
          message: `${LABEL}: exactly one runner named ${alias} must report online`,
        },
      )
      .toBe("online");
    return rows[0];
  }

  async function expectNoRunner(page, alias) {
    expect(
      (await runnersNamed(page, alias)).map((runner) => runner.id),
      `${LABEL}: no runner row named ${alias} may remain`,
    ).toHaveLength(0);
  }

  async function semaphoreUsersNamed(page, username) {
    return (await shared.api(page, "GET", "/users")).filter((user) => user.username === username);
  }

  async function soleSemaphoreUser(page, username) {
    const named = await semaphoreUsersNamed(page, username);
    expect(
      named.map((user) => user.id),
      `${LABEL}: Semaphore must hold exactly one user named ${username}`,
    ).toHaveLength(1);
    return named[0];
  }

  async function deleteSemaphoreUsers(page, username) {
    for (const user of await semaphoreUsersNamed(page, username)) {
      const response = await shared.apiResponse(page, "DELETE", `/users/${user.id}`);
      expect([204, 404], `${LABEL}: deleting the Semaphore user ${username} answered ${response.status()}`).toContain(
        response.status(),
      );
    }
  }

  async function identitiesOf(page, userId) {
    return shared.api(page, "GET", `/users/${userId}/identities`);
  }

  /**
   * Args:
   *   page: a page carrying the administrator session.
   *   projectId: a workspace project.
   *
   * Returns:
   *   `{username: roles}` of every project member that is neither a Semaphore
   *   admin nor the store's account.
   */
  async function memberRoles(page, projectId) {
    const store = requireDotenvValue(process.env.SEMAPHORE_STORE_USERNAME, "SEMAPHORE_STORE_USERNAME");
    const admins = new Set((await shared.api(page, "GET", "/users")).filter((user) => user.admin).map((user) => user.username));
    const members = await shared.api(page, "GET", `/project/${projectId}/users`);
    return Object.fromEntries(
      members
        .filter((member) => !admins.has(member.username) && member.username !== store)
        .map((member) => [member.username, [...member.roles].sort().join(",")]),
    );
  }

  async function createMember(page, tag, cleanup) {
    const kc = keycloakEnv();
    const username = `pw-ws-${tag}-${crypto.randomBytes(4).toString("hex")}`;
    const member = { username, password: `${crypto.randomBytes(18).toString("base64url")}Aa1!` };
    member.id = await keycloakAdminCreateUser(
      page.request,
      kc.baseUrl,
      kc.realm,
      { username, email: `${username}@example.invalid`, firstName: "Playwright", lastName: tag, password: member.password },
      kc.username,
      kc.password,
      kc.opts,
    );
    cleanup(async () => {
      await deleteSemaphoreUsers(page, username);
      await keycloakAdminDeleteUser(page.request, kc.baseUrl, kc.realm, member.id, kc.username, kc.password, kc.opts);
    });
    return member;
  }

  async function allowLogin(page, member) {
    const kc = keycloakEnv();
    const added = await keycloakAdminAddUserToGroup(
      page.request,
      kc.baseUrl,
      kc.realm,
      shared.env.userGroupPath,
      member.username,
      kc.username,
      kc.password,
      kc.opts,
    );
    expect(added, `${LABEL}: ${member.username} must join ${shared.env.userGroupPath} to sign in to Semaphore`).toBe(true);
  }

  async function denyLogin(page, member) {
    const kc = keycloakEnv();
    await keycloakRemoveUserFromGroupViaRest(
      page.request,
      kc.baseUrl,
      kc.realm,
      kc.username,
      kc.password,
      shared.env.userGroupPath,
      member.username,
      kc.opts,
    );
  }

  async function memberSignIn(browser, member, cleanup) {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    cleanup(() => context.close());
    const memberPage = await context.newPage();
    await shared.beforeEach({ page: memberPage });
    await shared.signInViaOidc(memberPage, member.username, member.password, `${LABEL} ${member.username}`);
    return memberPage;
  }

  /**
   * Args:
   *   request: a Playwright request context without a Semaphore session.
   *   token: a Semaphore API token.
   *   method: the HTTP method.
   *   path: the path below `/api`.
   *   data: the JSON body, undefined for none.
   *
   * Returns:
   *   The response, whatever its status.
   */
  async function withToken(request, token, method, path, data) {
    try {
      return await apiFetchOnion(request, `${shared.env.semaphoreBaseUrl}/api${path}`, {
        method,
        headers: { Authorization: `Bearer ${token}` },
        data,
        failOnStatusCode: false,
        timeout: resolveTimeout(REQUEST_MS),
      });
    } catch (error) {
      // eslint-disable-next-line preserve-caught-error -- the call log of the cause lists the Authorization header
      throw new Error(`${LABEL}: ${method} /api${path} with an API token failed: ${firstLine(error)}`);
    }
  }

  function runnersWithToken(request, token) {
    return withToken(request, token, "GET", "/runners");
  }

  async function storeEntries(context) {
    const token = await storeVaultToken(context);
    return {
      semaphore: await vaultRead(context, token, PLATFORM_MOUNT, STORE_SEMAPHORE_PATH),
      gitea: await vaultRead(context, token, PLATFORM_MOUNT, STORE_GITEA_PATH),
    };
  }

  async function storeSemaphoreToken(context) {
    const { semaphore } = await storeEntries(context);
    expect(
      Boolean(semaphore && semaphore.token),
      `${LABEL}: OpenBao must hold the store's Semaphore token at ${PLATFORM_MOUNT}/${STORE_SEMAPHORE_PATH}`,
    ).toBe(true);
    return semaphore.token;
  }

  async function giteaWithToken(request, token, method, route) {
    const baseUrl = normalizeBaseUrl(
      requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_GITEA_URL, "SEMAPHORE_WORKSPACES_GITEA_URL"),
    );
    try {
      return await apiFetchOnion(request, `${baseUrl}/api/v1${route}`, {
        method,
        headers: { Authorization: `token ${token}` },
        failOnStatusCode: false,
        timeout: resolveTimeout(REQUEST_MS),
      });
    } catch (error) {
      // eslint-disable-next-line preserve-caught-error -- the call log of the cause lists the Authorization header
      throw new Error(`${LABEL}: Gitea ${method} ${route} with a token failed: ${firstLine(error)}`);
    }
  }

  /**
   * Args:
   *   request: a Playwright request context.
   *   method: the HTTP method.
   *   route: the path below `/api/v1`.
   *   data: the JSON body, undefined for none.
   *   statuses: the statuses the call may answer.
   *
   * Returns:
   *   The parsed body of Gitea's answer as the platform administrator, null
   *   for an empty one.
   */
  async function gitea(request, method, route, data, statuses) {
    const baseUrl = normalizeBaseUrl(
      requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_GITEA_URL, "SEMAPHORE_WORKSPACES_GITEA_URL"),
    );
    const authorization = `Basic ${Buffer.from(`${shared.env.adminUsername}:${shared.env.adminPassword}`).toString("base64")}`;
    let response;
    try {
      response = await apiFetchOnion(request, `${baseUrl}/api/v1${route}`, {
        method,
        headers: { Authorization: authorization, "Content-Type": "application/json" },
        data,
        failOnStatusCode: false,
        timeout: resolveTimeout(REQUEST_MS),
      });
    } catch (error) {
      // eslint-disable-next-line preserve-caught-error -- the call log of the cause lists the Authorization header
      throw new Error(`${LABEL}: Gitea ${method} ${route} failed: ${firstLine(error)}`);
    }
    expect(statuses, `${LABEL}: Gitea ${method} ${route} answered ${response.status()}`).toContain(response.status());
    const body = await response.text();
    return body ? JSON.parse(body) : null;
  }

  async function commitFile(request, repository, file, branches) {
    const body = await gitea(
      request,
      "POST",
      `/repos/${repository}/contents/${file}`,
      { content: Buffer.from(`${file}\n`).toString("base64"), message: `playwright ${file}`, ...branches },
      [201],
    );
    return body.commit.sha;
  }

  test.describe("workspace runners", () => {
    test.describe.configure({ retries: 0 });

    test("runners: no global runner exists", async ({ page, browser }) => {
      test.setTimeout(resolveTimeout(2 * SIGN_IN_MS + 8 * REQUEST_MS));
      await signIn(page);
      const minted = await shared.api(page, "POST", "/user/tokens", {
        name: `playwright-runners-${crypto.randomBytes(4).toString("hex")}`,
        expires_at: new Date(Date.now() + TOKEN_LIFETIME_MS).toISOString(),
      });
      const bearer = await browser.newContext({ ignoreHTTPSErrors: true });
      await withCleanup(async (cleanup) => {
        cleanup(() => bearer.close());
        cleanup(async () => {
          const removed = await shared.apiResponse(page, "DELETE", `/user/tokens/${minted.id.slice(0, TOKEN_PREFIX_LENGTH)}`);
          expect(removed.status(), `${LABEL}: deleting the minted API token must answer 204`).toBe(204);
          expect(
            (await runnersWithToken(bearer.request, minted.id)).status(),
            `${LABEL}: the deleted API token must no longer authenticate`,
          ).toBe(401);
        });
        const response = await runnersWithToken(bearer.request, minted.id);
        expect(response.status(), `${LABEL}: GET /api/runners with an admin API token must answer 200`).toBe(200);
        const unowned = (await response.json()).filter((runner) => runner.project_id === null).map((runner) => runner.name);
        expect(unowned, `${LABEL}: GET /api/runners must list no runner without a project`).toEqual([]);
      });
      await shared.logout(page, LABEL);
    });

    test("runners: each platform project runs on its own runner", async ({ page }) => {
      test.setTimeout(resolveTimeout(BASE_MS + TASK_START_MS + APP_CONTROL_TASK_MS));
      await signIn(page);
      const runners = await shared.api(page, "GET", "/runners");
      const runnerOf = (projectId, what) => {
        const owned = runners.filter((runner) => runner.project_id === projectId);
        expect(
          owned.map((runner) => runner.name),
          `${LABEL}: ${what} must have exactly one runner`,
        ).toHaveLength(1);
        return owned[0];
      };
      const appControlId = await soleProjectId(page, shared.env.projectName);
      const appControlRunner = runnerOf(appControlId, `the app-control project "${shared.env.projectName}"`);
      const deployRunners = [];
      if (strictFlag(process.env.SEMAPHORE_DEPLOY_ENABLED, "SEMAPHORE_DEPLOY_ENABLED")) {
        const deployName = requireDotenvValue(process.env.SEMAPHORE_DEPLOY_PROJECT_NAME, "SEMAPHORE_DEPLOY_PROJECT_NAME");
        deployRunners.push(runnerOf(await soleProjectId(page, deployName), `the deploy project "${deployName}"`).name);
      }
      const { start } = await shared.appControlTemplates(page, appControlId, shared.env.appControlTargetId);
      const taskId = await startTask(page, appControlId, start.id, {}, {});
      let used;
      try {
        await expect
          .poll(
            async () => {
              const listed = await shared.api(page, "GET", `/project/${appControlId}/tasks/last?count=20`);
              const entry = listed.find((candidate) => candidate.id === taskId);
              used = entry?.used_runner_name;
              if (used) {
                return "assigned";
              }
              return entry && TASK_FINISHED.has(entry.status) ? "finished" : "pending";
            },
            {
              timeout: resolveTimeout(TASK_START_MS),
              intervals: [500],
              message: `${LABEL}: the task API must report the runner of task ${taskId} while it runs`,
            },
          )
          .not.toBe("pending");
      } finally {
        await shared.awaitTaskSuccess(page, appControlId, taskId, APP_CONTROL_TASK_MS, LABEL);
      }
      expect(used, `${LABEL}: task ${taskId} must run on the app-control runner ${appControlRunner.name}`).toBe(
        appControlRunner.name,
      );
      expect(deployRunners, `${LABEL}: task ${taskId} of the app-control project must not run on the deploy runner`).not.toContain(
        used,
      );
      await shared.logout(page, LABEL);
    });

    test("workspace: apply creates project, runner row and runner", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace] }) => {
        const alias = `ws-${workspace}`;
        const { run, result } = await applied(page, ops, workspace, pickedCore(), "");
        expect(result.alias, `${LABEL}: ${run.what} must name the alias ${alias}`).toBe(alias);
        expect(await projectIdsNamed(page, alias), `${LABEL}: exactly the project ${alias} the result names must exist`).toEqual([
          result.project_id,
        ]);
        expect((await soleOrganization(page.request, workspace)).name, `${LABEL}: the organization must be named ${alias}`).toBe(alias);
        const row = await awaitRunnerOnline(page, alias);
        expect(
          { project_id: row.project_id, tags: row.tags, max_parallel_tasks: row.max_parallel_tasks, is_default: row.is_default },
          `${LABEL}: the runner row ${alias} must belong to its project, carry only its tag, take one task and not be a default`,
        ).toEqual({ project_id: result.project_id, tags: [alias], max_parallel_tasks: 1, is_default: false });
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: a second apply changes nothing", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + RUNNER_ONLINE_MS + 3 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace] }) => {
        const alias = `ws-${workspace}`;
        const first = await applied(page, ops, workspace, pickedCore(), "");
        const before = await awaitRunnerOnline(page, alias);
        const second = await applied(page, ops, workspace, pickedCore(), "");
        expect(second.result, `${LABEL}: the second apply must report the result of the first`).toEqual(first.result);
        const after = await awaitRunnerOnline(page, alias);
        expect(after, `${LABEL}: the second apply must keep the runner row of ${alias}`).toMatchObject({
          id: before.id,
          project_id: before.project_id,
          tags: before.tags,
          max_parallel_tasks: before.max_parallel_tasks,
          is_default: before.is_default,
        });
        expectStep(second.run, `Create the runner token of ${alias} once`, ["skipping"]);
        expectStep(second.run, `Align the runner row of ${alias}`, ["ok"]);
        expectStep(second.run, `Apply ${alias} projects`, ["ok"]);
        expectStep(second.run, `Bring up the runner and egress of ${alias}`, ["ok"]);
        expect(
          organizationSummary(second.run),
          `${LABEL}: the second apply must create and delete nothing in Keycloak`,
        ).toMatchObject({ created: 0, deleted: 0 });
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: destroy leaves nothing of the runner", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], done }) => {
        const alias = `ws-${workspace}`;
        await applied(page, ops, workspace, pickedCore(), "");
        await awaitRunnerOnline(page, alias);
        const run = await destroyed(page, ops, workspace, done);
        expectStep(run, `Align the runner row of ${alias}`, ["changed"]);
        expectStep(run, `Stop the runner and egress of ${alias}`, ["changed"]);
        expectStep(run, `Remove the runner images of ${alias}`, ["changed"]);
        expectStep(run, `Remove the compose project directory of ${alias}`, ["changed"]);
        await expectNoRunner(page, alias);
        expect(await projectIdsNamed(page, alias), `${LABEL}: the project ${alias} must be gone`).toEqual([]);
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: a stopped destroy finishes when run again", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 4 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], done, cleanup }) => {
        const alias = `ws-${workspace}`;
        await applied(page, ops, workspace, pickedCore(), "");
        await awaitRunnerOnline(page, alias);
        const twin = await plantTwin(page.request, workspace);
        cleanup(() => deleteOrganization(page.request, twin));
        const stopped = await destroyRun(page, ops, workspace);
        expectStatus(stopped, "error");
        expectLine(stopped, `organizations carry the marker of ${workspace}`);
        expectStep(stopped, `Align the runner row of ${alias}`, ["changed"]);
        expectStep(stopped, `Stop the runner and egress of ${alias}`, ["changed"]);
        await expectNoRunner(page, alias);
        expect(
          (await markedOrganizations(page.request, workspace)).map((organization) => organization.alias),
          `${LABEL}: the stopped destroy must leave the organization ${alias}`,
        ).toContain(alias);
        await deleteOrganization(page.request, twin);
        const finished = await destroyed(page, ops, workspace, done);
        expectLine(finished, `deleted organization ${alias}`);
        const third = await destroyed(page, ops, workspace, done);
        expectLine(third, `gone organization ${alias}`);
        expectStep(third, `Align the runner row of ${alias}`, ["ok"]);
        expectStep(third, `Stop the runner and egress of ${alias}`, ["skipping"]);
        expectStep(third, `Remove the runner images of ${alias}`, ["ok"]);
        expectStep(third, `Remove the compose project directory of ${alias}`, ["ok"]);
        expect(organizationSummary(third), `${LABEL}: the third destroy must create and delete nothing in Keycloak`).toMatchObject({
          created: 0,
          deleted: 0,
        });
      });
      await shared.logout(page, LABEL);
    });

    test("workspace runner: each workspace runs its selected core version", async ({ browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * RUNNER_ONLINE_MS + 6 * WORKSPACE_TASK_MS));
      const picks = corePicks();
      expect(
        new Set(picks.map(([version]) => version)).size,
        `${LABEL}: the specs pick the own build or two distinct releases at or above the floor`,
      ).toBe(picks.length);
      const selected = [picks[0], picks[picks.length - 1]];
      await withWorkspace(shared, browser, LABEL, "", async (first) => {
        await withWorkspace(shared, browser, LABEL, "", async (second) => {
          const runnerIds = [];
          for (const [index, fixture] of [first, second].entries()) {
            const [version, declares] = selected[index];
            const ops = await operations(fixture.page);
            const { run, result } = await applied(fixture.page, ops, fixture.workspace, version, "");
            expectStep(run, `Assert the runner of ${result.alias} runs core ${declares}`, ["ok"]);
            const row = await awaitRunnerOnline(fixture.page, result.alias);
            expect(
              { project_id: row.project_id, tags: row.tags },
              `${LABEL}: the workspace on core ${version} must run on its own runner ${result.alias}`,
            ).toEqual({ project_id: result.project_id, tags: [result.alias] });
            runnerIds.push(row.id);
          }
          expect(new Set(runnerIds).size, `${LABEL}: the two workspaces must run on two runners`).toBe(2);
        });
      });
    });

    test("workspace runner: a task finds nothing the previous task wrote", async ({ browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + 2 * PROBE_TASK_MS));
      await withWorkspace(shared, browser, LABEL, "", async (fixture) => {
        const nonce = crypto.randomBytes(8).toString("hex");
        const project = fixture.result.project_id;
        const first = `${LABEL}: the first probe task`;
        const written = await runProbe(shared, fixture, project, LEFTOVER_WRITE_SCRIPT, [nonce], first);
        expectSucceeded(written, first);
        expect(
          Object.fromEntries(LEFTOVER_PLACES.map((place) => [place, probeLines(written, `write-${place}`)])),
          `${LABEL}: the first probe task must leave its mark under HOME, the task directory and /tmp, and a master socket under HOME`,
        ).toEqual(Object.fromEntries(LEFTOVER_PLACES.map((place) => [place, ["allowed 0"]])));
        const second = `${LABEL}: the second probe task`;
        const found = await runProbe(shared, fixture, project, LEFTOVER_READ_SCRIPT, [nonce], second);
        expectSucceeded(found, second);
        for (const place of [...LEFTOVER_PLACES, "masters"]) {
          expect(
            probeLines(found, `left-${place}`),
            `${LABEL}: the second probe task of ws-${fixture.workspace} must find nothing of the first in ${place}`,
          ).toEqual(["refused 1"]);
        }
      });
    });

    test("workspace runner: an unpinned host key stops every host template", async ({ browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + HOST_TEMPLATES.length * PROBE_TASK_MS));
      const { address } = await sharedTargetAddress();
      await withWorkspace(shared, browser, LABEL, `${address}:${SSH_PORT}`, async (fixture) => {
        const reference = await stageWorkspaceKey(fixture, await fixtureWorkspaceKey(fixture.context));
        const role = requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_PROBE_ROLE, "SEMAPHORE_WORKSPACE_PROBE_ROLE");
        const commit = await commitInventory(fixture, address, [role], {}, reference, LABEL);
        const probe = { host: address, hostKey: sshEd25519PublicLine(), role, commit };
        for (const name of HOST_TEMPLATES) {
          const what = `${LABEL}: ${name} of ws-${fixture.workspace} against ${address} with a host key the target does not hold`;
          const lines = (await hostRun(fixture, name, probe, what)).map(bare);
          expect(lines.some((line) => line.includes(HOST_KEY_ERROR)), `${what}: must stop at "${HOST_KEY_ERROR}"`).toBe(true);
          expect(lines.filter((line) => CHANGED_STEP.test(line)), `${what}: must change nothing on the host`).toEqual([]);
        }
      });
    });

    test("workspace egress: only the listed targets answer", async ({ browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + PROBE_TASK_MS));
      const { address } = await sharedTargetAddress();
      const listed = `${address}:${SSH_PORT}`;
      await withWorkspace(shared, browser, LABEL, listed, async (fixture) => {
        const verdicts = await egressVerdicts(fixture, [`proxy:listed=${listed}`, `proxy:unlisted=${UNLISTED_PUBLIC}`]);
        expect(verdicts["proxy-listed"], `${LABEL}: the listed target ${listed} must answer through the proxy`).toBe("allowed 200");
        expect(verdicts["proxy-unlisted"], `${LABEL}: the proxy itself must refuse the unlisted ${UNLISTED_PUBLIC}`).toBe("refused 403");
      });
    });

    test("workspace egress: metadata address and host gateway stay closed", async ({ browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + PROBE_TASK_MS));
      const hosts = decodeDotenvJsonList(
        process.env.SEMAPHORE_WORKSPACE_HOST_ADDRESSES_JSON,
        "SEMAPHORE_WORKSPACE_HOST_ADDRESSES_JSON",
      );
      expect(hosts.length, `${LABEL}: the deploy must name the host's own addresses`).toBeGreaterThan(0);
      await withWorkspace(shared, browser, LABEL, "", async (fixture) => {
        const openbao = new URL(openbaoOrigin());
        const closed = [
          `metadata=${METADATA}`,
          ...GATEWAY_PORTS.map((port) => `gateway-${port}=GATEWAY:${port}`),
          ...hosts.flatMap((address) => GATEWAY_PORTS.map((port) => `host-${address}-${port}=${hostPort(address, port)}`)),
        ];
        const entries = ["proxy", "direct"].flatMap((via) => closed.map((check) => `${via}:${check}`));
        const verdicts = await egressVerdicts(fixture, [`proxy:openbao=${openbao.hostname}:${openbao.port || 443}`, ...entries]);
        expect(verdicts["proxy-openbao"], `${LABEL}: the proxy must pass OpenBao, so its refusals below mean something`).toBe(
          "allowed 200",
        );
        for (const entry of entries) {
          const check = entry.split("=")[0].replace(":", "-");
          expect(verdicts[check], `${LABEL}: ${check} must stay closed`).toMatch(/^refused /);
        }
      });
    });

    test("workspace isolation: a task of one workspace reads nothing of another", async ({ browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 4 * WORKSPACE_TASK_MS + 3 * PROBE_TASK_MS));
      const state = new URL(requireDotenvValue(process.env.PROVISION_STATE_ENDPOINT, "PROVISION_STATE_ENDPOINT")).origin;
      const tokenFile = requireDotenvValue(process.env.SEMAPHORE_RUNNER_TOKEN_FILE, "SEMAPHORE_RUNNER_TOKEN_FILE");
      const workspacesDir = requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_DIR, "SEMAPHORE_WORKSPACES_DIR");
      await withWorkspace(shared, browser, LABEL, "", async (a) => {
        await withWorkspace(shared, browser, LABEL, "", async (b, cleanup) => {
          const reference = await stageWorkspaceKey(b, throwawaySshKey().privateKey);
          const [mount, ...path] = reference.openbao.split("#")[0].split("/");
          const salt = crypto.randomBytes(16).toString("hex");
          const holder = `${LABEL}: the holder task of ${b.result.alias}`;
          const { held, taskId: heldTask } = await holdInWorkspace(
            b,
            [salt, b.workspace, b.result.project_id, tokenFile, Math.ceil(resolveTimeout(2 * PROBE_TASK_MS) / 1000)],
            cleanup,
            holder,
          );
          for (const check of HOLDER_OWN) {
            expect(held[check], `${holder}: ${check} must find B's own while A probes, so A's probe of it means something`).toBe(
              "allowed 0",
            );
          }
          expect(held["token-digest"], `${holder}: must report the salted digest of B's token`).toMatch(SALTED_DIGEST);
          const what = `${LABEL}: the isolation probe of ${a.result.alias} against ${b.result.alias}`;
          const run = await runProbe(
            shared,
            a,
            a.result.project_id,
            ISOLATION_SCRIPT,
            [
              openbaoOrigin(),
              a.result.alias,
              b.result.alias,
              `${mount}/data/${path.join("/")}`,
              `${state}/${b.result.alias}-state/`,
              `semaphore-${b.result.alias}-runner-1`,
              tokenFile,
              workspacesDir,
              a.result.project_id,
              b.result.project_id,
              a.workspace,
              b.workspace,
              salt,
              held["token-digest"],
            ],
            what,
          );
          expectSucceeded(run, what);
          const holding = await shared.api(b.page, "GET", `/project/${b.result.project_id}/tasks/${heldTask}`);
          expect(TASK_FINISHED.has(holding.status), `${holder}: task ${heldTask} must still run when A's probe ends`).toBe(false);
          const verdicts = Object.fromEntries(probeLines(run, "isolation").map(splitVerdict));
          expect(verdicts["login-own"], `${what}: the login with its own role must pass, so the refusals below mean something`).toBe(
            "allowed 200",
          );
          for (const check of ISOLATION_OWN) {
            expect(verdicts[check], `${what}: ${check} must find A's own, so the same probe of B's means something`).toBe("allowed 0");
          }
          for (const check of ISOLATION_OTHER) {
            expect(verdicts[check], `${what}: ${check} must be refused`).toMatch(/^refused /);
          }
        });
      });
    });

    test("workspace deploy: no vault password and no vault block", async ({ browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + DEPLOY_RUN_MS));
      const { address } = await sharedTargetAddress();
      await withWorkspace(shared, browser, LABEL, `${address}:${SSH_PORT}`, async (fixture) => {
        const what = `${LABEL}: the environment of ws-${fixture.workspace}`;
        const environments = await shared.api(fixture.page, "GET", `/project/${fixture.result.project_id}/environment`);
        const names = environments.flatMap((environment) => [
          ...Object.keys(JSON.parse(environment.env || "{}")),
          ...Object.keys(JSON.parse(environment.json || "{}")),
          ...(environment.secrets || []).map((secret) => secret.name),
        ]);
        expect(names.length, `${what}: the workspace must have an environment`).toBeGreaterThan(0);
        expect(names.filter((name) => VAULT_NAME.test(name)), `${what}: must carry no vault password`).toEqual([]);
        const role = requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_PROBE_ROLE, "SEMAPHORE_WORKSPACE_PROBE_ROLE");
        const deployed = await deployToSharedTarget(shared, fixture, { roles: [role], hostVars: {} }, LABEL);
        expect(
          deployed.lines.filter((line) => VAULT_TRACES.some((trace) => line.includes(trace))),
          `${LABEL}: the deploy of ws-${fixture.workspace} must run without a vault password and see no vault block`,
        ).toHaveLength(0);
      });
    });

    test("workspace deploy: SSH key and host keys come from OpenBao", async ({ browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + DEPLOY_RUN_MS + PROBE_TASK_MS));
      const { address } = await sharedTargetAddress();
      await withWorkspace(shared, browser, LABEL, `${address}:${SSH_PORT}`, async (fixture) => {
        const role = requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_PROBE_ROLE, "SEMAPHORE_WORKSPACE_PROBE_ROLE");
        const { lines, target } = await deployToSharedTarget(shared, fixture, { roles: [role], hostVars: {} }, LABEL);
        const what = `${LABEL}: deploy of ws-${fixture.workspace} to ${target.address} with the workspace fixture key from OpenBao`;
        expect(lines.some((line) => line.includes(KEY_LOADED)), `${what}: deploy.sh must load the key into the task agent`).toBe(true);
        expect(lines.some((line) => line.includes(HOST_KEY_ERROR)), `${what}: the pinned host key must be accepted`).toBe(false);
        expect(lines.some((line) => line.includes(AUTH_REFUSED)), `${what}: the target must accept the key`).toBe(false);
        expect(lines.some((line) => line.startsWith(`ok: [${target.address}]`)), `${what}: the login must reach the target`).toBe(true);
        const after = `${LABEL}: the probe after the deploy of ws-${fixture.workspace}`;
        const left = await runProbe(shared, fixture, fixture.result.project_id, AGENT_LEFTOVER_SCRIPT, [], after);
        expectSucceeded(left, after);
        expect(probeLines(left, "leftover-agent"), `${after}: no agent socket and no known_hosts may be left`).toEqual(["refused 0"]);
      });
    });

    test("workspace: apply hands over the read key's public half", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace] }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        expect(Object.keys(result).sort(), `${LABEL}: the result of apply must hold exactly its five keys`).toEqual(RESULT_KEYS);
        expect(sshPublicShape(result.read_key), `${LABEL}: read_key must be one bare ed25519 public key`).toEqual({
          type: "ssh-ed25519",
          words: 0,
          fields: ["ssh-ed25519", 32],
          canonical: true,
        });
        const keyName = `${READ_KEY_PREFIX}${result.read_key}`;
        const keyIdsOf = async (projectId) =>
          (await shared.api(page, "GET", `/project/${projectId}/keys`))
            .filter((key) => key.type === "ssh" && key.name === keyName)
            .map((key) => key.id);
        expect(await keyIdsOf(result.project_id), `${LABEL}: the project ws-${workspace} must store the read key once`).toHaveLength(1);
        const repositoryUrl = result.templates.deploy.git_url;
        const cloning = Object.entries(result.templates).filter(([, template]) => template.git_url === repositoryUrl);
        expect(cloning.length, `${LABEL}: the templates of ws-${workspace} must clone the workspace repository`).toBeGreaterThan(
          HOST_TEMPLATES.length,
        );
        for (const [name, template] of cloning) {
          expect(
            await keyIdsOf(template.project_id),
            `${LABEL}: the template "${name}" must clone with the read key whose public half the result names`,
          ).toEqual([template.ssh_key_id]);
        }
      });
      await shared.logout(page, LABEL);
    });

    test("members: sync mirrors the organization", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + 4 * MEMBERS_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        const owner = await createMember(page, "owner", cleanup);
        const viewer = await createMember(page, "viewer", cleanup);
        const operator = await createMember(page, "operator", cleanup);
        await membersOk(page, ops, workspace, "add", { WORKSPACE_MEMBER: owner.id });
        const organization = await soleOrganization(page.request, workspace);
        const groups = await organizationGroups(page.request, organization.id);
        await placeInOrganization(page.request, organization.id, groups.Viewer, viewer.id);
        await placeInOrganization(page.request, organization.id, groups.Operator, operator.id);
        await membersOk(page, ops, workspace, "sync", {});
        expect(await memberRoles(page, result.project_id), `${LABEL}: sync must give each member the role of their group`).toEqual({
          [owner.username]: "task_runner",
          [viewer.username]: "guest",
          [operator.username]: "task_runner",
        });
        const viewerAccount = await soleSemaphoreUser(page, viewer.username);
        const operatorAccount = await soleSemaphoreUser(page, operator.username);
        await keycloak(page.request, "DELETE", `organizations/${organization.id}/groups/${groups.Operator}/members/${operator.id}`, undefined, [204]);
        await keycloak(page.request, "DELETE", `organizations/${organization.id}/groups/${groups.Viewer}/members/${viewer.id}`, undefined, [204]);
        await keycloak(page.request, "DELETE", `organizations/${organization.id}/members/${viewer.id}`, undefined, [204]);
        const shrunk = await membersOk(page, ops, workspace, "sync", {});
        expectLine(shrunk, `semaphore workspace=${workspace} account=${viewerAccount.id} role=none`);
        expectLine(shrunk, `semaphore workspace=${workspace} account=${operatorAccount.id} role=none`);
        expect(await memberRoles(page, result.project_id), `${LABEL}: a member without a group must lose the role`).toEqual({
          [owner.username]: "task_runner",
        });
        const again = await membersOk(page, ops, workspace, "sync", {});
        expect(changeLines(again), `${LABEL}: a sync of an unchanged organization must change nothing`).toEqual([]);
      });
      await shared.logout(page, LABEL);
    });

    test("members: a new member holds the role at the first login", async ({ page, browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + MEMBERS_TASK_MS + 2 * SIGN_IN_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        const member = await createMember(page, "first", cleanup);
        const added = await membersOk(page, ops, workspace, "add", { WORKSPACE_MEMBER: member.id });
        expectLine(added, `semaphore user ${member.id} created`);
        const account = await soleSemaphoreUser(page, member.username);
        expect({ external: account.external, admin: account.admin }, `${LABEL}: the mirror must create an external account`).toEqual({
          external: true,
          admin: false,
        });
        expect(await identitiesOf(page, account.id), `${LABEL}: the account must hold no identity before the first login`).toEqual([]);
        await allowLogin(page, member);
        const memberPage = await memberSignIn(browser, member, cleanup);
        expect((await shared.currentUser(memberPage)).id, `${LABEL}: the first login must land on the mirrored account`).toBe(account.id);
        expect(
          (await shared.api(memberPage, "GET", "/projects")).map((project) => project.id),
          `${LABEL}: the member must see the project ws-${workspace} at the first login`,
        ).toContain(result.project_id);
        expect(await memberRoles(page, result.project_id), `${LABEL}: the member must hold task_runner`).toEqual({
          [member.username]: "task_runner",
        });
        expect(
          (await identitiesOf(page, account.id)).map((identity) => ({ type: identity.type, external_uid: identity.external_uid })),
          `${LABEL}: the account must be linked to the member's sub once`,
        ).toEqual([{ type: "oidc", external_uid: member.id }]);
        await soleSemaphoreUser(page, member.username);
        await shared.logout(memberPage, `${LABEL} ${member.username}`);
      });
      await shared.logout(page, LABEL);
    });

    test("members: remove revokes in one task", async ({ page, browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + 3 * MEMBERS_TASK_MS + 2 * SIGN_IN_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        const owner = await createMember(page, "owner", cleanup);
        const member = await createMember(page, "leaver", cleanup);
        await membersOk(page, ops, workspace, "add", { WORKSPACE_MEMBER: owner.id });
        const organization = await soleOrganization(page.request, workspace);
        const groups = await organizationGroups(page.request, organization.id);
        await placeInOrganization(page.request, organization.id, groups.Operator, member.id);
        await membersOk(page, ops, workspace, "sync", {});
        const account = await soleSemaphoreUser(page, member.username);
        await allowLogin(page, member);
        const memberPage = await memberSignIn(browser, member, cleanup);
        expect(
          (await shared.apiResponse(memberPage, "GET", `/project/${result.project_id}`)).status(),
          `${LABEL}: the member must read the project ws-${workspace} before the remove`,
        ).toBe(200);
        await denyLogin(page, member);
        const removed = await membersOk(page, ops, workspace, "remove", { WORKSPACE_MEMBER: member.id });
        expectLine(removed, `change workspace=${workspace} action=remove user=${member.id} group=Operator change=left`);
        expectLine(removed, `change workspace=${workspace} action=remove user=${member.id} change=left_organization`);
        expectLine(removed, `semaphore workspace=${workspace} account=${account.id} role=none`);
        expect(
          await organizationMemberIds(page.request, organization.id),
          `${LABEL}: the remove must end the membership of ${member.username}`,
        ).not.toContain(member.id);
        expect(
          [403, 404],
          `${LABEL}: the member's next request to the project ws-${workspace} must be refused`,
        ).toContain((await shared.apiResponse(memberPage, "GET", `/project/${result.project_id}`)).status());
        await shared.logout(memberPage, `${LABEL} ${member.username}`);
      });
      await shared.logout(page, LABEL);
    });

    test("members: a sync never waits for an apply", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + TASK_START_MS + 3 * WORKSPACE_TASK_MS + MEMBERS_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        await applied(page, ops, workspace, pickedCore(), "");
        const applyId = await startTask(page, ops.projectId, ops.workspace, applySurvey(workspace, pickedCore(), ""), {});
        cleanup(() => awaitTask(page, ops.projectId, applyId, WORKSPACE_TASK_MS, `the second apply of ${workspace}`));
        await expect
          .poll(async () => (await shared.api(page, "GET", `/project/${ops.projectId}/tasks/${applyId}`)).status, {
            timeout: resolveTimeout(TASK_START_MS),
            intervals: [1_000],
            message: `${LABEL}: the second apply (task ${applyId}) must start running`,
          })
          .toBe("running");
        const sync = await membersOk(page, ops, workspace, "sync", {});
        const during = await shared.api(page, "GET", `/project/${ops.projectId}/tasks/${applyId}`);
        expect(
          TASK_FINISHED.has(during.status),
          `${LABEL}: the apply (task ${applyId}) must still run when the sync (task ${sync.id}) ended, it was ${during.status}`,
        ).toBe(false);
        const second = await awaitTask(page, ops.projectId, applyId, WORKSPACE_TASK_MS, `the second apply of ${workspace}`);
        expectStatus(second, "success");
        expect(
          Date.parse(sync.task.end) < Date.parse(second.task.end),
          `${LABEL}: the sync (task ${sync.id}) must end before the apply (task ${applyId})`,
        ).toBe(true);
      });
      await shared.logout(page, LABEL);
    });

    test("members: a suspended workspace runs no member task", async ({ page, browser }) => {
      requireWorkspaces();
      test.setTimeout(
        resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + 3 * MEMBERS_TASK_MS + HOST_TEMPLATES.length * PROBE_TASK_MS + 2 * SIGN_IN_MS),
      );
      await signIn(page);
      const ops = await operations(page);
      const probe = {
        host: PROBE_HOST,
        hostKey: sshEd25519PublicLine(),
        role: requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_PROBE_ROLE, "SEMAPHORE_WORKSPACE_PROBE_ROLE"),
        commit: ZERO_COMMIT,
      };
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        const owner = await createMember(page, "owner", cleanup);
        await membersOk(page, ops, workspace, "add", { WORKSPACE_MEMBER: owner.id });
        expect(await memberRoles(page, result.project_id), `${LABEL}: the owner must hold task_runner`).toEqual({
          [owner.username]: "task_runner",
        });
        await allowLogin(page, owner);
        const ownerPage = await memberSignIn(browser, owner, cleanup);
        const start = (name) =>
          shared.apiResponse(ownerPage, "POST", `/project/${result.project_id}/tasks`, {
            template_id: result.templates[name].template_id,
            environment: JSON.stringify(hostSurvey(name, probe)),
          });
        const suspended = await membersOk(page, ops, workspace, "sync", { WORKSPACE_SUSPENDED: "true" });
        expectLine(suspended, `semaphore workspace=${workspace} user=${owner.id} role=guest`);
        for (const name of HOST_TEMPLATES) {
          expect((await start(name)).status(), `${LABEL}: while ${workspace} is suspended, starting "${name}" must answer 403`).toBe(403);
        }
        const resumed = await membersOk(page, ops, workspace, "sync", {});
        expectLine(resumed, `semaphore workspace=${workspace} user=${owner.id} role=task_runner`);
        for (const name of HOST_TEMPLATES) {
          const response = await start(name);
          expect(response.status(), `${LABEL}: after the sync with false, starting "${name}" must answer 201`).toBe(201);
          const taskId = (await response.json()).id;
          cleanup(async () => {
            await shared.stopUnfinishedTask(page, result.project_id, taskId);
            await awaitTask(page, result.project_id, taskId, PROBE_TASK_MS, `the ${name} probe of ${workspace}`);
          });
        }
        await shared.logout(ownerPage, `${LABEL} ${owner.username}`);
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: destroy deletes the organization last", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 3 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], done, cleanup }) => {
        const alias = `ws-${workspace}`;
        await applied(page, ops, workspace, pickedCore(), "");
        const twin = await plantTwin(page.request, workspace);
        cleanup(() => deleteOrganization(page.request, twin));
        const stopped = await destroyRun(page, ops, workspace);
        expectStatus(stopped, "error");
        expect(await projectIdsNamed(page, alias), `${LABEL}: the project ${alias} must be gone before the organization`).toEqual([]);
        await expectNoRunner(page, alias);
        expect(
          (await markedOrganizations(page.request, workspace)).map((organization) => organization.alias),
          `${LABEL}: the organization ${alias} must outlive every other resource of the stopped destroy`,
        ).toContain(alias);
        await deleteOrganization(page.request, twin);
        const run = await destroyed(page, ops, workspace, done);
        const organizationIndex = lineIndex(run, `deleted organization ${alias}`);
        expect(organizationIndex, `${LABEL}: ${run.what} must delete the organization ${alias}`).toBeGreaterThan(-1);
        for (const role of ORGANIZATION_ROLES) {
          const roleIndex = lineIndex(run, `deleted role ${workspace}:${role}`);
          expect(
            roleIndex > -1 && roleIndex < organizationIndex,
            `${LABEL}: ${run.what} must delete the client role ${workspace}:${role} before the organization`,
          ).toBe(true);
        }
        const others = run.lines
          .map((line, index) => ({ role: ROLE_BANNER.exec(line.trim())?.[1], index }))
          .filter((step) => step.role && step.role !== "web-app-keycloak");
        expect(
          others.map((step) => step.role),
          `${LABEL}: ${run.what} must run the Semaphore steps`,
        ).toContain("web-app-semaphore");
        const lastOther = Math.max(...others.map((step) => step.index));
        expect(
          lastOther < organizationIndex,
          `${LABEL}: ${run.what} must delete the organization (line ${organizationIndex}) after the last step of every other role (line ${lastOther})`,
        ).toBe(true);
        await expectNoOrganization(page.request, workspace);
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: destroy retried after the organization is gone succeeds", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 3 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], done }) => {
        const alias = `ws-${workspace}`;
        await applied(page, ops, workspace, pickedCore(), "");
        expectLine(await destroyed(page, ops, workspace, done), `deleted organization ${alias}`);
        const retried = await destroyed(page, ops, workspace, done);
        expectLine(retried, `gone organization ${alias}`);
        for (const role of ORGANIZATION_ROLES) {
          expectLine(retried, `gone role ${workspace}:${role}`);
        }
        expect(organizationSummary(retried), `${LABEL}: the retried destroy must create and delete nothing in Keycloak`).toMatchObject({
          created: 0,
          deleted: 0,
        });
        expectStep(retried, `Align the runner row of ${alias}`, ["ok"]);
        expectStep(retried, `Stop the runner and egress of ${alias}`, ["skipping"]);
        expectStep(retried, `Remove the runner images of ${alias}`, ["ok"]);
        expectStep(retried, `Remove the compose project directory of ${alias}`, ["ok"]);
        await expectNoOrganization(page.request, workspace);
      });
      await shared.logout(page, LABEL);
    });

    test("members: a retried remove finishes", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + 6 * MEMBERS_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        const owner = await createMember(page, "owner", cleanup);
        const member = await createMember(page, "leaver", cleanup);
        await membersOk(page, ops, workspace, "add", { WORKSPACE_MEMBER: owner.id });
        const organization = await soleOrganization(page.request, workspace);
        const groups = await organizationGroups(page.request, organization.id);
        await placeInOrganization(page.request, organization.id, groups.Operator, member.id);
        await membersOk(page, ops, workspace, "sync", {});
        const account = await soleSemaphoreUser(page, member.username);
        const plantedName = `pw-ws-manager-${crypto.randomBytes(4).toString("hex")}`;
        cleanup(() => deleteSemaphoreUsers(page, plantedName));
        const planted = await shared.api(page, "POST", "/users", {
          username: plantedName,
          name: plantedName,
          email: `${plantedName}@example.invalid`,
          external: true,
          admin: false,
          alert: false,
        });
        await shared.api(page, "POST", `/project/${result.project_id}/users`, { user_id: planted.id, role: "manager" });
        const failed = await membersRun(page, ops, workspace, "remove", { WORKSPACE_MEMBER: member.id });
        expectStatus(failed, "error");
        expectLine(failed, `grants edit rights beyond the store's account: account=${planted.id}`);
        expect(
          await organizationMemberIds(page.request, organization.id),
          `${LABEL}: the failed remove must already have ended the membership`,
        ).not.toContain(member.id);
        expect(
          Object.keys(await memberRoles(page, result.project_id)),
          `${LABEL}: the failed remove must already have taken the project role`,
        ).not.toContain(member.username);
        await shared.api(page, "DELETE", `/project/${result.project_id}/users/${planted.id}`);
        const finished = await membersOk(page, ops, workspace, "remove", { WORKSPACE_MEMBER: member.id });
        expect(changeLines(finished), `${LABEL}: the retried remove must find nothing left to change`).toEqual([]);
        await shared.api(page, "POST", `/project/${result.project_id}/users`, { user_id: account.id, role: "task_runner" });
        const leftover = await membersOk(page, ops, workspace, "remove", { WORKSPACE_MEMBER: member.id });
        expect(
          changeLines(leftover),
          `${LABEL}: a remove of a former member must take only the Semaphore role and make no membership call`,
        ).toEqual([`semaphore workspace=${workspace} account=${account.id} role=none`]);
        const last = await membersOk(page, ops, workspace, "remove", { WORKSPACE_MEMBER: member.id });
        expect(changeLines(last), `${LABEL}: a further remove must change nothing`).toEqual([]);
        expect(await memberRoles(page, result.project_id), `${LABEL}: only the owner may keep a role`).toEqual({
          [owner.username]: "task_runner",
        });
      });
      await shared.logout(page, LABEL);
    });

    test("inventory commit: a task runs exactly the given commit", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + PROBE_TASK_MS));
      const address = privateTargetAddress();
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), `${address}:22`);
        const deploy = result.templates.deploy;
        const [owner, file] = new URL(deploy.git_url).pathname.replace(/^\//, "").split("/");
        const repository = `${owner}/${file.replace(/\.git$/, "")}`;
        await gitea(
          page.request,
          "POST",
          `/orgs/${owner}/repos`,
          { name: file.replace(/\.git$/, ""), private: true, auto_init: true, readme: "Default", default_branch: deploy.git_branch },
          [201],
        );
        cleanup(() => gitea(page.request, "DELETE", `/repos/${repository}`, undefined, [204, 404]));
        await gitea(page.request, "POST", `/repos/${repository}/keys`, { title: "read", key: result.read_key, read_only: true }, [201]);
        const pinned = await commitFile(page.request, repository, "pw-pinned.txt", { branch: deploy.git_branch });
        const moved = await commitFile(page.request, repository, "pw-moved.txt", { branch: deploy.git_branch });
        const other = await commitFile(page.request, repository, "pw-other.txt", {
          branch: deploy.git_branch,
          new_branch: MEMBER_BRANCH,
        });
        expect(
          (await gitea(page.request, "GET", `/repos/${repository}/branches/${deploy.git_branch}`, undefined, [200])).commit.id,
          `${LABEL}: ${deploy.git_branch} of ${repository} must have moved past the pinned commit`,
        ).toBe(moved);
        const probe = {
          host: address,
          hostKey: sshEd25519PublicLine(),
          role: requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_PROBE_ROLE, "SEMAPHORE_WORKSPACE_PROBE_ROLE"),
          commit: pinned,
        };
        const run = await runTask(
          page,
          deploy.project_id,
          deploy.template_id,
          hostSurvey("deploy", probe),
          { commit_hash: other },
          PROBE_TASK_MS,
          `deploy of ${workspace} at ${pinned}`,
        );
        expectLine(run, `deploy.sh: inventory at ${pinned}`);
        expectNoLine(run, `inventory at ${moved}`);
        expectNoLine(run, `inventory at ${other}`);
        expectLine(run, "deploy.sh: the inventory repository holds no ");
        expectStatus(run, "error");
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: the store account manages workspace projects only", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace] }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        const account = await soleSemaphoreUser(
          page,
          requireDotenvValue(process.env.SEMAPHORE_STORE_USERNAME, "SEMAPHORE_STORE_USERNAME"),
        );
        expect(account.admin, `${LABEL}: the store's account must not be a Semaphore admin`).toBe(false);
        const guestIn = new Set([
          ops.projectId,
          result.templates[`unlock ${result.alias}`].project_id,
          result.templates[`export ${result.alias}`].project_id,
        ]);
        const held = {};
        const expected = {};
        for (const project of await shared.api(page, "GET", "/projects")) {
          const members = await shared.api(page, "GET", `/project/${project.id}/users`);
          held[project.name] = members
            .filter((member) => member.id === account.id)
            .flatMap((member) => [...member.roles])
            .sort();
          if (WORKSPACE_PROJECT.test(project.name)) {
            expected[project.name] = ["manager"];
          } else {
            expected[project.name] = guestIn.has(project.id) ? ["guest"] : [];
          }
        }
        expect(held[result.alias], `${LABEL}: the store must manage the project ${result.alias}`).toEqual(["manager"]);
        expect(held, `${LABEL}: the store must hold manager in every workspace project and guest in the three platform projects only`).toEqual(
          expected,
        );
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: the store starts only workspace, members and user", async ({ page, browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + MEMBERS_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      const grants = {};
      const expected = {};
      for (const template of await shared.api(page, "GET", `/project/${ops.projectId}/templates`)) {
        grants[template.name] = (await shared.api(page, "GET", `/project/${ops.projectId}/templates/${template.id}/perms`)).map(
          (grant) => [grant.role_slug, grant.permissions],
        );
        expected[template.name] = STORE_TEMPLATES.includes(template.name) ? [["guest", RUN_AND_READ]] : [];
      }
      expect(Object.keys(grants), `${LABEL}: the Workspaces project must hold ${ROTATION_TEMPLATE}`).toContain(ROTATION_TEMPLATE);
      expect(grants, `${LABEL}: only workspace, members and user may carry a grant, one run-and-read grant for guest`).toEqual(
        expected,
      );
      const store = await browser.newContext({ ignoreHTTPSErrors: true });
      await withCleanup(async (cleanup) => {
        cleanup(() => store.close());
        const token = await storeSemaphoreToken(store);
        const refused = {
          [ops.workspace]: ["workspace", { WORKSPACE: REFUSED_INPUT, WORKSPACE_ACTION: "apply" }, WORKSPACE_TASK_MS],
          [ops.members]: [
            "members",
            { WORKSPACE: REFUSED_INPUT, MEMBERS_ACTION: "list", WORKSPACE_SUSPENDED: "false" },
            MEMBERS_TASK_MS,
          ],
          [ops.user]: ["user", { USER_ACTION: REFUSED_INPUT, USER_ID: REFUSED_INPUT }, MEMBERS_TASK_MS],
        };
        for (const [templateId, [name, survey, runMs]] of Object.entries(refused)) {
          const response = await withToken(store.request, token, "POST", `/project/${ops.projectId}/tasks`, {
            template_id: Number(templateId),
            environment: JSON.stringify(survey),
          });
          expect(response.status(), `${LABEL}: the store starting "${name}" must answer 201`).toBe(201);
          const taskId = (await response.json()).id;
          cleanup(async () => {
            const run = await awaitTask(page, ops.projectId, taskId, runMs, `the store's ${name} with a refused input`);
            expectStatus(run, "error");
          });
        }
        const rotation = await withToken(store.request, token, "POST", `/project/${ops.projectId}/tasks`, {
          template_id: ops.rotation,
          environment: "{}",
        });
        expect(rotation.status(), `${LABEL}: the store starting "${ROTATION_TEMPLATE}" must answer 403`).toBe(403);
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: the store account changes no project member", async ({ page, browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        const account = await soleSemaphoreUser(
          page,
          requireDotenvValue(process.env.SEMAPHORE_STORE_USERNAME, "SEMAPHORE_STORE_USERNAME"),
        );
        const admin = await shared.currentUser(page);
        const path = `/project/${result.project_id}/users`;
        const roster = async () =>
          (await shared.api(page, "GET", path)).map((member) => [member.id, [...member.roles].sort().join(",")]).sort();
        const before = await roster();
        const store = await browser.newContext({ ignoreHTTPSErrors: true });
        cleanup(() => store.close());
        const token = await storeSemaphoreToken(store);
        const attempts = [
          ["adding", "POST", path, { user_id: admin.id, role: "owner" }],
          ["changing", "PUT", `${path}/${account.id}`, { user_id: account.id, role: "owner" }],
          ["removing", "DELETE", `${path}/${account.id}`, undefined],
        ];
        for (const [what, method, route, data] of attempts) {
          expect(
            (await withToken(store.request, token, method, route, data)).status(),
            `${LABEL}: ${what} a member of ${result.alias} with the store's token must answer 403`,
          ).toBe(403);
        }
        expect(await roster(), `${LABEL}: the members of ${result.alias} must stay as they were`).toEqual(before);
      });
      await shared.logout(page, LABEL);
    });

    test("workspace: no admin token outlives its task", async ({ page }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 4 * WORKSPACE_TASK_MS + 3 * MEMBERS_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const unmarked = await plantUnmarked(page.request, workspace);
        cleanup(() => deleteOrganization(page.request, unmarked));
        const failedApply = await applyRun(page, ops, workspace, pickedCore(), "");
        expectStatus(failedApply, "error");
        await deleteOrganization(page.request, unmarked);
        const { run: apply, result } = await applied(page, ops, workspace, pickedCore(), "");
        const sync = await membersOk(page, ops, workspace, "sync", {});
        const plantedName = `pw-ws-manager-${crypto.randomBytes(4).toString("hex")}`;
        cleanup(() => deleteSemaphoreUsers(page, plantedName));
        const planted = await shared.api(page, "POST", "/users", {
          username: plantedName,
          name: plantedName,
          email: `${plantedName}@example.invalid`,
          external: true,
          admin: false,
          alert: false,
        });
        await shared.api(page, "POST", `/project/${result.project_id}/users`, { user_id: planted.id, role: "manager" });
        const failedSync = await membersRun(page, ops, workspace, "sync", {});
        expectStatus(failedSync, "error");
        expectLine(failedSync, `grants edit rights beyond the store's account: account=${planted.id}`);
        await shared.api(page, "DELETE", `/project/${result.project_id}/users/${planted.id}`);
        const runs = [failedApply, apply, sync, failedSync];
        const outlived = (await shared.api(page, "GET", "/user/tokens"))
          .filter((token) => !token.expired && runs.some((run) => withinRun(token.created, run)))
          .map((token) => `${token.name} created ${token.created}`);
        expect(outlived, `${LABEL}: no admin token minted by a workspace or members task may outlive it`).toEqual([]);
      });
      await shared.logout(page, LABEL);
    });

    test("workspace roles: a task runner runs templates and changes nothing", async ({ page, browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * WORKSPACE_TASK_MS + MEMBERS_TASK_MS + PROBE_TASK_MS + 2 * SIGN_IN_MS));
      await signIn(page);
      const ops = await operations(page);
      const probe = {
        host: PROBE_HOST,
        hostKey: sshEd25519PublicLine(),
        role: requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_PROBE_ROLE, "SEMAPHORE_WORKSPACE_PROBE_ROLE"),
        commit: ZERO_COMMIT,
      };
      await withWorkspaces(page, ops, 1, async ({ workspaces: [workspace], cleanup }) => {
        const { result } = await applied(page, ops, workspace, pickedCore(), "");
        const owner = await createMember(page, "owner", cleanup);
        await membersOk(page, ops, workspace, "add", { WORKSPACE_MEMBER: owner.id });
        expect(await memberRoles(page, result.project_id), `${LABEL}: the owner must hold task_runner`).toEqual({
          [owner.username]: "task_runner",
        });
        await allowLogin(page, owner);
        const ownerPage = await memberSignIn(browser, owner, cleanup);
        const restart = result.templates.restart;
        const started = await shared.apiResponse(ownerPage, "POST", `/project/${result.project_id}/tasks`, {
          template_id: restart.template_id,
          environment: JSON.stringify(hostSurvey("restart", probe)),
        });
        expect(started.status(), `${LABEL}: a task runner starting "restart" must answer 201`).toBe(201);
        const taskId = (await started.json()).id;
        cleanup(async () => {
          await shared.stopUnfinishedTask(page, result.project_id, taskId);
          await awaitTask(page, result.project_id, taskId, PROBE_TASK_MS, `the restart probe of ${workspace}`);
        });
        const resources = {
          template: `/project/${result.project_id}/templates/${restart.template_id}`,
          key: `/project/${result.project_id}/keys/${restart.ssh_key_id}`,
          inventory: `/project/${result.project_id}/inventory/${restart.inventory_id}`,
          repository: `/project/${result.project_id}/repositories/${restart.repository_id}`,
          environment: `/project/${result.project_id}/environment/${restart.environment_id}`,
        };
        for (const [kind, path] of Object.entries(resources)) {
          const body = await shared.api(page, "GET", path);
          const response = await shared.apiResponse(ownerPage, "PUT", path, { ...body, name: `${body.name} pw` });
          expect(response.status(), `${LABEL}: a task runner changing the ${kind} of ${result.alias} must answer 403`).toBe(403);
          expect((await shared.api(page, "GET", path)).name, `${LABEL}: the ${kind} of ${result.alias} must keep its name`).toBe(
            body.name,
          );
        }
        await shared.logout(ownerPage, `${LABEL} ${owner.username}`);
      });
      await shared.logout(page, LABEL);
    });

    test("rotation: store tokens are replaced and old ones revoked", async ({ page, browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + 2 * ROTATION_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      const schedules = (await shared.api(page, "GET", `/project/${ops.projectId}/schedules`)).filter(
        (schedule) => schedule.template_id === ops.rotation,
      );
      expect(
        schedules.map((schedule) => [Boolean(schedule.active), WEEKLY_CRON.test(schedule.cron_format)]),
        `${LABEL}: ${ROTATION_TEMPLATE} must run on exactly one active weekly schedule`,
      ).toEqual([[true, true]]);
      const store = await browser.newContext({ ignoreHTTPSErrors: true });
      await withCleanup(async (cleanup) => {
        cleanup(() => store.close());
        const first = await runTask(page, ops.projectId, ops.rotation, {}, {}, ROTATION_TASK_MS, ROTATION_TEMPLATE);
        expectStatus(first, "success");
        const earlier = await storeEntries(store);
        expectStoreEntry(earlier.semaphore, first, `${PLATFORM_MOUNT}/${STORE_SEMAPHORE_PATH}`);
        expectStoreEntry(earlier.gitea, first, `${PLATFORM_MOUNT}/${STORE_GITEA_PATH}`);
        const giteaUser = await giteaWithToken(store.request, earlier.gitea.token, "GET", "/user");
        expect(giteaUser.status(), `${LABEL}: the store's Gitea token must work after the rotation`).toBe(200);
        const login = (await giteaUser.json()).login;
        const minted = (await gitea(page.request, "GET", `/users/${login}/tokens`, undefined, [200]))
          .map((token) => token.name)
          .filter((name) => name.endsWith(earlier.gitea.expires_at));
        expect(minted, `${LABEL}: exactly one Gitea token of ${login} must be named after its expires_at`).toHaveLength(1);
        const giteaPassed = `${minted[0].slice(0, -earlier.gitea.expires_at.length)}${PASSED_EXPIRY}`;
        const semaphorePassed = `${STORE_TOKEN_PREFIX}${PASSED_EXPIRY}`;
        const plantedSemaphore = await withToken(store.request, earlier.semaphore.token, "POST", "/user/tokens", {
          name: semaphorePassed,
        });
        expect(plantedSemaphore.status(), `${LABEL}: the store minting a token of its own must answer 201`).toBe(201);
        const passedSemaphoreToken = (await plantedSemaphore.json()).id;
        cleanup(async () => {
          const removed = await withToken(
            store.request,
            earlier.semaphore.token,
            "DELETE",
            `/user/tokens/${passedSemaphoreToken.slice(0, TOKEN_PREFIX_LENGTH)}`,
          );
          expect([204, 404], `${LABEL}: deleting the planted Semaphore token answered ${removed.status()}`).toContain(
            removed.status(),
          );
        });
        const passedGiteaToken = (
          await gitea(page.request, "POST", `/users/${login}/tokens`, { name: giteaPassed, scopes: ["read:user"] }, [201])
        ).sha1;
        cleanup(() => gitea(page.request, "DELETE", `/users/${login}/tokens/${encodeURIComponent(giteaPassed)}`, undefined, [204, 404]));
        const second = await runTask(page, ops.projectId, ops.rotation, {}, {}, ROTATION_TASK_MS, `the manual ${ROTATION_TEMPLATE}`);
        expectStatus(second, "success");
        expectLine(second, `revoked semaphore token ${semaphorePassed}`);
        const later = await storeEntries(store);
        expectStoreEntry(later.semaphore, second, `${PLATFORM_MOUNT}/${STORE_SEMAPHORE_PATH}`);
        expectStoreEntry(later.gitea, second, `${PLATFORM_MOUNT}/${STORE_GITEA_PATH}`);
        expect(
          [later.semaphore.token === earlier.semaphore.token, later.gitea.token === earlier.gitea.token],
          `${LABEL}: the manual run must replace both store tokens`,
        ).toEqual([false, false]);
        const statuses = {
          "the passed Semaphore token": (await withToken(store.request, passedSemaphoreToken, "GET", "/user")).status(),
          "the passed Gitea token": (await giteaWithToken(store.request, passedGiteaToken, "GET", "/user")).status(),
          "the earlier Semaphore token": (await withToken(store.request, earlier.semaphore.token, "GET", "/user")).status(),
          "the earlier Gitea token": (await giteaWithToken(store.request, earlier.gitea.token, "GET", "/user")).status(),
          "the new Semaphore token": (await withToken(store.request, later.semaphore.token, "GET", "/user")).status(),
          "the new Gitea token": (await giteaWithToken(store.request, later.gitea.token, "GET", "/user")).status(),
        };
        expect(statuses, `${LABEL}: only the store tokens whose expires_at has passed may stop working`).toEqual({
          "the passed Semaphore token": 401,
          "the passed Gitea token": 401,
          "the earlier Semaphore token": 200,
          "the earlier Gitea token": 200,
          "the new Semaphore token": 200,
          "the new Gitea token": 200,
        });
      });
      await shared.logout(page, LABEL);
    });

    test("rotation: the semaphore token expires on its own", async ({ page, browser }) => {
      requireWorkspaces();
      test.setTimeout(resolveTimeout(BASE_MS + ROTATION_TASK_MS));
      await signIn(page);
      const ops = await operations(page);
      const store = await browser.newContext({ ignoreHTTPSErrors: true });
      await withCleanup(async (cleanup) => {
        cleanup(() => store.close());
        const run = await runTask(page, ops.projectId, ops.rotation, {}, {}, ROTATION_TASK_MS, ROTATION_TEMPLATE);
        expectStatus(run, "success");
        const { semaphore } = await storeEntries(store);
        expectStoreEntry(semaphore, run, `${PLATFORM_MOUNT}/${STORE_SEMAPHORE_PATH}`);
        const listed = await withToken(store.request, semaphore.token, "GET", "/user/tokens");
        expect(listed.status(), `${LABEL}: the store must list its own tokens`).toBe(200);
        const named = (await listed.json()).filter((token) => token.name === `${STORE_TOKEN_PREFIX}${semaphore.expires_at}`);
        expect(named.map((token) => token.name), `${LABEL}: exactly one store token must carry the name of the entry`).toHaveLength(1);
        expect(Boolean(named[0].expires_at), `${LABEL}: the rotated Semaphore token must carry Semaphore's own expires_at`).toBe(true);
        expectAfterRun(named[0].expires_at, run, SEMAPHORE_LIFETIME_MS, "Semaphore's own expires_at of the store token");
      });
      await shared.logout(page, LABEL);
    });
  });
};
