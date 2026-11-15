const crypto = require("node:crypto");
const dns = require("node:dns");
const zlib = require("node:zlib");
const { expect, test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiFetchOnion, decodeDotenvQuotedValue, requireDotenvValue } = require("./personas");
const { ANSI, TASK_FINISHED, WORKSPACE_RUN_MS, WORKSPACE_TEMPLATE, strictFlag } = require("./personas/utils/workspace");

const TASK_POLL_INTERVAL_MS = 5_000;
const REQUEST_MS = 30_000;
const ROTATION_RUN_MS = 10 * 60_000;
const OUTPUT_TAIL_LINES = 30;
const ERROR_BODY_CHARS = 300;
const ROTATION_TEMPLATE = "rotate store credentials";
const LATEST_CORE_VERSION = "latest";
const PLATFORM_MOUNT = "platform";
const STORE_GITEA_PATH = "store/gitea";
const REPOSITORY_BRANCH = "main";
const PRESIGNED_SIGNATURE = /X-Amz-Signature=[0-9a-f]+/g;
const LOCKED_FLAGS = ["allow_override_args_in_task", "allow_override_branch_in_task", "allow_parallel_tasks"];
const JWT_AUDIENCE = "openbao";
const PROBE_TEMPLATE = "probe";
const PROBE_RUN_MS = 10 * 60_000;
const PROBE_LINE = /^PROBE (\S+) (.*)$/;
const TENANT_MOUNT = "tenant";
const WORKSPACE_KEY_PATH = "ssh";
const WORKSPACE_KEY_FIELD = "private_key";
const WORKSPACE_KEY_VAR = "WORKSPACE_SSH_KEY";
const WORKSPACE_INVENTORY = "devices.yml";
const TARGET_LOGIN = "root";
const OPENSSH_MAGIC = Buffer.from("openssh-key-v1\0", "latin1");
const OPENSSH_BLOCK = 8;
const PEM_COLUMNS = 70;
const PINNED_KEY_TYPE = "ssh-ed25519";
const DEPLOY_RUN_MS = 90 * 60_000;
const DEPLOY_ORDER = { SALES_ORDER: "PW1", LINE: "1", DNS_LABEL: "pw" };
const PLAIN_KIND = "plain";
const DEFAULT_KIND = "default";
const ADMIN_USER = "platform_administrator";
const CREATE_ONLY = { cas: 0 };
const ALPHANUMERIC = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
const ALPHANUMERIC_LENGTH = 64;
const SK_LENGTH = 48;
const LOWER_ALNUM = "0123456789abcdefghijklmnopqrstuvwxyz";
const BCRYPT_ALPHABET = `./${ALPHANUMERIC}`;
const BCRYPT_PREFIX = "$2b$12$";
const BCRYPT_BODY = 53;
const STRONG_MARKS = "!@#$%^&*()-_=+[]:,.?";
const STRONG_PASSWORD_LENGTH = 32;
const STRONG_PASSWORD = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$/;
const USER_MARKS = "-_.";
const USER_PASSWORD_LENGTH = 64;
const USER_PASSWORD = /^[A-Za-z0-9](?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[-_.])[A-Za-z0-9._-]{15,}$/;
const PASSWORD_ATTEMPTS = 64;

const KDBX_SIGNATURE = [0x9aa2d903, 0xb54bfb67];
const KDBX_MAJOR = 3;
const KDBX_HEADER = {
  end: 0,
  cipher: 2,
  compression: 3,
  masterSeed: 4,
  transformSeed: 5,
  transformRounds: 6,
  iv: 7,
  protectedStreamKey: 8,
  streamStartBytes: 9,
  innerStream: 10,
};
const KDBX_AES256 = "31c1f2e6bf714350be5805216afc5aff";
const KDBX_GZIP = 1;
const KDBX_SALSA20 = 2;
const SALSA20_IV = Buffer.from("e830094b97205d2a", "hex");
const SALSA20_SIGMA = Buffer.from("expand 32-byte k", "ascii");
const SALSA20_DOUBLE_ROUNDS = 10;
const XML_ENTITIES = { lt: "<", gt: ">", amp: "&", quot: '"', apos: "'" };

const AGE_INTRO = "age-encryption.org/v1\n";
const AGE_MAC_LINE = "\n--- ";
const AGE_X25519_LABEL = "age-encryption.org/v1/X25519";
const AGE_STANZA_COLUMNS = 64;
const AGE_CHUNK = 64 * 1024;
const AGE_TAG = 16;
const AGE_STREAM_NONCE = 16;
const AGE_KEY = 32;
const X25519_SPKI_PREFIX = Buffer.from("302a300506032b656e032100", "hex");
const BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";
const BECH32_GENERATOR = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];

const TAR_BLOCK = 512;

function skipUnlessWorkspaces() {
  test.skip(
    !strictFlag(process.env.SEMAPHORE_WORKSPACES_ENABLED, "SEMAPHORE_WORKSPACES_ENABLED"),
    "SEMAPHORE_WORKSPACES_ENABLED=false: the inventory declares no services.semaphore.workspaces beside services.semaphore.deploy",
  );
}

function skipWithoutPlatformHost() {
  test.skip(
    !decodeDotenvQuotedValue(process.env.SEMAPHORE_WORKSPACES_PLATFORM_HOST),
    "SEMAPHORE_WORKSPACES_PLATFORM_HOST is empty: the deploy fixture lists no platform host in workspaces.yml, so no workspace operation reaches the platform",
  );
}

/**
 * Args:
 *   lines: the output lines of a task.
 *
 * Returns:
 *   The last lines, with every presigned signature blanked.
 */
function outputTail(lines) {
  return lines.slice(-OUTPUT_TAIL_LINES).join("\n").replace(PRESIGNED_SIGNATURE, "X-Amz-Signature=<blanked>");
}

/**
 * Args:
 *   lines: the output lines of a task.
 *
 * Returns:
 *   The last line that is not blank, trimmed.
 */
function lastLine(lines) {
  const filled = lines.filter((line) => line.trim() !== "");
  return filled.length === 0 ? "" : filled[filled.length - 1].trim();
}

/**
 * Args:
 *   context: the browser context whose request client sends the call.
 *   method: the HTTP method.
 *   url: the absolute URL.
 *   options: headers and data of the request.
 *
 * Returns:
 *   The response, whatever its status; a failed request throws its first
 *   error line only.
 */
async function http(context, method, url, options = {}) {
  try {
    return await apiFetchOnion(context.request, url, {
      ...options,
      method,
      failOnStatusCode: false,
      timeout: resolveTimeout(REQUEST_MS),
    });
  } catch (error) {
    // eslint-disable-next-line preserve-caught-error -- the call log of the cause lists the Authorization header
    throw new Error(`${method} ${new URL(url).origin}${new URL(url).pathname} failed: ${String(error && error.message).split("\n")[0]}`);
  }
}

/**
 * Args:
 *   response: a response of `http`.
 *   statuses: the statuses the caller accepts.
 *   what: the call the failure message names.
 */
async function expectStatus(response, statuses, what) {
  const status = response.status();
  const detail = status >= 400 ? `: ${(await response.text()).slice(0, ERROR_BODY_CHARS)}` : "";
  expect(statuses, `${what} answered HTTP ${status}${detail}`).toContain(status);
}

/**
 * Args:
 *   template: a Semaphore template.
 *
 * Returns:
 *   Its survey as `[name, required, target]` triples, in order.
 */
function surveyOf(template) {
  return (template.survey_vars || []).map((variable) => [variable.name, Boolean(variable.required), variable.target]);
}

/**
 * Args:
 *   template: a Semaphore template.
 *   label: the persona label the assertion messages name.
 */
