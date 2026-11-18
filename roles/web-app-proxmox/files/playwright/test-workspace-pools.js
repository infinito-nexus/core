const { createHash, randomInt, randomUUID } = require("node:crypto");

const { test, expect } = require("@playwright/test");
const { decodeDotenvJsonList, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const {
  WORKSPACE_RUN_MS,
  WORKSPACE_TEMPLATE,
  expectWorkspaceSuccess,
  openbaoRead,
  runTemplateTask,
  vaultedBreakglassSession,
  workspaceSurvey,
} = require("./personas/utils/workspace");
const { proxmoxEnv, signInThroughGate, signInThroughRealm } = require("./proxmox-flow");
const { resolveTimeout } = require("./timeouts");

const APPLICATION_ID = "web-app-proxmox";
const APP_CONTROL_RUN_MS = 600_000;
const GUEST_BOOT_MS = 900_000;
const PVE_TASK_MS = 900_000;
const SEMAPHORE_POLL_MS = 10_000;
const PVE_POLL_MS = 3_000;
const WORKSPACE_ROLE = "InfinitoWorkspace";
const STORAGE_ROLE = "InfinitoWorkspaceStorage";
const BRIDGE_ROLE = "InfinitoWorkspaceBridge";
const TEMPLATE_ROLE = "InfinitoTemplateClone";
const OTHER_STORAGE = "local";
const VMID_FLOOR = 100_000;
const VMID_SPAN = 800_000;
const FIRST_BOOT_PHASES = ["image", "deployed"];
const FIRST_BOOT_FORMATS = {
  ssh_host_keys: /^[A-Z0-9]+:SHA256:[A-Za-z0-9+/]{43}(?:,[A-Z0-9]+:SHA256:[A-Za-z0-9+/]{43})*$/,
  machine_id: /^[0-9a-f]{64}$/,
  node_certificate: /^[0-9A-F]{2}(?::[0-9A-F]{2}){31}$/,
  root_ca: /^[0-9A-F]{2}(?::[0-9A-F]{2}){31}$/,
  root_hash: /^[0-9a-f]{64}$/,
};
const LIVE_CERTIFICATES = { node_certificate: "pve-ssl.pem", root_ca: "pve-root-ca.pem" };

const workspacesEnabled = process.env.SEMAPHORE_WORKSPACES_ENABLED === "true";
const vmFlavor = requireDotenvValue(process.env.PROXMOX_FLAVOR, "PROXMOX_FLAVOR") === "vm";

test.use({ ignoreHTTPSErrors: true });

function settings() {
  return {
    apiUrl: normalizeBaseUrl(requireDotenvValue(process.env.PROXMOX_API_URL, "PROXMOX_API_URL")),
    node: requireDotenvValue(process.env.PROXMOX_NODE, "PROXMOX_NODE"),
    tokenName: requireDotenvValue(process.env.PROXMOX_WORKSPACE_TOKEN_NAME, "PROXMOX_WORKSPACE_TOKEN_NAME"),
    storage: requireDotenvValue(process.env.PROXMOX_WORKSPACE_STORAGE, "PROXMOX_WORKSPACE_STORAGE"),
    bridge: requireDotenvValue(process.env.PROXMOX_WORKSPACE_BRIDGE, "PROXMOX_WORKSPACE_BRIDGE"),
    otherBridge: requireDotenvValue(process.env.PROXMOX_OTHER_BRIDGE, "PROXMOX_OTHER_BRIDGE"),
    imageSha256: requireDotenvValue(process.env.PROXMOX_IMAGE_SHA256, "PROXMOX_IMAGE_SHA256"),
    templates: {
      kvm: Number(requireDotenvValue(process.env.PROXMOX_TEMPLATE_KVM, "PROXMOX_TEMPLATE_KVM")),
      emulated: Number(requireDotenvValue(process.env.PROXMOX_TEMPLATE_EMULATED, "PROXMOX_TEMPLATE_EMULATED")),
    },
    pinnedRelease: requireDotenvValue(process.env.PROXMOX_PINNED_RELEASE, "PROXMOX_PINNED_RELEASE"),
    provision: {
      mount: requireDotenvValue(process.env.PROXMOX_PROVISION_MOUNT, "PROXMOX_PROVISION_MOUNT"),
      path: requireDotenvValue(process.env.PROXMOX_PROVISION_PATH, "PROXMOX_PROVISION_PATH"),
    },
    tenantMount: requireDotenvValue(process.env.PROXMOX_TENANT_MOUNT, "PROXMOX_TENANT_MOUNT"),
    openbao: {
      baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL")),
      roleId: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_ROLE_ID, "OPENBAO_PLAYWRIGHT_ROLE_ID"),
      secretId: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SECRET_ID, "OPENBAO_PLAYWRIGHT_SECRET_ID"),
      mount: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_MOUNT, "OPENBAO_PLAYWRIGHT_MOUNT"),
    },
    semaphore: {
      baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.SEMAPHORE_BASE_URL, "SEMAPHORE_BASE_URL")),
      breakglassPath: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SEMAPHORE_PATH, "OPENBAO_PLAYWRIGHT_SEMAPHORE_PATH"),
      workspacesProject: requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_PROJECT, "SEMAPHORE_WORKSPACES_PROJECT"),
      appControlProject: requireDotenvValue(process.env.SEMAPHORE_APP_CONTROL_PROJECT, "SEMAPHORE_APP_CONTROL_PROJECT"),
    },
  };
}

