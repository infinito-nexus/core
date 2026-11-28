const crypto = require("node:crypto");
const { expect } = require("@playwright/test");
const { resolveTimeout } = require("../../timeouts");
const { requireDotenvValue } = require("./dotenv");

const TASK_FINISHED = new Set(["success", "error", "stopped", "rejected"]);
const WORKSPACE_TEMPLATE = "workspace";
const WORKSPACE_RUN_MS = 30 * 60_000;
const WORKSPACE_RESULT_LINE = /^\{"(?:alias|destroyed)"/;
const ANSI = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*[A-Za-z]`, "g");
const REQUEST_MS = 30_000;
const IPV4_NETWORK = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/;
const SMALLEST_TARGET_PREFIX = 30;

/**
 * Args:
 *   raw: the raw value of the variable.
 *   name: the variable name the error names.
 *
 * Returns:
 *   The boolean the dotenv flag carries; anything but "true" or "false" throws.
 */
function strictFlag(raw, name) {
  const value = requireDotenvValue(raw, name);
  if (value !== "true" && value !== "false") {
    throw new Error(`${name} must be "true" or "false", got ${JSON.stringify(value)}`);
  }
  return value === "true";
}

/**
 * Args:
 *   workspace: the workspace id.
 *   action: the WORKSPACE_ACTION of the `workspace` template.
 *
 * Returns:
 *   The survey answers of that action; apply runs the latest core without
 *   targets and without the platform provider secrets.
 */
function workspaceSurvey(workspace, action) {
  return action === "apply"
    ? {
        WORKSPACE: workspace,
        WORKSPACE_ACTION: action,
        WORKSPACE_CORE_VERSION: "latest",
        WORKSPACE_TARGETS: "",
        WORKSPACE_PLATFORM_TOKENS: "false",
      }
    : { WORKSPACE: workspace, WORKSPACE_ACTION: action };
}

/**
 * Args:
 *   request: a Playwright request context, signed in by this call.
 *   account: `baseUrl`, `username` and `password` of the Semaphore break-glass account.
 *   projectName: the Semaphore project the session works in.
 *   templateName: the template of that project the session runs.
 *
 * Returns:
 *   `call(method, route, data)`, which parses the answer and fails on a status
 *   that is not ok, with the `projectId` and `templateId` of the named template.
 */
async function breakglassSession(request, account, projectName, templateName) {
  const call = async (method, route, data) => {
    const response = await request.fetch(`${account.baseUrl}/api${route}`, {
      method,
      data,
      failOnStatusCode: false,
      timeout: resolveTimeout(REQUEST_MS),
    });
    expect(response.ok(), `Semaphore ${method} /api${route} answered ${response.status()}`).toBe(true);
    const body = await response.text();
    return body ? JSON.parse(body) : null;
  };
  const login = await request.post(`${account.baseUrl}/api/auth/login`, {
    data: { auth: account.username, password: account.password },
    failOnStatusCode: false,
    timeout: resolveTimeout(REQUEST_MS),
  });
  expect(login.status(), "Semaphore must sign the break-glass admin in").toBe(204);
  const project = (await call("GET", "/projects")).find((candidate) => candidate.name === projectName);
  expect(project, `Semaphore must hold the project ${projectName}`).toBeTruthy();
  const template = (await call("GET", `/project/${project.id}/templates`)).find(
    (candidate) => candidate.name === templateName,
  );
  expect(template, `${projectName} must hold the template ${templateName}`).toBeTruthy();
  return { call, projectId: project.id, templateId: template.id };
}

/**
 * Args:
 *   sem: a session of `breakglassSession`.
 *   environment: the survey answers, null for a task without any.
 *   runMs: the longest the task may run, before timeout scaling.
 *   intervalMs: the interval between two status reads.
 *   what: the task the failure message names.
 *
 * Returns:
 *   `id`, `status` and the output `lines` of the finished task.
 */
async function runTemplateTask(sem, environment, runMs, intervalMs, what) {
  const task = await sem.call("POST", `/project/${sem.projectId}/tasks`, {
    template_id: sem.templateId,
    ...(environment ? { environment: JSON.stringify(environment) } : {}),
  });
  let state;
  await expect
    .poll(
      async () => {
        state = await sem.call("GET", `/project/${sem.projectId}/tasks/${task.id}`);
        return TASK_FINISHED.has(state.status);
      },
      { timeout: resolveTimeout(runMs), intervals: [intervalMs], message: `${what} task ${task.id} must finish` },
    )
    .toBe(true);
  const lines = (await sem.call("GET", `/project/${sem.projectId}/tasks/${task.id}/output`)).map((line) => line.output);
  return { id: task.id, status: state.status, lines };
}

/**
 * Args:
 *   sem: a session of `breakglassSession` on the `workspace` template.
 *   workspace: the workspace id.
 *   action: the WORKSPACE_ACTION to run.
 *   intervalMs: the interval between two status reads.
 *
 * Returns:
 *   The finished task, as `runTemplateTask` returns it.
 */
function runWorkspaceTask(sem, workspace, action, intervalMs) {
  return runTemplateTask(sem, workspaceSurvey(workspace, action), WORKSPACE_RUN_MS, intervalMs, `workspace ${action}`);
}

/**
 * Args:
 *   run: a finished workspace task.
 *   workspace: the workspace id.
 *   action: the WORKSPACE_ACTION the task ran.
 *
 * Returns:
 *   The run, once its success is asserted.
 */
function expectWorkspaceSuccess(run, workspace, action) {
  expect(run.status, `workspace ${action} task ${run.id} of ws-${workspace} must succeed; its output is in Semaphore`).toBe(
    "success",
  );
  return run;
}

/**
 * Args:
 *   request: a Playwright request context.
 *   openbao: `baseUrl`, `roleId` and `secretId` of the Playwright AppRole.
 *   mount: the KV v2 mount.
 *   path: the secret path below the mount.
 *
 * Returns:
 *   The `status` of the read and the `data` of the newest version, null
 *   unless it answered 200; the AppRole token is revoked afterwards.
 */
async function openbaoRead(request, openbao, mount, path) {
  const login = await request.post(`${openbao.baseUrl}/v1/auth/approle/login`, {
    data: { role_id: openbao.roleId, secret_id: openbao.secretId },
    failOnStatusCode: false,
    timeout: resolveTimeout(REQUEST_MS),
  });
  expect(login.status(), "OpenBao must accept the Playwright AppRole").toBe(200);
  const headers = { "X-Vault-Token": (await login.json()).auth.client_token };
  try {
    const read = await request.get(`${openbao.baseUrl}/v1/${mount}/data/${path}`, {
      headers,
      failOnStatusCode: false,
      timeout: resolveTimeout(REQUEST_MS),
    });
    return { status: read.status(), data: read.status() === 200 ? (await read.json()).data.data : null };
  } finally {
    const revoke = await request.post(`${openbao.baseUrl}/v1/auth/token/revoke-self`, {
      headers,
      failOnStatusCode: false,
      timeout: resolveTimeout(REQUEST_MS),
    });
    expect(revoke.status(), "the OpenBao token of the spec must be revoked").toBe(204);
  }
}

/**
 * Args:
 *   request: a Playwright request context, signed in to Semaphore by this call.
 *   openbao: `baseUrl`, `roleId`, `secretId` and `mount` of the Playwright AppRole.
 *   semaphore: `baseUrl` of Semaphore and the `breakglassPath` of its login below the mount.
 *   projectName: the Semaphore project the session works in.
 *   templateName: the template of that project the session runs.
 *
 * Returns:
 *   The `breakglassSession` of the break-glass login OpenBao holds.
 */
async function vaultedBreakglassSession(request, openbao, semaphore, projectName, templateName) {
  const login = await openbaoRead(request, openbao, openbao.mount, semaphore.breakglassPath);
  expect(login.status, `OpenBao must hand the Playwright AppRole the break-glass login ${openbao.mount}/${semaphore.breakglassPath}`).toBe(200);
  return breakglassSession(request, { ...semaphore, ...login.data }, projectName, templateName);
}

function sshString(bytes) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(bytes.length);
  return Buffer.concat([length, bytes]);
}

/**
 * Returns:
 *   A fresh ed25519 public key in OpenSSH form, whose private half nobody keeps.
 */
function sshEd25519PublicLine() {
  const { publicKey } = crypto.generateKeyPairSync("ed25519");
  const raw = Buffer.from(publicKey.export({ format: "jwk" }).x, "base64url");
  return `ssh-ed25519 ${Buffer.concat([sshString(Buffer.from("ssh-ed25519")), sshString(raw)]).toString("base64")}`;
}

/**
 * Args:
 *   networks: the decoded services.semaphore.workspaces.private_targets.
 *   label: the persona label the assertion message names.
 *
 * Returns:
 *   The last usable IPv4 address of the first network wide enough to hold
 *   one, an address workspace apply accepts as a target.
 */
function targetAddressIn(networks, label) {
  const network = networks
    .map((candidate) => IPV4_NETWORK.exec(candidate))
    .find((match) => match && Number(match[5]) <= SMALLEST_TARGET_PREFIX);
  expect(
    network,
    `${label}: services.semaphore.workspaces.private_targets must name an IPv4 network of /${SMALLEST_TARGET_PREFIX} or wider (names: ${networks.join(", ") || "none"})`,
  ).toBeTruthy();
  const base = network.slice(1, 5).reduce((sum, octet) => sum * 256 + Number(octet), 0);
  const size = 2 ** (32 - Number(network[5]));
  const last = base - (base % size) + size - 2;
  return [24, 16, 8, 0].map((shift) => Math.floor(last / 2 ** shift) % 256).join(".");
}

module.exports = {
  ANSI,
  TASK_FINISHED,
  WORKSPACE_RESULT_LINE,
  WORKSPACE_RUN_MS,
  WORKSPACE_TEMPLATE,
  breakglassSession,
  expectWorkspaceSuccess,
  openbaoRead,
  runTemplateTask,
  runWorkspaceTask,
  sshEd25519PublicLine,
  strictFlag,
  targetAddressIn,
  vaultedBreakglassSession,
  workspaceSurvey,
};