function expectLockedTemplate(template, label) {
  for (const flag of LOCKED_FLAGS) {
    expect(Boolean(template[flag]), `${label}: the template ${template.name} must keep ${flag} off`).toBe(false);
  }
  expect(
    Boolean(template.jwt_params && template.jwt_params.enabled) && template.jwt_params.audience === JWT_AUDIENCE,
    `${label}: the template ${template.name} must issue a task token for ${JWT_AUDIENCE}`,
  ).toBe(true);
  expect(Boolean(template.runner_tag), `${label}: the template ${template.name} must name its runner tag`).toBe(true);
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page carrying a Semaphore session.
 *   name: the project name.
 *
 * Returns:
 *   The one project of that name.
 */
async function namedProject(shared, page, name) {
  const projects = await shared.api(page, "GET", "/projects");
  const named = projects.filter((project) => project.name === name);
  expect(
    named,
    `exactly one Semaphore project must be named "${name}" (projects: ${projects.map((project) => project.name).join(", ")})`,
  ).toHaveLength(1);
  return named[0];
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page carrying a Semaphore session.
 *   projectId: the project.
 *   name: the template name.
 *
 * Returns:
 *   Every template of the project carrying that name.
 */
async function namedTemplates(shared, page, projectId, name) {
  return (await shared.api(page, "GET", `/project/${projectId}/templates`)).filter((template) => template.name === name);
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page carrying a Semaphore session.
 *   projectId: the project.
 *   name: the template name.
 *
 * Returns:
 *   The one template of that name.
 */
async function namedTemplate(shared, page, projectId, name) {
  const named = await namedTemplates(shared, page, projectId, name);
  expect(named, `project ${projectId} must hold exactly one template "${name}"`).toHaveLength(1);
  return named[0];
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page whose session may run the template.
 *   projectId: the project.
 *   templateId: the template.
 *   survey: the survey answers, every one a declared survey variable.
 *
 * Returns:
 *   The id of the task Semaphore created.
 */
async function startTask(shared, page, projectId, templateId, survey) {
  const task = await shared.api(page, "POST", `/project/${projectId}/tasks`, {
    template_id: templateId,
    environment: JSON.stringify(survey),
  });
  return task.id;
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page whose session may read the task.
 *   projectId: the project.
 *   taskId: the task.
 *   runMs: the longest the task may run, before timeout scaling.
 *   label: the persona label the assertion messages name.
 *
 * Returns:
 *   The finished task and its output lines.
 */
async function awaitTask(shared, page, projectId, taskId, runMs, label) {
  let task;
  await expect
    .poll(
      async () => {
        task = await shared.api(page, "GET", `/project/${projectId}/tasks/${taskId}`);
        return TASK_FINISHED.has(task.status);
      },
      {
        timeout: resolveTimeout(runMs),
        intervals: [TASK_POLL_INTERVAL_MS],
        message: `${label}: task ${taskId} must finish`,
      },
    )
    .toBe(true);
  const output = await shared.api(page, "GET", `/project/${projectId}/tasks/${taskId}/output`);
  return { task, lines: output.map((line) => line.output) };
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page whose session may run the template.
 *   projectId: the project.
 *   templateId: the template.
 *   survey: the survey answers.
 *   runMs: the longest the task may run, before timeout scaling.
 *   label: the persona label the assertion messages name.
 *
 * Returns:
 *   The finished task and its output lines; a task still running is stopped.
 */
async function runTemplate(shared, page, projectId, templateId, survey, runMs, label) {
  const taskId = await startTask(shared, page, projectId, templateId, survey);
  try {
    return await awaitTask(shared, page, projectId, taskId, runMs, label);
  } finally {
    await shared.stopUnfinishedTask(page, projectId, taskId);
  }
}

/**
 * Args:
 *   run: a result of `runTemplate`.
 *   label: what the failure message names.
 */
function expectSucceeded(run, label) {
  expect(run.task.status, `${label}: task ${run.task.id} ended ${run.task.status}; output tail:\n${outputTail(run.lines)}`).toBe(
    "success",
  );
}

/**
 * Args:
 *   run: a result of `runTemplate`.
 *   refusal: the line the task has to print.
 *   label: what the failure message names.
 */
function expectRefused(run, refusal, label) {
  expect(
    run.task.status,
    `${label}: task ${run.task.id} must end in error, it ended ${run.task.status}; output tail:\n${outputTail(run.lines)}`,
  ).toBe("error");
  expect(
    run.lines.some((line) => line.includes(refusal)),
    `${label}: task ${run.task.id} must print "${refusal}"; output tail:\n${outputTail(run.lines)}`,
  ).toBe(true);
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `openWorkspace`.
 *   projectId: the workspace project, or the provision or export project,
 *     whose locked probe template core creates in test runtimes only.
 *   script: the bash text the probe runs inside the task; it prints only
 *     `PROBE <kind> <status>` lines and never a value it read.
 *   args: the positional arguments of that text.
 *   label: what the failure messages name.
 *
 * Returns:
 *   The finished probe run.
 */
async function runProbe(shared, fixture, projectId, script, args, label) {
  const name = projectId === fixture.result.project_id ? PROBE_TEMPLATE : `${PROBE_TEMPLATE} ${fixture.result.alias}`;
  const template = await namedTemplate(shared, fixture.page, projectId, name);
  return runTemplate(
    shared,
    fixture.page,
    projectId,
    template.id,
    { PROBE_SCRIPT: script, PROBE_ARGS: args.join(" ") },
    PROBE_RUN_MS,
    label,
  );
}

/**
 * Args:
 *   line: one output line of a task.
 *
 * Returns:
 *   The line without colour markup and surrounding blanks.
 */
function bare(line) {
  return String(line).replace(ANSI, "").trim();
}

/**
 * Args:
 *   run: a finished probe run.
 *   kind: the first word after `PROBE`.
 *
 * Returns:
 *   The rest of every `PROBE <kind>` line the probe printed, in order.
 */
function probeLines(run, kind) {
  return run.lines
    .map((line) => PROBE_LINE.exec(bare(line)))
    .filter((match) => match && match[1] === kind)
    .map((match) => match[2]);
}

function workspacesProjectName() {
  return requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_PROJECT_NAME, "SEMAPHORE_WORKSPACES_PROJECT_NAME");
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page carrying the administrator session.
 *   survey: the survey answers of the `workspace` template.
 *   label: the persona label the assertion messages name.
 *
 * Returns:
 *   The JSON object the operation printed as its last line.
 */
async function workspaceOperation(shared, page, survey, label) {
  const project = await namedProject(shared, page, workspacesProjectName());
  const template = await namedTemplate(shared, page, project.id, WORKSPACE_TEMPLATE);
  const what = `${label}: workspace ${survey.WORKSPACE_ACTION} of ws-${survey.WORKSPACE}`;
  const run = await runTemplate(shared, page, project.id, template.id, survey, WORKSPACE_RUN_MS, what);
  expectSucceeded(run, what);
  try {
    return JSON.parse(lastLine(run.lines));
  } catch (error) {
    throw new Error(`${what}: the last output line is no JSON object; output tail:\n${outputTail(run.lines)}`, {
      cause: error,
    });
  }
}

/**
 * Returns:
 *   An empty workspace fixture with a fresh workspace id, for `openWorkspace`
 *   to fill and `closeWorkspace` to clean up whatever an open left.
 */
function workspaceFixture() {
  return { workspace: crypto.randomUUID(), applying: false, destroyed: false, giteaToken: null, repository: false, staged: [] };
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   browser: the Playwright browser.
 *   fixture: a result of `workspaceFixture`, filled with the administrator
 *     `context` and `page`, the `result` of apply and the store's Gitea token.
 *   targets: `WORKSPACE_TARGETS`, comma-separated `<host>:<port>` pairs, empty for none.
 *   label: the persona label the assertion messages name.
 */
async function openWorkspace(shared, browser, fixture, targets, label) {
  skipWithoutPlatformHost();
  fixture.context = await browser.newContext({ ignoreHTTPSErrors: true });
  fixture.page = await fixture.context.newPage();
  await shared.signInViaBreakglassApi(fixture.page, shared.env.breakglassUsername, shared.env.breakglassPassword, label);
  fixture.applying = true;
  fixture.result = await workspaceOperation(
    shared,
    fixture.page,
    {
      WORKSPACE: fixture.workspace,
      WORKSPACE_ACTION: "apply",
      WORKSPACE_CORE_VERSION: LATEST_CORE_VERSION,
      WORKSPACE_TARGETS: targets,
    },
    label,
  );
  expect(fixture.result.workspace, `${label}: apply must print the result of ws-${fixture.workspace}`).toBe(fixture.workspace);
  expect(fixture.result.alias, `${label}: apply must name the workspace ws-${fixture.workspace}`).toBe(`ws-${fixture.workspace}`);
  fixture.giteaToken = await storeGiteaToken(shared, fixture, label);
  await createWorkspaceRepository(fixture, label);
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `openWorkspace`.
 *   label: the persona label the assertion messages name.
 */
async function destroyWorkspace(shared, fixture, label) {
  const result = await workspaceOperation(
    shared,
    fixture.page,
    { WORKSPACE: fixture.workspace, WORKSPACE_ACTION: "destroy" },
    label,
  );
  fixture.destroyed = true;
  expect(
    { ...result, stopped_tasks: Number.isInteger(result.stopped_tasks) && result.stopped_tasks >= 0 },
    `${label}: destroy must print the destroyed result of ws-${fixture.workspace} with its count of stopped tasks`,
  ).toEqual({ destroyed: true, stopped_tasks: true, workspace: fixture.workspace });
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `openWorkspace`, or the partial fixture a failed open left.
 *   label: the persona label the assertion messages name.
 */
async function closeWorkspace(shared, fixture, label) {
  const failures = [];
  if ((fixture.staged || []).length > 0) {
    try {
      const token = await storeVaultToken(fixture.context);
      for (const path of fixture.staged) {
        try {
          await vaultDestroy(fixture.context, token, TENANT_MOUNT, path);
        } catch (error) {
          failures.push(error);
        }
      }
    } catch (error) {
      failures.push(error);
    }
  }
  if (fixture.repository) {
    try {
      const response = await http(fixture.context, "DELETE", repositoryUrl(fixture.workspace), {
        headers: giteaHeaders(fixture.giteaToken),
      });
      await expectStatus(response, [204, 404], `${label}: the delete of the repository of ws-${fixture.workspace}`);
    } catch (error) {
      failures.push(error);
    }
  }
  if (fixture.applying && !fixture.destroyed) {
    try {
      await destroyWorkspace(shared, fixture, label);
    } catch (error) {
      failures.push(error);
    }
  }
  if (fixture.context) {
    await fixture.context.close();
  }
  if (failures.length > 0) {
    throw new AggregateError(
      failures,
      `${label}: the cleanup of ws-${fixture.workspace} failed: ${failures.map((failure) => failure.message).join("; ")}`,
    );
  }
}

/**
 * Args:
 *   shared: the role's shared helpers.
 */
function requireWorkspaces(shared) {
  skipUnlessWorkspaces();
  shared.skipUnlessServiceEnabled("sso");
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   browser: the Playwright browser.
 *   label: the persona label the assertion messages name.
 *   targets: `WORKSPACE_TARGETS` of the apply.
 *   body: async function receiving the fixture and `cleanup(step)`; the
 *     steps run in reverse order after the body, also when it fails, and
 *     the workspace is closed last.
 *
 * Returns:
 *   What the body returned.
 */
async function withWorkspace(shared, browser, label, targets, body) {
  const fixture = workspaceFixture();
  const steps = [];
  let failure;
  let value;
  try {
    await openWorkspace(shared, browser, fixture, targets, label);
    value = await body(fixture, (step) => steps.push(step));
  } catch (error) {
    failure = error;
  }
  const problems = [];
  for (const step of steps.reverse()) {
    try {
      await step();
    } catch (error) {
      problems.push(error);
    }
  }
  try {
    await closeWorkspace(shared, fixture, label);
  } catch (error) {
    problems.push(error);
  }
  const summary = problems.map((problem) => String(problem && problem.message).split("\n")[0]).join("; ");
  if (failure) {
    if (problems.length > 0) {
      console.warn(`${label}: the cleanup of ws-${fixture.workspace} after the failure also failed: ${summary}`);
    }
    throw failure;
  }
  if (problems.length > 0) {
    throw new AggregateError(problems, `${label}: the cleanup of ws-${fixture.workspace} failed: ${summary}`);
  }
  return value;
}

function openbaoOrigin() {
  return new URL(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL")).origin;
}

/**
 * Args:
 *   context: a browser context.
 *   path: a path below the Playwright mount the Playwright policy reads.
 *
 * Returns:
 *   The fields stored there, read with the Playwright AppRole whose token is revoked afterwards.
 */
async function playwrightRead(context, path) {
  const login = await http(context, "POST", `${openbaoOrigin()}/v1/auth/approle/login`, {
    data: {
      role_id: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_ROLE_ID, "OPENBAO_PLAYWRIGHT_ROLE_ID"),
      secret_id: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SECRET_ID, "OPENBAO_PLAYWRIGHT_SECRET_ID"),
    },
  });
  await expectStatus(login, [200], "the OpenBao AppRole login of the Playwright AppRole");
  const token = (await login.json()).auth.client_token;
  try {
    const mount = requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_MOUNT, "OPENBAO_PLAYWRIGHT_MOUNT");
    const data = await vaultRead(context, token, mount, path);
    expect(data, `OpenBao must hand the Playwright AppRole ${mount}/${path}`).not.toBeNull();
    return data;
  } finally {
    const revoke = await http(context, "POST", `${openbaoOrigin()}/v1/auth/token/revoke-self`, {
      headers: { "X-Vault-Token": token },
    });
    await expectStatus(revoke, [204], "the revocation of the Playwright AppRole token");
  }
}

/**
 * Args:
 *   context: a browser context.
 *
 * Returns:
 *   An OpenBao token of the store AppRole, the identity the store writes tenant secrets with.
 */
async function storeVaultToken(context) {
  const response = await http(context, "POST", `${openbaoOrigin()}/v1/auth/approle/login`, {
    data: await playwrightRead(
      context,
      requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_STORE_PATH, "OPENBAO_PLAYWRIGHT_STORE_PATH"),
    ),
  });
  await expectStatus(response, [200], "the OpenBao AppRole login of the store");
  return (await response.json()).auth.client_token;
}

/**
 * Args:
 *   context: a browser context.
 *   token: an OpenBao token.
 *   mount: the KV v2 mount.
 *   path: the secret path below the mount.
 *
 * Returns:
 *   The data of the newest version, null when the path holds none.
 */
async function vaultRead(context, token, mount, path) {
  const response = await http(context, "GET", `${openbaoOrigin()}/v1/${mount}/data/${path}`, {
    headers: { "X-Vault-Token": token },
  });
  await expectStatus(response, [200, 404], `the OpenBao read of ${mount}/${path}`);
  return response.status() === 404 ? null : (await response.json()).data.data;
}

/**
 * Args:
 *   context: a browser context.
 *   token: an OpenBao token.
 *   mount: the KV v2 mount.
 *   path: the secret path below the mount.
 *   data: the fields to write.
 *   options: the KV v2 write options, `CREATE_ONLY` for a write that
 *     refuses an existing secret; none by default.
 */
async function vaultWrite(context, token, mount, path, data, options) {
  const response = await http(context, "POST", `${openbaoOrigin()}/v1/${mount}/data/${path}`, {
    headers: { "X-Vault-Token": token },
    data: options ? { data, options } : { data },
  });
  await expectStatus(response, [200, 204], `the OpenBao write of ${mount}/${path}`);
}

/**
 * Args:
 *   context: a browser context.
 *   token: an OpenBao token.
 *   mount: the KV v2 mount.
 *   path: the secret path below the mount, removed with every version.
 */
async function vaultDestroy(context, token, mount, path) {
  const response = await http(context, "DELETE", `${openbaoOrigin()}/v1/${mount}/metadata/${path}`, {
    headers: { "X-Vault-Token": token },
  });
  await expectStatus(response, [204, 404], `the OpenBao delete of ${mount}/${path}`);
}

function giteaHeaders(token) {
  return { Authorization: `token ${token}` };
}

function giteaApi() {
  return `${new URL(requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_GITEA_URL, "SEMAPHORE_WORKSPACES_GITEA_URL")).origin}/api/v1`;
}

function workspacesOwner() {
  return requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_GITEA_OWNER, "SEMAPHORE_WORKSPACES_GITEA_OWNER");
}

/**
 * Args:
 *   workspace: the workspace id.
 *
 * Returns:
 *   The Gitea API URL of the workspace repository.
 */
function repositoryUrl(workspace) {
  return `${giteaApi()}/repos/${workspacesOwner()}/ws-${workspace}`;
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the fixture of `openWorkspace`.
 *   label: the persona label the assertion messages name.
 *
 * Returns:
 *   The store's Gitea token from OpenBao; a store whose rotation never ran
 *   gets one from a run of `rotate store credentials` first.
 */
async function storeGiteaToken(shared, fixture, label) {
  let stored = await vaultRead(fixture.context, await storeVaultToken(fixture.context), PLATFORM_MOUNT, STORE_GITEA_PATH);
  if (stored === null) {
    const project = await namedProject(shared, fixture.page, workspacesProjectName());
    const template = await namedTemplate(shared, fixture.page, project.id, ROTATION_TEMPLATE);
    const what = `${label}: ${ROTATION_TEMPLATE}`;
    expectSucceeded(await runTemplate(shared, fixture.page, project.id, template.id, {}, ROTATION_RUN_MS, what), what);
    stored = await vaultRead(fixture.context, await storeVaultToken(fixture.context), PLATFORM_MOUNT, STORE_GITEA_PATH);
  }
  expect(
    Boolean(stored && stored.token),
    `${label}: OpenBao must hold the store's Gitea token at ${PLATFORM_MOUNT}/${STORE_GITEA_PATH}`,
  ).toBe(true);
  return stored.token;
}

/**
 * Args:
 *   fixture: the fixture of `openWorkspace`, carrying `giteaToken` and `result`.
 *   label: the persona label the assertion messages name.
 */
async function createWorkspaceRepository(fixture, label) {
  const url = repositoryUrl(fixture.workspace);
  const owner = workspacesOwner();
  const name = `ws-${fixture.workspace}`;
  const created = await http(fixture.context, "POST", `${giteaApi()}/orgs/${owner}/repos`, {
    headers: giteaHeaders(fixture.giteaToken),
    data: { name, private: true, auto_init: true, default_branch: REPOSITORY_BRANCH },
  });
  await expectStatus(created, [201], `${label}: the store's creation of the repository ${owner}/${name}`);
  fixture.repository = true;
  const keyed = await http(fixture.context, "POST", `${url}/keys`, {
    headers: giteaHeaders(fixture.giteaToken),
    data: { title: `read ${name}`, key: fixture.result.read_key, read_only: true },
  });
  await expectStatus(keyed, [201], `${label}: the read key apply returned on ${owner}/${name}`);
}

/**
 * Args:
 *   parts: the buffers to hash, in order.
 *
 * Returns:
 *   Their SHA-256 digest.
 */
function sha256(...parts) {
  const hash = crypto.createHash("sha256");
  for (const part of parts) {
    hash.update(part);
  }
  return hash.digest();
}

/**
 * Args:
 *   values: the 5-bit values of the expanded prefix, the data and the checksum slots.
 *
 * Returns:
 *   The BIP 173 checksum state over them.
 */
function bech32Polymod(values) {
  let checksum = 1;
  for (const value of values) {
    const top = checksum >>> 25;
    checksum = ((checksum & 0x1ffffff) << 5) ^ value;
    BECH32_GENERATOR.forEach((generator, bit) => {
      if ((top >>> bit) & 1) {
        checksum ^= generator;
      }
    });
  }
  return checksum;
}

/**
 * Args:
 *   prefix: the human-readable part, lowercase.
 *   bytes: the payload.
 *
 * Returns:
 *   The Bech32 encoding age uses for recipients.
 */
function bech32Encode(prefix, bytes) {
  const words = [];
  let accumulator = 0;
  let bits = 0;
  for (const byte of bytes) {
    accumulator = (accumulator << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      words.push((accumulator >>> bits) & 31);
    }
    accumulator &= (1 << bits) - 1;
  }
  if (bits > 0) {
    words.push((accumulator << (5 - bits)) & 31);
  }
  const codes = [...prefix].map((character) => character.charCodeAt(0));
  const expanded = [...codes.map((code) => code >> 5), 0, ...codes.map((code) => code & 31)];
  const state = bech32Polymod([...expanded, ...words, 0, 0, 0, 0, 0, 0]) ^ 1;
  const checksum = [0, 1, 2, 3, 4, 5].map((index) => (state >>> (5 * (5 - index))) & 31);
  return `${prefix}1${[...words, ...checksum].map((word) => BECH32_CHARSET[word]).join("")}`;
}

/**
 * Returns:
 *   A fresh X25519 key pair as age uses it: `recipient`, the `age1...`
 *   string an Owner registers, and `privateKey`, the KeyObject that opens
 *   what was sealed to it.
 */
function ageIdentity() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("x25519");
  return { recipient: bech32Encode("age", rawX25519(publicKey)), privateKey };
}

function rawX25519(key) {
  const publicKey = key.type === "public" ? key : crypto.createPublicKey(key);
  return Buffer.from(publicKey.export({ format: "jwk" }).x, "base64url");
}

function hkdf(secret, salt, info, length) {
  return Buffer.from(crypto.hkdfSync("sha256", secret, salt, Buffer.from(info, "utf8"), length));
}

function chachaOpen(key, nonce, sealed) {
  const decipher = crypto.createDecipheriv("chacha20-poly1305", key, nonce, { authTagLength: AGE_TAG });
  decipher.setAuthTag(sealed.subarray(sealed.length - AGE_TAG));
  return Buffer.concat([decipher.update(sealed.subarray(0, sealed.length - AGE_TAG)), decipher.final()]);
}

/**
 * Args:
 *   file: a binary age v1 file sealed to one X25519 recipient.
 *   privateKey: the X25519 KeyObject of that recipient.
 *
 * Returns:
 *   The plaintext, after the header MAC and every payload chunk verified.
 */
function ageDecrypt(file, privateKey) {
  const text = file.toString("latin1");
  if (!text.startsWith(AGE_INTRO)) {
    throw new Error("the file carries no age v1 header");
  }
  const macAt = text.indexOf(AGE_MAC_LINE);
  const macEnd = text.indexOf("\n", macAt + 1);
  if (macAt < 0 || macEnd < 0) {
    throw new Error("the age header has no MAC line");
  }
  const stanzas = [];
  for (const line of text.slice(AGE_INTRO.length, macAt).split("\n")) {
    if (line.startsWith("-> ")) {
      stanzas.push({ args: line.slice(3).split(" "), body: [], open: true });
    } else if (stanzas.length > 0 && stanzas[stanzas.length - 1].open) {
      const stanza = stanzas[stanzas.length - 1];
      stanza.body.push(line);
      stanza.open = line.length === AGE_STANZA_COLUMNS;
    } else {
      throw new Error("the age header holds a line outside every stanza");
    }
  }
  if (stanzas.length !== 1 || stanzas[0].args[0] !== "X25519" || stanzas[0].args.length !== 2) {
    throw new Error(`the age header must hold exactly one X25519 stanza, it holds ${stanzas.map((stanza) => stanza.args[0]).join(", ")}`);
  }
  const ephemeral = Buffer.from(stanzas[0].args[1], "base64");
  const sharedSecret = crypto.diffieHellman({
    privateKey,
    publicKey: crypto.createPublicKey({ key: Buffer.concat([X25519_SPKI_PREFIX, ephemeral]), format: "der", type: "spki" }),
  });
  const wrapKey = hkdf(sharedSecret, Buffer.concat([ephemeral, rawX25519(privateKey)]), AGE_X25519_LABEL, AGE_KEY);
  const fileKey = chachaOpen(wrapKey, Buffer.alloc(12), Buffer.from(stanzas[0].body.join(""), "base64"));
  const mac = crypto.createHmac("sha256", hkdf(fileKey, Buffer.alloc(0), "header", AGE_KEY));
  mac.update(file.subarray(0, macAt + AGE_MAC_LINE.length - 1));
  if (!crypto.timingSafeEqual(mac.digest(), Buffer.from(text.slice(macAt + AGE_MAC_LINE.length, macEnd), "base64"))) {
    throw new Error("the age header MAC does not match");
  }
  const payload = file.subarray(macEnd + 1);
  const streamKey = hkdf(fileKey, payload.subarray(0, AGE_STREAM_NONCE), "payload", AGE_KEY);
  const sealed = payload.subarray(AGE_STREAM_NONCE);
  const chunks = [];
  for (let index = 0, offset = 0; offset < sealed.length || index === 0; index += 1, offset += AGE_CHUNK + AGE_TAG) {
    const nonce = Buffer.alloc(12);
    nonce.writeUIntBE(index, 5, 6);
    nonce[11] = offset + AGE_CHUNK + AGE_TAG >= sealed.length ? 1 : 0;
    chunks.push(chachaOpen(streamKey, nonce, sealed.subarray(offset, offset + AGE_CHUNK + AGE_TAG)));
  }
  return Buffer.concat(chunks);
}

/**
 * Args:
 *   archive: a ustar or pax tar.
 *
 * Returns:
 *   Every member as `{ name, type, data }`, pax headers applied and dropped.
 */
function readTar(archive) {
  const members = [];
  let pax = {};
  for (let offset = 0; offset + TAR_BLOCK <= archive.length; ) {
    const header = archive.subarray(offset, offset + TAR_BLOCK);
    if (header.every((byte) => byte === 0)) {
      break;
    }
    const field = (from, to) => header.subarray(from, to).toString("utf8").split("\0")[0];
    const size = parseInt(field(124, 136).trim() || "0", 8);
    const type = header[156] === 0 ? "0" : String.fromCharCode(header[156]);
    const data = archive.subarray(offset + TAR_BLOCK, offset + TAR_BLOCK + size);
    offset += TAR_BLOCK + Math.ceil(size / TAR_BLOCK) * TAR_BLOCK;
    if (type === "x") {
      pax = Object.fromEntries(
        data
          .toString("utf8")
          .split("\n")
          .filter((record) => record.includes("="))
          .map((record) => record.slice(record.indexOf(" ") + 1).split(/=(.*)/s).slice(0, 2)),
      );
      continue;
    }
    if (type === "g") {
      continue;
    }
    const prefix = field(345, 500);
    members.push({ name: pax.path || (prefix ? `${prefix}/${field(0, 100)}` : field(0, 100)), type, data });
    pax = {};
  }
  return members;
}

/**
 * Args:
 *   state: the 16 words of a Salsa20 state.
 *
 * Returns:
 *   The 64 keystream bytes of that state.
 */
function salsa20Block(state) {
  const x = Uint32Array.from(state);
  const rotate = (value, count) => (value << count) | (value >>> (32 - count));
  const quarter = (a, b, c, d) => {
    x[b] ^= rotate((x[a] + x[d]) | 0, 7);
    x[c] ^= rotate((x[b] + x[a]) | 0, 9);
    x[d] ^= rotate((x[c] + x[b]) | 0, 13);
    x[a] ^= rotate((x[d] + x[c]) | 0, 18);
  };
  for (let round = 0; round < SALSA20_DOUBLE_ROUNDS; round += 1) {
    quarter(0, 4, 8, 12);
    quarter(5, 9, 13, 1);
    quarter(10, 14, 2, 6);
    quarter(15, 3, 7, 11);
    quarter(0, 1, 2, 3);
    quarter(5, 6, 7, 4);
    quarter(10, 11, 8, 9);
    quarter(15, 12, 13, 14);
  }
  const block = Buffer.alloc(64);
  for (let word = 0; word < 16; word += 1) {
    block.writeUInt32LE((x[word] + state[word]) >>> 0, 4 * word);
  }
  return block;
}

/**
 * Args:
 *   key: the 32-byte key.
 *   nonce: the 8-byte nonce.
 *
 * Returns:
 *   A function that hands out the next `length` keystream bytes on each call.
 */
function salsa20(key, nonce) {
  const state = new Uint32Array(16);
  [0, 5, 10, 15].forEach((word, index) => {
    state[word] = SALSA20_SIGMA.readUInt32LE(4 * index);
  });
  for (let index = 0; index < 4; index += 1) {
    state[1 + index] = key.readUInt32LE(4 * index);
    state[11 + index] = key.readUInt32LE(16 + 4 * index);
  }
  state[6] = nonce.readUInt32LE(0);
  state[7] = nonce.readUInt32LE(4);
  let block = Buffer.alloc(0);
  return (length) => {
    const out = Buffer.alloc(length);
    for (let index = 0; index < length; index += 1) {
      if (block.length === 0) {
        block = salsa20Block(state);
        state[8] += 1;
        if (state[8] === 0) {
          state[9] += 1;
        }
      }
      out[index] = block[0];
      block = block.subarray(1);
    }
    return out;
  };
}

function decodeXml(text) {
  return text.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|lt|gt|amp|quot|apos);/g, (_, entity) => {
    if (entity.startsWith("#x")) {
      return String.fromCodePoint(parseInt(entity.slice(2), 16));
    }
    if (entity.startsWith("#")) {
      return String.fromCodePoint(parseInt(entity.slice(1), 10));
    }
    return XML_ENTITIES[entity];
  });
}

function encodeXml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/**
 * Args:
 *   file: a KDBX 3.1 database with AES-KDF, AES-256 and a Salsa20 inner stream,
 *     the format `keepassxc-cli import` writes.
 *   password: the database password.
 *
 * Returns:
 *   Every entry as a map of its string fields, protected fields decrypted.
 */
function readKdbx(file, password) {
  if (file.readUInt32LE(0) !== KDBX_SIGNATURE[0] || file.readUInt32LE(4) !== KDBX_SIGNATURE[1]) {
    throw new Error("the database carries no KeePass 2 signature");
  }
  const major = file.readUInt16LE(10);
  if (major !== KDBX_MAJOR) {
    throw new Error(`the database is KDBX ${major}, the reader opens KDBX ${KDBX_MAJOR}`);
  }
  const headers = new Map();
  let offset = 12;
  let id;
  do {
    id = file[offset];
    const size = file.readUInt16LE(offset + 1);
    headers.set(id, file.subarray(offset + 3, offset + 3 + size));
    offset += 3 + size;
  } while (id !== KDBX_HEADER.end);
  const header = (name) => {
    const value = headers.get(KDBX_HEADER[name]);
    if (!value) {
      throw new Error(`the database header lacks ${name}`);
    }
    return value;
  };
  if (header("cipher").toString("hex") !== KDBX_AES256) {
    throw new Error(`the database cipher ${header("cipher").toString("hex")} is not AES-256`);
  }
  const transform = crypto.createCipheriv("aes-256-ecb", header("transformSeed"), null);
  transform.setAutoPadding(false);
  let key = sha256(sha256(Buffer.from(password, "utf8")));
  const rounds = Number(header("transformRounds").readBigUInt64LE(0));
  for (let round = 0; round < rounds; round += 1) {
    key = transform.update(key);
  }
  const decipher = crypto.createDecipheriv("aes-256-cbc", sha256(header("masterSeed"), sha256(key)), header("iv"));
  const plain = Buffer.concat([decipher.update(file.subarray(offset)), decipher.final()]);
  if (!plain.subarray(0, 32).equals(header("streamStartBytes"))) {
    throw new Error("the password does not open the database");
  }
  const blocks = [];
  for (let at = 32, index = 0; ; index += 1) {
    const size = plain.readUInt32LE(at + 36);
    if (plain.readUInt32LE(at) !== index) {
      throw new Error(`block ${index} of the database is out of order`);
    }
    if (size === 0) {
      break;
    }
    const data = plain.subarray(at + 40, at + 40 + size);
    if (!sha256(data).equals(plain.subarray(at + 4, at + 36))) {
      throw new Error(`block ${index} of the database fails its hash`);
    }
    blocks.push(data);
    at += 40 + size;
  }
  let xml = Buffer.concat(blocks);
  if (header("compression").readUInt32LE(0) === KDBX_GZIP) {
    xml = zlib.gunzipSync(xml);
  }
  if (header("innerStream").readUInt32LE(0) !== KDBX_SALSA20) {
    throw new Error("the database inner stream is not Salsa20");
  }
  const stream = salsa20(sha256(header("protectedStreamKey")), SALSA20_IV);
  const opened = xml
    .toString("utf8")
    .replace(/<Value\/>/g, "<Value></Value>")
    .replace(/<Value Protected="True"\/>/g, "<Value></Value>")
    .replace(/<Value Protected="True">([^<]*)<\/Value>/g, (_, sealed) => {
      const bytes = Buffer.from(sealed, "base64");
      const keystream = stream(bytes.length);
      return `<Value>${encodeXml(Buffer.from(bytes.map((byte, index) => byte ^ keystream[index])).toString("utf8"))}</Value>`;
    });
  return [...opened.matchAll(/<Entry>([\s\S]*?)<\/Entry>/g)].map(([, entry]) =>
    Object.fromEntries(
      [...entry.matchAll(/<String>\s*<Key>([^<]*)<\/Key>\s*<Value>([^<]*)<\/Value>\s*<\/String>/g)].map(([, name, value]) => [
        decodeXml(name),
        decodeXml(value),
      ]),
    ),
  );
}

function sshString(bytes) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(bytes.length);
  return Buffer.concat([length, bytes]);
}

function sshUint32(value) {
  const bytes = Buffer.alloc(4);
  bytes.writeUInt32BE(value);
  return bytes;
}

/**
 * Returns:
 *   `privateKey`, a fresh unencrypted ed25519 key in OpenSSH form that no
 *   host authorizes, and `publicLine`, its public half.
 */
function throwawaySshKey() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const pub = Buffer.from(publicKey.export({ format: "jwk" }).x, "base64url");
  const seed = Buffer.from(privateKey.export({ format: "jwk" }).d, "base64url");
  const type = Buffer.from(PINNED_KEY_TYPE);
  const blob = Buffer.concat([sshString(type), sshString(pub)]);
  const check = sshUint32(crypto.randomInt(2 ** 32));
  const section = Buffer.concat([
    check,
    check,
    sshString(type),
    sshString(pub),
    sshString(Buffer.concat([seed, pub])),
    sshString(Buffer.from("playwright")),
  ]);
  const padding = Buffer.from(Array.from({ length: (OPENSSH_BLOCK - (section.length % OPENSSH_BLOCK)) % OPENSSH_BLOCK }, (_, index) => index + 1));
  const none = sshString(Buffer.from("none"));
  const body = Buffer.concat([OPENSSH_MAGIC, none, none, sshString(Buffer.alloc(0)), sshUint32(1), sshString(blob), sshString(Buffer.concat([section, padding]))]);
  const lines = body.toString("base64").match(new RegExp(`.{1,${PEM_COLUMNS}}`, "g"));
  return {
    privateKey: `-----BEGIN OPENSSH PRIVATE KEY-----\n${lines.join("\n")}\n-----END OPENSSH PRIVATE KEY-----\n`,
    publicLine: `${PINNED_KEY_TYPE} ${blob.toString("base64")}`,
  };
}

/**
 * Args:
 *   fixture: the result of `openWorkspace`.
 *   privateKey: the workspace key, never logged.
 *   token: a store AppRole token of `storeVaultToken`; a fresh one when omitted.
 *
 * Returns:
 *   The `WORKSPACE_SSH_KEY` reference of the key the store wrote to
 *   tenant/ws-<id>/ssh; `closeWorkspace` destroys it.
 */
async function stageWorkspaceKey(fixture, privateKey, token) {
  const path = `ws-${fixture.workspace}/${WORKSPACE_KEY_PATH}`;
  fixture.staged.push(path);
  await vaultWrite(fixture.context, token || (await storeVaultToken(fixture.context)), TENANT_MOUNT, path, {
    [WORKSPACE_KEY_FIELD]: privateKey,
  });
  return { openbao: `${TENANT_MOUNT}/${path}#${WORKSPACE_KEY_FIELD}` };
}

function randomText(alphabet, length) {
  return Array.from({ length }, () => alphabet[crypto.randomInt(alphabet.length)]).join("");
}

/**
 * Args:
 *   make: returns a fresh candidate.
 *   valid: whether a candidate holds.
 *   what: the value the failure message names.
 *
 * Returns:
 *   The first of `PASSWORD_ATTEMPTS` candidates that holds.
 */
function untilValid(make, valid, what) {
  for (let attempt = 0; attempt < PASSWORD_ATTEMPTS; attempt += 1) {
    const value = make();
    if (valid(value)) {
      return value;
    }
  }
  throw new Error(`${what}: ${PASSWORD_ATTEMPTS} generated values all failed their check`);
}

const GENERATORS = {
  random_hex: () => crypto.randomBytes(64).toString("hex"),
  random_hex_32: () => crypto.randomBytes(32).toString("hex"),
  random_hex_16: () => crypto.randomBytes(16).toString("hex"),
  sha256: () => crypto.createHash("sha256").update(crypto.randomBytes(32)).digest("hex"),
  sha1: () => crypto.createHash("sha1").update(crypto.randomBytes(20)).digest("hex"),
  strong_password: () =>
    untilValid(() => randomText(`${ALPHANUMERIC}${STRONG_MARKS}`, STRONG_PASSWORD_LENGTH), (value) => STRONG_PASSWORD.test(value), "strong_password"),
  bcrypt: () =>
    [...`${BCRYPT_PREFIX}${randomText(BCRYPT_ALPHABET, BCRYPT_BODY)}`].map((char) => (char === "$" ? randomText(LOWER_ALNUM, 1) : char)).join(""),
  alphanumeric: () => randomText(ALPHANUMERIC, ALPHANUMERIC_LENGTH),
  sk_prefixed: () => `sk-${randomText(ALPHANUMERIC, SK_LENGTH)}`,
  base64_prefixed_32: () => `base64:${crypto.randomBytes(32).toString("base64")}`,
  rsa_pem_2048: () =>
    crypto.generateKeyPairSync("rsa", { modulusLength: 2048, publicExponent: 65537 }).privateKey.export({ type: "pkcs1", format: "pem" }),
  ssh_ed25519: () => throwawaySshKey().privateKey,
  undefined: () => "undefined",
};

/**
 * Args:
 *   kind: a generator kind of the credential schema.
 *   what: the credential the failure message names.
 *
 * Returns:
 *   A fresh value of the kind, as `ValueGenerator.generate_value` makes it.
 */
function generated(kind, what) {
  if (!Object.hasOwn(GENERATORS, kind)) {
    throw new Error(`${what}: the workspace fixture has no generator for the kind ${kind}`);
  }
  return GENERATORS[kind]();
}

function userPassword() {
  return untilValid(
    () => {
      const body = [...randomText(`${ALPHANUMERIC}${USER_MARKS}`, USER_PASSWORD_LENGTH)];
      body[0] = randomText(ALPHANUMERIC, 1);
      body[1 + crypto.randomInt(USER_PASSWORD_LENGTH - 1)] = randomText(USER_MARKS, 1);
      return body.join("");
    },
    (value) => USER_PASSWORD.test(value),
    "the shell-safe user password",
  );
}

/**
 * Args:
 *   user: a `users` entry of the credential schema.
 *
 * Returns:
 *   A password of the user's kind, the shell-safe one without a kind, that
 *   passes the user's `validation`.
 */
function userValue(user) {
  const validation = user.validation ? new RegExp(user.validation) : null;
  return untilValid(
    () => (user.algorithm ? generated(user.algorithm, user.path) : userPassword()),
    (value) => !validation || validation.test(value),
    `user ${user.name}`,
  );
}

/**
 * Args:
 *   roles: the roles a deploy names.
 *
 * Returns:
 *   `credentials` and `users` of the credential schema the deploy fixture
 *   rendered for these roles, each path and each user once.
 */
function credentialSchema(roles) {
  const rendered = JSON.parse(requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_CREDENTIALS_JSON, "SEMAPHORE_WORKSPACE_CREDENTIALS_JSON"));
  const credentials = new Map();
  const users = new Map();
  for (const role of roles) {
    expect(rendered[role], `SEMAPHORE_WORKSPACE_CREDENTIALS_JSON must carry the credential schema of ${role}`).toBeTruthy();
    rendered[role].credentials.forEach((entry) => credentials.set(entry.path, entry));
    rendered[role].users.forEach((user) => users.set(user.name, user));
  }
  return { credentials: [...credentials.values()], users: [...users.values()] };
}

function setPath(node, keys, value) {
  const [head, ...rest] = keys;
  if (rest.length === 0) {
    node[head] = value;
    return;
  }
  node[head] = node[head] || {};
  setPath(node[head], rest, value);
}

function isMapping(node) {
  return Boolean(node) && typeof node === "object" && !Array.isArray(node);
}

/**
 * Args:
 *   base: host variables.
 *   extra: host variables merged on top; mappings merge key by key, any other value replaces.
 *
 * Returns:
 *   The merged variables.
 */
function mergeVars(base, extra) {
  const merged = { ...base };
  for (const [key, value] of Object.entries(extra)) {
    merged[key] = isMapping(merged[key]) && isMapping(value) ? mergeVars(merged[key], value) : value;
  }
  return merged;
}

/**
 * Args:
 *   fixture: the result of `openWorkspace`.
 *   roles: the roles the deploy names.
 *   token: a store AppRole token of `storeVaultToken`.
 *
 * Returns:
 *   `vars`, the `applications` credentials and `users` passwords as typed
 *   references, and `adminPassword`, the platform administrator's password,
 *   kept in memory and never logged. Every value is generated here and
 *   written create-only below tenant/ws-<id>/, the way the store writes a
 *   workspace's credentials; a `plain` one stays an empty string.
 *   `closeWorkspace` destroys every path.
 */
async function stageCredentials(fixture, roles, token) {
  const { credentials, users } = credentialSchema(roles);
  const stage = async (path, field, value) => {
    const full = `ws-${fixture.workspace}/${path}`;
    fixture.staged.push(full);
    await vaultWrite(fixture.context, token, TENANT_MOUNT, full, { [field]: value }, CREATE_ONLY);
    return { openbao: `${TENANT_MOUNT}/${full}#${field}` };
  };
  const vars = { applications: {}, users: {} };
  for (const entry of credentials) {
    const value = () =>
      entry.algorithm === DEFAULT_KIND ? Buffer.from(entry.default_b64, "base64").toString("utf8") : generated(entry.algorithm, entry.path);
    const node = entry.algorithm === PLAIN_KIND ? "" : await stage(entry.path, entry.field, value());
    setPath(vars.applications, [entry.application, "secrets", "credentials", ...entry.key.split(".")], node);
  }
  let adminPassword = null;
  for (const user of users) {
    const value = userValue(user);
    vars.users[user.name] = { password: await stage(user.path, user.field, value) };
    if (user.name === ADMIN_USER) {
      adminPassword = value;
    }
  }
  return { vars, adminPassword };
}

/**
 * Args:
 *   context: a browser context.
 *
 * Returns:
 *   The private half of the workspace fixture key, the one key the shared
 *   target authorizes for workspaces, read with the Playwright AppRole; never logged.
 */
async function fixtureWorkspaceKey(context) {
  const path = requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_FIXTURE_KEY_PATH, "SEMAPHORE_WORKSPACE_FIXTURE_KEY_PATH");
  const key = (await playwrightRead(context, path))[WORKSPACE_KEY_FIELD];
  expect(typeof key === "string" && key.length > 0, `OpenBao must hold the workspace fixture key at ${path}#${WORKSPACE_KEY_FIELD}`).toBe(true);
  return key;
}

/**
 * Returns:
 *   The host variables of the shared target as the deploy fixture committed
 *   them, so a workspace deploy keeps the target's root login and keys.
 */
function sharedTargetVars() {
  const vars = JSON.parse(requireDotenvValue(process.env.SEMAPHORE_DEPLOY_TARGET_VARS_JSON, "SEMAPHORE_DEPLOY_TARGET_VARS_JSON"));
  const keys = ((vars.users || {}).root || {}).authorized_keys || [];
  expect(
    keys.length,
    "SEMAPHORE_DEPLOY_TARGET_VARS_JSON must carry the root keys of the shared target; a deploy without them would lock the target",
  ).toBeGreaterThan(0);
  return vars;
}

/**
 * Args:
 *   fixture: the result of `openWorkspace`.
 *   path: the file path in the workspace repository.
 *   text: the file content.
 *   label: the persona label the assertion messages name.
 *
 * Returns:
 *   The commit main points at after the file landed.
 */
async function commitWorkspaceFile(fixture, path, text, label) {
  const repository = repositoryUrl(fixture.workspace);
  const headers = giteaHeaders(fixture.giteaToken);
  const where = `${workspacesOwner()}/ws-${fixture.workspace}`;
  const created = await http(fixture.context, "POST", `${repository}/contents/${path}`, {
    headers,
    data: { content: Buffer.from(text, "utf8").toString("base64"), message: `playwright: ${path}`, branch: REPOSITORY_BRANCH },
  });
  await expectStatus(created, [201], `${label}: the commit of ${path} to ${where}`);
  const branch = await http(fixture.context, "GET", `${repository}/branches/${REPOSITORY_BRANCH}`, { headers });
  await expectStatus(branch, [200], `${label}: the read of ${REPOSITORY_BRANCH} of ${where}`);
  return (await branch.json()).commit.id;
}

/**
 * Args:
 *   fixture: the result of `openWorkspace`.
 *   host: the address of the one host.
 *   roles: the roles whose groups hold the host.
 *   hostVars: the variables of the host merged into the shared target's
 *     own and its login by `mergeVars`; `WORKSPACE_SSH_KEY` is set last.
 *   reference: the `WORKSPACE_SSH_KEY` reference of `stageWorkspaceKey`.
 *   label: the persona label the assertion messages name.
 *
 * Returns:
 *   The commit of the workspace inventory that lists the host.
 */
function commitInventory(fixture, host, roles, hostVars, reference, label) {
  const vars = { ...mergeVars({ ...sharedTargetVars(), ansible_user: TARGET_LOGIN }, hostVars), [WORKSPACE_KEY_VAR]: reference };
  const inventory = {
    all: {
      hosts: { [host]: vars },
      children: Object.fromEntries(roles.map((role) => [role, { hosts: { [host]: {} } }])),
    },
  };
  return commitWorkspaceFile(fixture, WORKSPACE_INVENTORY, `${JSON.stringify(inventory, null, 2)}\n`, label);
}

/**
 * Returns:
 *   `name` and IPv4 `address` of the shared target, the address a workspace lists in WORKSPACE_TARGETS.
 */
async function sharedTargetAddress() {
  const name = requireDotenvValue(process.env.SEMAPHORE_DEPLOY_TARGET_HOST, "SEMAPHORE_DEPLOY_TARGET_HOST");
  const { address } = await dns.promises.lookup(name, { family: 4 });
  return { name, address };
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page carrying the administrator session.
 *
 * Returns:
 *   `name` and IPv4 `address` of the shared target, and `hostKey`, its
 *   `<type> <base64>` key as DEPLOY_KNOWN_HOSTS of the Deploy project pins it.
 */
async function sharedTarget(shared, page) {
  const { name, address } = await sharedTargetAddress();
  const project = await namedProject(
    shared,
    page,
    requireDotenvValue(process.env.SEMAPHORE_DEPLOY_PROJECT_NAME, "SEMAPHORE_DEPLOY_PROJECT_NAME"),
  );
  const environments = await shared.api(page, "GET", `/project/${project.id}/environment`);
  const pinned = environments
    .flatMap((environment) => String(JSON.parse(environment.env || "{}").DEPLOY_KNOWN_HOSTS || "").split("\n"))
    .map((line) => line.trim().split(/\s+/))
    .filter(([hosts, , key]) => key && hosts.split(",").some((host) => [name, address].includes(host.replace(/^\[([^\]]+)\]:\d+$/, "$1"))));
  const line = pinned.find(([, type]) => type === PINNED_KEY_TYPE) || pinned[0];
  expect(line, `the Deploy project must pin a host key of the shared target ${name} (${address}) in DEPLOY_KNOWN_HOSTS`).toBeTruthy();
  return { name, address, hostKey: `${line[1]} ${line[2]}` };
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `openWorkspace`, its targets listing the shared target's SSH port.
 *   options: `roles`, the roles to deploy, and `hostVars`, see `commitInventory`.
 *   label: the persona label the assertion messages name.
 *
 * Returns:
 *   `run`, the finished `deploy` task, which has to succeed, `lines`, its
 *   output without colour, `target` of `sharedTarget`, `commit` of the
 *   inventory, `request`, the API context of the fixture, and the deployed
 *   Keycloak's `baseUrl`, app `realm`, master `adminUsername` and
 *   `adminPassword`, the platform administrator's password this call
 *   generated, never logged. The workspace fixture key signs in; one store
 *   AppRole token stages it and the credentials, `closeWorkspace` destroys them.
 */
async function deployToSharedTarget(shared, fixture, options, label) {
  const target = await sharedTarget(shared, fixture.page);
  const token = await storeVaultToken(fixture.context);
  const reference = await stageWorkspaceKey(fixture, await fixtureWorkspaceKey(fixture.context), token);
  const staged = await stageCredentials(fixture, options.roles, token);
  const commit = await commitInventory(fixture, target.address, options.roles, mergeVars(staged.vars, options.hostVars || {}), reference, label);
  const identity = fixture.result.templates.deploy;
  const what = `${label}: deploy of ${options.roles.join(",")} by ws-${fixture.workspace} to ${target.name} (${target.address})`;
  expect(identity, `${what}: apply must return the deploy template`).toBeTruthy();
  const template = await shared.api(fixture.page, "GET", `/project/${identity.project_id}/templates/${identity.template_id}`);
  const environment = await shared.api(fixture.page, "GET", `/project/${identity.project_id}/environment/${template.environment_id}`);
  const zone = JSON.parse(environment.env || "{}").WORKSPACE_DNS_ZONE;
  expect(Boolean(zone), `${what}: the deploy environment must name WORKSPACE_DNS_ZONE`).toBe(true);
  const keycloak = JSON.parse(requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_KEYCLOAK_JSON, "SEMAPHORE_WORKSPACE_KEYCLOAK_JSON"));
  const run = await runTemplate(
    shared,
    fixture.page,
    identity.project_id,
    identity.template_id,
    { ...DEPLOY_ORDER, HOST: target.address, HOST_KEY: target.hostKey, ROLES: options.roles.join(","), INVENTORY_COMMIT: commit },
    DEPLOY_RUN_MS,
    what,
  );
  expectSucceeded(run, what);
  return {
    run,
    lines: run.lines.map(bare),
    target,
    commit,
    request: fixture.context.request,
    baseUrl: `https://${keycloak.host_label}.${DEPLOY_ORDER.DNS_LABEL}.ws-${fixture.workspace}.${zone}`,
    realm: keycloak.realm,
    adminUsername: keycloak.admin_username,
    adminPassword: staged.adminPassword,
  };
}

module.exports = {
  DEPLOY_ORDER,
  DEPLOY_RUN_MS,
  ageDecrypt,
  ageIdentity,
  awaitTask,
  bare,
  closeWorkspace,
  commitInventory,
  commitWorkspaceFile,
  deployToSharedTarget,
  destroyWorkspace,
  expectLockedTemplate,
  expectRefused,
  expectStatus,
  expectSucceeded,
  fixtureWorkspaceKey,
  giteaHeaders,
  http,
  lastLine,
  namedProject,
  namedTemplate,
  namedTemplates,
  openWorkspace,
  outputTail,
  probeLines,
  readKdbx,
  readTar,
  repositoryUrl,
  requireWorkspaces,
  runProbe,
  runTemplate,
  openbaoOrigin,
  sharedTarget,
  sharedTargetAddress,
  skipUnlessWorkspaces,
  skipWithoutPlatformHost,
  stageWorkspaceKey,
  startTask,
  storeVaultToken,
  surveyOf,
  throwawaySshKey,
  vaultDestroy,
  vaultRead,
  vaultWrite,
  withWorkspace,
  workspaceFixture,
  workspacesOwner,
};