function identity(workspace) {
  const user = `ws-${workspace}@pve`;
  return { pool: `ws-${workspace}`, user, token: `${user}!${settings().tokenName}` };
}

function expectedAcls(workspace) {
  const { storage, bridge, templates } = settings();
  const { user, token } = identity(workspace);
  return [
    [`/pool/ws-${workspace}`, WORKSPACE_ROLE, 1],
    [`/storage/${storage}`, STORAGE_ROLE, 0],
    [`/sdn/zones/localnetwork/${bridge}`, BRIDGE_ROLE, 0],
    [`/vms/${templates.kvm}`, TEMPLATE_ROLE, 0],
    [`/vms/${templates.emulated}`, TEMPLATE_ROLE, 0],
  ]
    .flatMap(([path, role, propagate]) => [
      `user ${user} ${path} ${role} ${propagate}`,
      `token ${token} ${path} ${role} ${propagate}`,
    ])
    .sort();
}

function digest(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function runTemplate(request, projectName, templateName, environment, runMs) {
  const { openbao, semaphore } = settings();
  const sem = await vaultedBreakglassSession(request, openbao, semaphore, projectName, templateName);
  return runTemplateTask(sem, environment, runMs, SEMAPHORE_POLL_MS, templateName);
}

async function runWorkspace(request, workspace, action) {
  const survey = workspaceSurvey(workspace, action);
  return runTemplate(request, settings().semaphore.workspacesProject, WORKSPACE_TEMPLATE, survey, WORKSPACE_RUN_MS);
}

async function expectWorkspace(request, workspace, action) {
  return expectWorkspaceSuccess(await runWorkspace(request, workspace, action), workspace, action);
}

async function appControl(request, action) {
  const run = await runTemplate(
    request,
    settings().semaphore.appControlProject,
    `${action} ${APPLICATION_ID}`,
    null,
    APP_CONTROL_RUN_MS,
  );
  expect(run.status, `app-control ${action} task ${run.id} of ${APPLICATION_ID} must succeed`).toBe("success");
}

async function workspaceToken(request, workspace) {
  const path = `ws-${workspace}-provision/proxmox`;
  const read = await openbaoRead(request, settings().openbao, settings().tenantMount, path);
  expect(read.status, `OpenBao must hold ${settings().tenantMount}/${path}`).toBe(200);
  expect(Object.keys(read.data).sort(), `${path} must hold exactly token_id and secret`).toEqual(["secret", "token_id"]);
  expect(read.data.token_id, `${path} must name the token of ws-${workspace}`).toBe(identity(workspace).token);
  return read.data;
}

function tokenApi(request, token) {
  const { apiUrl } = settings();
  const authorization = `PVEAPIToken=${token.token_id}=${token.secret}`;
  return (method, route, data) =>
    request.fetch(`${apiUrl}/api2/json${route}`, {
      method,
      headers: { Authorization: authorization },
      data,
      failOnStatusCode: false,
      timeout: resolveTimeout(60_000),
    });
}

async function answered(response, what) {
  expect(response.status(), `${what} must succeed`).toBe(200);
  return (await response.json()).data;
}

function refused(response, what) {
  expect(response.status(), `${what} must be refused with 403`).toBe(403);
}

async function adminApi(page) {
  const env = proxmoxEnv();
  await signInThroughGate(page, env);
  await signInThroughRealm(page, env);
  return async (route) => {
    const response = await page.request.get(`${env.appBaseUrl}/api2/json${route}`, {
      failOnStatusCode: false,
      timeout: resolveTimeout(60_000),
    });
    expect(response.status(), `Proxmox VE must answer GET ${route} for the administrator`).toBe(200);
    return (await response.json()).data;
  };
}

async function workspaceState(admin) {
  const pools = (await admin("/pools")).map((pool) => pool.poolid).filter((id) => id.startsWith("ws-")).sort();
  const users = (await admin("/access/users?full=1"))
    .filter((user) => user.userid.startsWith("ws-"))
    .map((user) => `${user.userid} ${(user.tokens || []).map((token) => token.tokenid).sort().join(",")}`)
    .sort();
  const acls = (await admin("/access/acl"))
    .filter((acl) => acl.ugid.startsWith("ws-"))
    .map((acl) => `${acl.type} ${acl.ugid} ${acl.path} ${acl.roleid} ${acl.propagate}`)
    .sort();
  return { pools, users, acls };
}

function stateOf(state, workspace) {
  const { pool, user } = identity(workspace);
  return {
    pools: state.pools.filter((id) => id === pool),
    users: state.users.filter((entry) => entry.startsWith(`${user} `)),
    acls: state.acls.filter((entry) => entry.split(" ")[1].startsWith(user)),
  };
}

async function awaitTask(api, upid, what) {
  const { node } = settings();
  let state;
  await expect
    .poll(
      async () => {
        state = await answered(await api("GET", `/nodes/${node}/tasks/${encodeURIComponent(upid)}/status`), `reading the task of ${what}`);
        return state.status;
      },
      { timeout: resolveTimeout(PVE_TASK_MS), intervals: [PVE_POLL_MS], message: `the Proxmox VE task of ${what} must stop` },
    )
    .toBe("stopped");
  expect(state.exitstatus, `the Proxmox VE task of ${what} must end OK`).toBe("OK");
}

function freshVmid() {
  return VMID_FLOOR + randomInt(VMID_SPAN);
}

async function cloneInto(api, source, workspace, created) {
  const { node } = settings();
  const { pool } = identity(workspace);
  const newid = freshVmid();
  const what = `the full clone of ${source} into ${pool} as ${newid}`;
  const upid = await answered(
    await api("POST", `/nodes/${node}/qemu/${source}/clone`, { newid, name: `playwright-${newid}`, pool, full: 1 }),
    what,
  );
  created.set(newid, workspace);
  await awaitTask(api, upid, what);
  return newid;
}

async function removeVm(api, vmid, created) {
  const { node } = settings();
  const status = await answered(await api("GET", `/nodes/${node}/qemu/${vmid}/status/current`), `reading VM ${vmid}`);
  if (status.status === "running") {
    await awaitTask(api, await answered(await api("POST", `/nodes/${node}/qemu/${vmid}/status/stop`), `stopping VM ${vmid}`), `stopping VM ${vmid}`);
  }
  await awaitTask(api, await answered(await api("DELETE", `/nodes/${node}/qemu/${vmid}`), `deleting VM ${vmid}`), `deleting VM ${vmid}`);
  created.delete(vmid);
}

async function awaitApi(api, what) {
  await expect
    .poll(
      async () =>
        api("GET", "/version").then(
          (response) => response.status(),
          (error) => `no answer (${error.message.split("\n")[0]})`,
        ),
      { timeout: resolveTimeout(GUEST_BOOT_MS), intervals: [PVE_POLL_MS * 5], message: `Proxmox VE must answer ${what}` },
    )
    .toBe(200);
}

function firstBootDigests() {
  const lines = decodeDotenvJsonList(process.env.PROXMOX_FIRST_BOOT_DIGESTS_JSON, "PROXMOX_FIRST_BOOT_DIGESTS_JSON");
  const record = Object.fromEntries(
    lines.map((line) => {
      const at = line.indexOf("=");
      return at < 0 ? [line, ""] : [line.slice(0, at), line.slice(at + 1)];
    }),
  );
  const items = Object.keys(FIRST_BOOT_FORMATS);
  const keys = FIRST_BOOT_PHASES.flatMap((phase) => items.map((item) => `${phase}.${item}`)).sort();
  expect(
    Object.keys(record).sort(),
    "the first boot must record the image's and this deployment's identity digests; a guest installed before the hook kept them carries none until the proxmox_guest volume is recreated",
  ).toEqual(keys);
  for (const key of keys) {
    expect(record[key], `${key} of the first-boot record must be well-formed`).toMatch(FIRST_BOOT_FORMATS[key.split(".")[1]]);
  }
  return Object.fromEntries(
    FIRST_BOOT_PHASES.map((phase) => [phase, Object.fromEntries(items.map((item) => [item, record[`${phase}.${item}`]]))]),
  );
}

function provisionRecordKvm(record) {
  const kvm = String(record.kvm).toLowerCase();
  expect(["true", "false"], `the provision record must state kvm as true or false, got ${record.kvm}`).toContain(kvm);
  return kvm === "true";
}

test("proxmox templates: the deploy creates both templates once", async ({ page }) => {
  test.setTimeout(resolveTimeout(600_000));
  const { node, storage, imageSha256, templates } = settings();
  const admin = await adminApi(page);
  for (const [id, kvm, cpu] of [
    [templates.kvm, 1, "x86-64-v2-AES"],
    [templates.emulated, 0, "qemu64"],
  ]) {
    const config = await admin(`/nodes/${node}/qemu/${id}/config`);
    expect(Number(config.template), `VM ${id} must be a template`).toBe(1);
    expect(String(config.description).trim(), `template ${id} must carry the pinned image marker`).toBe(
      `image-sha256=${imageSha256}`,
    );
    expect(Number(config.kvm), `template ${id} must run with kvm ${kvm}`).toBe(kvm);
    expect(config.cpu, `template ${id} must use the CPU type ${cpu}`).toBe(cpu);
    expect(String(config.scsi0), `template ${id} must keep its disk on ${storage}`).toMatch(new RegExp(`^${storage}:`));
    const tasks = await admin(`/nodes/${node}/tasks?vmid=${id}&source=all&limit=1000`);
    const count = (type) => tasks.filter((task) => task.type === type).length;
    expect(count("qmcreate"), `template ${id} must be created exactly once`).toBe(1);
    expect(count("qmtemplate"), `template ${id} must be turned into a template exactly once`).toBe(1);
    expect(count("qmdestroy"), `template ${id} must never be destroyed and rebuilt`).toBe(0);
  }
});

test("proxmox vm: the guest runs the pinned release", async ({ page }) => {
  test.skip(!vmFlavor, "the container flavor runs Proxmox VE from packages, not as a guest of the pinned installer ISO");
  const { pinnedRelease } = settings();
  expect(pinnedRelease, "the pinned release must read <major>.<minor>, so the ISO file name parsed").toMatch(/^\d+\.\d+$/);
  const admin = await adminApi(page);
  const version = await admin("/version");
  expect(version.release, `the guest must run Proxmox VE ${pinnedRelease}`).toBe(pinnedRelease);
  expect(String(version.version), `pve-manager must belong to release ${pinnedRelease}`).toMatch(
    new RegExp(`^${pinnedRelease.replace(".", "\\.")}\\.`),
  );
});

test("proxmox vm: no two deployments share a key", async ({ page }) => {
  test.skip(!vmFlavor, "the container flavor runs Proxmox VE from packages, so no two deployments boot from one image");
  const { node } = settings();
  const { image, deployed } = firstBootDigests();
  const imageHostKeys = image.ssh_host_keys.split(",");
  const deployedHostKeys = deployed.ssh_host_keys.split(",");
  expect(
    deployedHostKeys.filter((key) => imageHostKeys.includes(key)),
    "no SSH host key of this deployment may be one the image carries",
  ).toEqual([]);
  expect(
    deployedHostKeys.filter((key) => key.startsWith("ED25519:")),
    "the guest must hold exactly the ed25519 host key the launcher generated for it",
  ).toHaveLength(1);
  for (const item of Object.keys(FIRST_BOOT_FORMATS).filter((name) => name !== "ssh_host_keys")) {
    expect(deployed[item], `the ${item} of this deployment must not be the one the image carries`).not.toBe(image[item]);
  }
  const admin = await adminApi(page);
  const certificates = await admin(`/nodes/${node}/certificates/info`);
  for (const [item, file] of Object.entries(LIVE_CERTIFICATES)) {
    const live = certificates.find((certificate) => String(certificate.filename).split("/").pop() === file);
    expect(live, `Proxmox VE must report ${file} of ${node}`).toBeTruthy();
    expect(String(live.fingerprint).toUpperCase(), `${file} of ${node} must be the one the first boot generated`).toBe(deployed[item]);
  }
});

test.describe.serial("proxmox workspaces", () => {
  test.skip(!workspacesEnabled, "no Semaphore Workspaces project with OpenBao runs beside Proxmox VE, so no workspace apply can start");

  const first = randomUUID();
  const second = randomUUID();
  const applied = new Set();
  const created = new Map();
  const runsOfFirst = [];
  let foreignVm;

  test.afterAll(async ({ playwright }) => {
    test.setTimeout(resolveTimeout(3 * WORKSPACE_RUN_MS));
    const request = await playwright.request.newContext({ ignoreHTTPSErrors: true });
    try {
      for (const workspace of applied) {
        try {
          const api = tokenApi(request, await workspaceToken(request, workspace));
          for (const [vmid] of [...created].filter(([, owner]) => owner === workspace)) {
            await removeVm(api, vmid, created);
          }
        } finally {
          await expectWorkspace(request, workspace, "destroy");
        }
      }
      expect([...created.keys()], "every VM the spec cloned must be removed").toEqual([]);
    } finally {
      await request.dispose();
    }
  });

  test("proxmox workspaces: apply creates pool, user, token and ACLs once", async ({ page, request }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_RUN_MS + 600_000));
    applied.add(first);
    runsOfFirst.push(await expectWorkspace(request, first, "apply"));
    const { pool, user } = identity(first);
    const admin = await adminApi(page);
    const before = stateOf(await workspaceState(admin), first);
    expect(before.pools, `apply must create the pool ${pool}`).toEqual([pool]);
    expect(before.users, `apply must create ${user} with exactly its token`).toEqual([`${user} ${settings().tokenName}`]);
    expect(before.acls, `the user and the token of ${pool} must hold exactly their ACLs`).toEqual(expectedAcls(first));
    const tokenInfo = await admin(`/access/users/${encodeURIComponent(user)}/token/${settings().tokenName}`);
    expect(Number(tokenInfo.privsep), `the token of ${pool} must be privilege-separated`).toBe(1);
    const token = await workspaceToken(request, first);
    await answered(await tokenApi(request, token)("GET", "/version"), `the token of ${pool} authenticating`);

    runsOfFirst.push(await expectWorkspace(request, first, "apply"));
    const after = stateOf(await workspaceState(await adminApi(page)), first);
    expect(after, `a second apply must leave pool, user, token and ACLs of ${pool} as they were`).toEqual(before);
    const kept = await workspaceToken(request, first);
    expect(digest(kept.secret), `a second apply must keep the token of ${pool}`).toBe(digest(token.secret));
    await answered(await tokenApi(request, token)("GET", "/version"), `the first token of ${pool} after the second apply`);
  });

  test("proxmox workspaces: the token secret exists only in OpenBao", async ({ request }) => {
    const token = await workspaceToken(request, first);
    expect(token.secret, "the token secret in OpenBao must be a Proxmox VE token value").toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
    await answered(await tokenApi(request, token)("GET", "/version"), "the token from OpenBao authenticating");
    expect(runsOfFirst, "the apply runs of the first workspace must be on record").toHaveLength(2);
    for (const run of runsOfFirst) {
      expect(
        run.lines.filter((line) => line.includes(token.secret)),
        `no line of workspace apply task ${run.id} may hold the token secret`,
      ).toHaveLength(0);
    }
  });

  test("proxmox workspaces: a token reaches only its own pool", async ({ request }) => {
    test.setTimeout(resolveTimeout(WORKSPACE_RUN_MS + 2 * PVE_TASK_MS));
    applied.add(second);
    await expectWorkspace(request, second, "apply");
    const { node, templates, otherBridge } = settings();
    const asFirst = tokenApi(request, await workspaceToken(request, first));
    const asSecond = tokenApi(request, await workspaceToken(request, second));
    foreignVm = await cloneInto(asSecond, templates.emulated, second, created);
    const ownVm = await cloneInto(asFirst, templates.emulated, first, created);

    refused(await asFirst("GET", `/nodes/${node}/qemu/${foreignVm}/config`), `reading VM ${foreignVm} of ${identity(second).pool}`);
    refused(
      await asFirst("PUT", `/nodes/${node}/qemu/${foreignVm}/config`, { description: "intrusion" }),
      `changing VM ${foreignVm} of ${identity(second).pool}`,
    );
    refused(await asFirst("GET", `/pools?poolid=${identity(second).pool}`), `reading the pool ${identity(second).pool}`);
    refused(await asFirst("GET", `/nodes/${node}/qemu/${templates.kvm}/config`), `reading template ${templates.kvm}, a VM outside every workspace pool`);
    refused(await asFirst("POST", `/nodes/${node}/qemu`, { vmid: freshVmid() }), "creating a VM outside any pool");
    refused(
      await asFirst("POST", `/nodes/${node}/qemu`, { vmid: freshVmid(), pool: identity(second).pool }),
      `creating a VM in ${identity(second).pool}`,
    );
    refused(
      await asFirst("PUT", `/nodes/${node}/qemu/${ownVm}/config`, { net1: `virtio,bridge=${otherBridge}` }),
      `putting a NIC of VM ${ownVm} on ${otherBridge}`,
    );
    refused(
      await asFirst("PUT", `/nodes/${node}/qemu/${ownVm}/config`, { scsi1: `${OTHER_STORAGE}:1` }),
      `adding a disk of VM ${ownVm} on ${OTHER_STORAGE}`,
    );
    refused(await asFirst("GET", `/nodes/${node}/syslog`), "reading the node syslog");
    refused(await asFirst("GET", `/nodes/${node}/journal`), "reading the node journal");
    refused(await asFirst("POST", `/nodes/${node}/termproxy`), "opening a node shell");
    refused(
      await asFirst("POST", "/access/users", { userid: `playwright-${randomUUID().slice(0, 8)}@pve` }),
      "creating a user",
    );
    refused(
      await asFirst("PUT", "/access/acl", { path: `/pool/${identity(first).pool}`, roles: "Administrator", tokens: identity(first).token }),
      "raising the token's own ACL",
    );
    refused(
      await asFirst("POST", `/nodes/${node}/qemu/${foreignVm}/clone`, { newid: freshVmid(), pool: identity(first).pool, full: 1 }),
      `cloning VM ${foreignVm} of ${identity(second).pool}`,
    );
    await removeVm(asFirst, ownVm, created);
  });

  test("proxmox workspaces: a token clones the templates and changes none", async ({ page, request }) => {
    test.setTimeout(resolveTimeout(3 * PVE_TASK_MS + 600_000));
    const { node, templates } = settings();
    const asFirst = tokenApi(request, await workspaceToken(request, first));
    const admin = await adminApi(page);
    const before = await Promise.all([templates.kvm, templates.emulated].map((id) => admin(`/nodes/${node}/qemu/${id}/config`)));
    const clones = [];
    for (const source of [templates.kvm, templates.emulated]) {
      clones.push(await cloneInto(asFirst, source, first, created));
    }
    const members = (await answered(await asFirst("GET", `/pools?poolid=${identity(first).pool}`), `reading ${identity(first).pool}`))[0].members.map(
      (member) => Number(member.vmid),
    );
    expect(members, `both clones must sit in ${identity(first).pool}`).toEqual(expect.arrayContaining(clones));
    expect(foreignVm, "the VM of the second workspace must exist from the previous test").toBeTruthy();
    refused(
      await asFirst("POST", `/nodes/${node}/qemu/${foreignVm}/clone`, { newid: freshVmid(), pool: identity(first).pool, full: 1 }),
      `cloning VM ${foreignVm}, which sits outside ${identity(first).pool} and is no template`,
    );
    for (const id of [templates.kvm, templates.emulated]) {
      refused(await asFirst("PUT", `/nodes/${node}/qemu/${id}/config`, { description: "changed" }), `changing template ${id}`);
      refused(await asFirst("DELETE", `/nodes/${node}/qemu/${id}`), `deleting template ${id}`);
    }
    const after = await Promise.all([templates.kvm, templates.emulated].map((id) => admin(`/nodes/${node}/qemu/${id}/config`)));
    expect(after.map((config) => config.digest), "neither template may change").toEqual(before.map((config) => config.digest));
    for (const vmid of clones) {
      await removeVm(asFirst, vmid, created);
    }
  });

  test("proxmox vm: a VM starts in the recorded mode", async ({ request }) => {
    test.skip(!vmFlavor, "the container flavor always runs its VMs with KVM, so no mode is recorded from the host");
    test.setTimeout(resolveTimeout(4 * PVE_TASK_MS));
    const { node, templates, provision, openbao } = settings();
    const record = await openbaoRead(request, openbao, provision.mount, provision.path);
    expect(record.status, `OpenBao must hold the provision record ${provision.mount}/${provision.path}`).toBe(200);
    const kvm = provisionRecordKvm(record.data);
    const asFirst = tokenApi(request, await workspaceToken(request, first));
    const source = kvm ? templates.kvm : templates.emulated;
    const vmid = await cloneInto(asFirst, source, first, created);
    const config = await answered(await asFirst("GET", `/nodes/${node}/qemu/${vmid}/config`), `reading VM ${vmid}`);
    expect(Number(config.kvm), `VM ${vmid} must carry the recorded mode kvm ${kvm ? 1 : 0}`).toBe(kvm ? 1 : 0);
    await awaitTask(asFirst, await answered(await asFirst("POST", `/nodes/${node}/qemu/${vmid}/status/start`), `starting VM ${vmid}`), `starting VM ${vmid}`);
    const status = await answered(await asFirst("GET", `/nodes/${node}/qemu/${vmid}/status/current`), `reading VM ${vmid}`);
    expect(status.status, `VM ${vmid} must run in the recorded mode kvm ${kvm ? 1 : 0}`).toBe("running");
    await removeVm(asFirst, vmid, created);
  });

  test("proxmox workspaces: a restart keeps every pool and token", async ({ page, request }) => {
    test.setTimeout(resolveTimeout(2 * APP_CONTROL_RUN_MS + GUEST_BOOT_MS + 600_000));
    const before = await workspaceState(await adminApi(page));
    const tokens = [await workspaceToken(request, first), await workspaceToken(request, second)];
    await appControl(request, "stop");
    try {
      await appControl(request, "start");
    } catch (error) {
      await appControl(request, "start");
      throw error;
    }
    await awaitApi(tokenApi(request, tokens[0]), "after the restart of the launcher container");
    const after = await workspaceState(await adminApi(page));
    expect(after, "a restart must keep every workspace pool, user, token and ACL").toEqual(before);
    for (const token of tokens) {
      await answered(await tokenApi(request, token)("GET", "/version"), `the token ${token.token_id} after the restart`);
    }
  });

  test("proxmox workspaces: destroy removes token, user and pool", async ({ page, request }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_RUN_MS + 2 * PVE_TASK_MS));
    const { templates } = settings();
    const { pool, user } = identity(first);
    const token = await workspaceToken(request, first);
    const asFirst = tokenApi(request, token);
    const vmid = await cloneInto(asFirst, templates.emulated, first, created);
    const refusedRun = await runWorkspace(request, first, "destroy");
    expect(refusedRun.status, `destroy task ${refusedRun.id} must refuse while ${pool} holds VM ${vmid}`).toBe("error");
    const kept = stateOf(await workspaceState(await adminApi(page)), first);
    expect(kept.pools, `the refused destroy must keep ${pool}`).toEqual([pool]);
    await answered(await asFirst("GET", "/version"), "the token after the refused destroy");
    await removeVm(asFirst, vmid, created);

    await expectWorkspace(request, first, "destroy");
    applied.delete(first);
    const gone = stateOf(await workspaceState(await adminApi(page)), first);
    expect(gone, `destroy must leave no pool, user, token or ACL of ${user}`).toEqual({ pools: [], users: [], acls: [] });
    expect((await asFirst("GET", "/version")).status(), "the destroyed token must no longer authenticate").toBe(401);
    const record = await openbaoRead(request, settings().openbao, settings().tenantMount, `ws-${first}-provision/proxmox`);
    expect(record.status, "destroy must drop the token secret from OpenBao").toBe(404);
  });
});
