const { createHash, randomBytes, randomUUID } = require("node:crypto");

const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { sign } = require("./personas/utils/s3");
const {
  WORKSPACE_TEMPLATE,
  expectWorkspaceSuccess,
  openbaoRead,
  runWorkspaceTask,
  strictFlag,
  vaultedBreakglassSession,
} = require("./personas/utils/workspace");
const { resolveTimeout } = require("./timeouts");

const REQUEST_MS = 30_000;
const WORKSPACE_MS = 30 * 60_000;
const SEMAPHORE_POLL_MS = 10_000;
const KEY_TYPE = "aes256-gcm96";
const HOURS = /^([0-9]+)h$/;
const REFUSED = [403];
const BAD_LOGIN = [400, 403];

function settings() {
  return {
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
    },
    storePath: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_STORE_PATH, "OPENBAO_PLAYWRIGHT_STORE_PATH"),
    storeRole: requireDotenvValue(process.env.OPENBAO_STORE_APPROLE, "OPENBAO_STORE_APPROLE"),
    storeSecretIdTtl: requireDotenvValue(process.env.OPENBAO_STORE_SECRET_ID_TTL, "OPENBAO_STORE_SECRET_ID_TTL"),
    tenant: requireDotenvValue(process.env.OPENBAO_TENANT_MOUNT, "OPENBAO_TENANT_MOUNT"),
    platform: requireDotenvValue(process.env.OPENBAO_PLATFORM_MOUNT, "OPENBAO_PLATFORM_MOUNT"),
    transit: requireDotenvValue(process.env.OPENBAO_TRANSIT_MOUNT, "OPENBAO_TRANSIT_MOUNT"),
    transitRecords: requireDotenvValue(process.env.OPENBAO_TRANSIT_RECORD_PREFIX, "OPENBAO_TRANSIT_RECORD_PREFIX"),
  };
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

/**
 * Args:
 *   request: a Playwright request context.
 *   method: the HTTP method.
 *   path: the API path below /v1/.
 *   token: the OpenBao token, null for a login.
 *   data: the JSON body, if any.
 *
 * Returns:
 *   The response, whatever its status.
 */
function bao(request, method, path, token, data) {
  return request.fetch(`${settings().openbao.baseUrl}/v1/${path}`, {
    method,
    headers: token ? { "X-Vault-Token": token } : {},
    data,
    failOnStatusCode: false,
    timeout: resolveTimeout(REQUEST_MS),
  });
}

/**
 * Args:
 *   response: a response of `bao`.
 *   statuses: the statuses the call may answer.
 *   what: the call the failure message names.
 */
function expectAnswer(response, statuses, what) {
  expect(statuses, `${what} answered ${response.status()}`).toContain(response.status());
}

/**
 * Args:
 *   request: a Playwright request context.
 *   secretId: a secret id of the store AppRole.
 *   roleId: the store's role id.
 *
 * Returns:
 *   The login response, whatever its status.
 */
function storeLogin(request, roleId, secretId) {
  return bao(request, "POST", "auth/approle/login", null, { role_id: roleId, secret_id: secretId });
}

/**
 * Args:
 *   request: a Playwright request context.
 *   tokens: the list each new token is pushed to, for the revocation of `revokeAll`.
 *
 * Returns:
 *   `token`, `roleId` and `secretId` of the store AppRole as the Playwright AppRole hands it over.
 */
async function storeIdentity(request, tokens) {
  const { openbao, storePath } = settings();
  const login = await openbaoRead(request, openbao, openbao.mount, storePath);
  expect(login.status, `OpenBao must hand the Playwright AppRole the store login ${openbao.mount}/${storePath}`).toBe(200);
  const response = await storeLogin(request, login.data.role_id, login.data.secret_id);
  expectAnswer(response, [200], "the AppRole login of the store");
  const token = (await response.json()).auth.client_token;
  tokens.push(token);
  return { token, roleId: login.data.role_id, secretId: login.data.secret_id };
}

async function revokeAll(request, tokens) {
  for (const token of tokens.splice(0)) {
    await bao(request, "POST", "auth/token/revoke-self", token);
  }
}

/**
 * Args:
 *   request: a Playwright request context.
 *   path: an API path below /v1/ the Playwright AppRole reads.
 *   statuses: the statuses the read may answer.
 *
 * Returns:
 *   The `data` of a 200 answer, else null, read with a Playwright AppRole token that is revoked afterwards.
 */
async function playwrightRead(request, path, statuses = [200]) {
  const { openbao } = settings();
  const login = await bao(request, "POST", "auth/approle/login", null, { role_id: openbao.roleId, secret_id: openbao.secretId });
  expectAnswer(login, [200], "the AppRole login of the Playwright AppRole");
  const token = (await login.json()).auth.client_token;
  try {
    const read = await bao(request, "GET", path, token);
    expectAnswer(read, statuses, `the Playwright read of ${path}`);
    return read.status() === 200 ? (await read.json()).data : null;
  } finally {
    expectAnswer(await bao(request, "POST", "auth/token/revoke-self", token), [204], "the revocation of the Playwright token");
  }
}

/**
 * Args:
 *   request: a Playwright request context.
 *   token: the store token.
 *   path: the secret path below the tenant mount.
 *   data: the fields to write.
 *
 * Returns:
 *   The version the write created.
 */
async function tenantWrite(request, token, path, data) {
  const response = await bao(request, "POST", `${settings().tenant}/data/${path}`, token, { data });
  expectAnswer(response, [200], `the store write of ${settings().tenant}/${path}`);
  return (await response.json()).data.version;
}

async function tenantErase(request, token, path) {
  expectAnswer(await bao(request, "DELETE", `${settings().tenant}/metadata/${path}`, token), [204], `the store erasure of ${path}`);
}

async function workspaceAttempt(request, workspace, action) {
  const { openbao, semaphore } = settings();
  const sem = await vaultedBreakglassSession(request, openbao, semaphore, semaphore.workspacesProject, WORKSPACE_TEMPLATE);
  return runWorkspaceTask(sem, workspace, action, SEMAPHORE_POLL_MS);
}

async function workspaceRun(request, workspace, action) {
  return expectWorkspaceSuccess(await workspaceAttempt(request, workspace, action), workspace, action);
}

async function transitKey(request, workspace, statuses = [200]) {
  return playwrightRead(request, `${settings().transit}/keys/ws-${workspace}-provision`, statuses);
}

/**
 * Args:
 *   request: a Playwright request context.
 *   workspace: the workspace id.
 *   key: the object key in the workspace's state bucket.
 *
 * Returns:
 *   A function of `method` and `body` that sends one request on that object with the workspace's own S3 keys.
 */
async function stateObject(request, workspace, key) {
  const { openbao, tenant } = settings();
  const keys = await openbaoRead(request, openbao, tenant, `ws-${workspace}-provision/s3`);
  expect(keys.status, `OpenBao must hold ${tenant}/ws-${workspace}-provision/s3`).toBe(200);
  const origin = new URL(normalizeBaseUrl(requireDotenvValue(process.env.SEAWEEDFS_S3_URL, "SEAWEEDFS_S3_URL")));
  const region = requireDotenvValue(process.env.SEAWEEDFS_REGION, "SEAWEEDFS_REGION");
  const path = `/ws-${workspace}-state/${key}`;
  return (method, body = "") =>
    request.fetch(`${origin.origin}${path}`, {
      method,
      headers: sign({
        method,
        host: origin.host,
        path,
        region,
        accessKey: keys.data.access_key,
        secretKey: keys.data.secret_key,
        query: {},
        payload: body,
      }),
      data: body === "" ? undefined : body,
      failOnStatusCode: false,
      timeout: resolveTimeout(REQUEST_MS),
    });
}

function skipWithoutPlaywrightAppRole() {
  test.skip(
    !strictFlag(process.env.OPENBAO_PLAYWRIGHT_ENABLED, "OPENBAO_PLAYWRIGHT_ENABLED"),
    "OPENBAO_PLAYWRIGHT_ENABLED=false: no Semaphore beside OpenBao or a production runtime, so neither the store nor the Playwright AppRole exists",
  );
}

function skipWithoutWorkspaces() {
  test.skip(
    !strictFlag(process.env.SEMAPHORE_WORKSPACES_ENABLED, "SEMAPHORE_WORKSPACES_ENABLED"),
    "SEMAPHORE_WORKSPACES_ENABLED=false: no workspace runner beside OpenBao, so no workspace apply can start",
  );
}

function skipWithoutStateBuckets() {
  test.skip(!process.env.SEAWEEDFS_S3_URL, "SEAWEEDFS_S3_URL is empty: no SeaweedFS beside OpenBao, so no workspace holds a state bucket");
}

test.describe.serial("openbao store approle", () => {
  const tokens = [];

  test.beforeEach(() => {
    skipWithoutPlaywrightAppRole();
  });

  test.afterEach(async ({ request }) => {
    await revokeAll(request, tokens);
  });

  test("store approle: writes but never reads a workspace secret", async ({ request }) => {
    const { tenant, transit } = settings();
    const workspace = randomUUID();
    const path = `ws-${workspace}/x`;
    const store = await storeIdentity(request, tokens);
    await tenantWrite(request, store.token, path, { value: randomBytes(16).toString("hex") });
    try {
      expectAnswer(await bao(request, "GET", `${tenant}/data/${path}`, store.token), REFUSED, `the store read of ${tenant}/${path}`);
      const key = `ws-${workspace}-provision`;
      const refused = [];
      for (const mount of ["jwt", "jwt-export"]) {
        refused.push(["GET", `auth/${mount}/config`], ["POST", `auth/${mount}/config`]);
        refused.push(["GET", `auth/${mount}/role/ws-${workspace}`], ["POST", `auth/${mount}/role/ws-${workspace}`]);
        refused.push(["DELETE", `auth/${mount}/role/ws-${workspace}`], ["GET", `auth/${mount}/role?list=true`]);
      }
      refused.push(["GET", "sys/policies/acl/x"], ["POST", "sys/policies/acl/x"]);
      refused.push(["GET", `${transit}/keys/${key}`], ["POST", `${transit}/keys/${key}`], ["POST", `${transit}/keys/${key}/config`]);
      refused.push(["POST", `${transit}/datakey/plaintext/${key}`], ["POST", `${transit}/decrypt/${key}`]);
      refused.push(["POST", `${transit}/encrypt/${key}`], ["GET", `${transit}/export/encryption-key/${key}`]);
      refused.push(["GET", `${transit}/backup/${key}`], ["GET", `${transit}/keys?list=true`]);
      for (const [method, target] of refused) {
        expectAnswer(await bao(request, method, target, store.token, method === "POST" ? {} : undefined), REFUSED, `the store's ${method} ${target}`);
      }
    } finally {
      await tenantErase(request, store.token, path);
    }
  });

  test("store approle: rotates its own secret id", async ({ request }) => {
    const { storeRole, storeSecretIdTtl } = settings();
    const ttl = HOURS.exec(storeSecretIdTtl);
    expect(ttl, `the store's secret_id_ttl ${storeSecretIdTtl} must read <hours>h`).toBeTruthy();
    const store = await storeIdentity(request, tokens);
    const mint = async (token) => {
      const response = await bao(request, "POST", `auth/approle/role/${storeRole}/secret-id`, token, {});
      expectAnswer(response, [200], "the store's mint of a secret id");
      return (await response.json()).data;
    };
    const login = async (secretId, statuses, what) => {
      const response = await storeLogin(request, store.roleId, secretId);
      expectAnswer(response, statuses, what);
      if (response.status() === 200) {
        tokens.push((await response.json()).auth.client_token);
        return tokens[tokens.length - 1];
      }
      return null;
    };
    const first = await mint(store.token);
    const firstToken = await login(first.secret_id, [200], "a login with the first minted secret id");
    const second = await mint(firstToken);
    const secondToken = await login(second.secret_id, [200], "a login with the second minted secret id");
    try {
      const destroyed = await bao(request, "POST", `auth/approle/role/${storeRole}/secret-id-accessor/destroy`, secondToken, {
        secret_id_accessor: first.secret_id_accessor,
      });
      expectAnswer(destroyed, [204], "the store's destroy of its first minted secret id");
      await login(first.secret_id, BAD_LOGIN, "a login with the destroyed secret id");
      await login(second.secret_id, [200], "a login with the secret id that replaced it");
      const lookup = await bao(request, "POST", `auth/approle/role/${storeRole}/secret-id/lookup`, secondToken, {
        secret_id: second.secret_id,
      });
      expectAnswer(lookup, [200], "the store's lookup of its newest secret id");
      const { creation_time: created, expiration_time: expires } = (await lookup.json()).data;
      expect(
        Date.parse(expires) - Date.parse(created),
        `a store secret id must expire ${ttl[1]} h after its creation, so OpenBao refuses an older one`,
      ).toBe(Number(ttl[1]) * 3_600_000);
    } finally {
      await bao(request, "POST", `auth/approle/role/${storeRole}/secret-id-accessor/destroy`, store.token, {
        secret_id_accessor: second.secret_id_accessor,
      });
      await bao(request, "POST", `auth/approle/role/${storeRole}/secret-id-accessor/destroy`, store.token, {
        secret_id_accessor: first.secret_id_accessor,
      });
    }
  });

  test("store approle: looks up only its own secret id", async ({ request }) => {
    const { storeRole } = settings();
    const store = await storeIdentity(request, tokens);
    const lookup = await bao(request, "POST", `auth/approle/role/${storeRole}/secret-id/lookup`, store.token, {
      secret_id: store.secretId,
    });
    expectAnswer(lookup, [200], "the store's lookup of its own secret id");
    expect(Date.parse((await lookup.json()).data.expiration_time), "the lookup must answer the expiration_time of the store's secret id").toBeGreaterThan(Date.now());
    expectAnswer(
      await bao(request, "POST", `auth/approle/role/${storeRole}/custom-secret-id`, store.token, { secret_id: randomUUID() }),
      REFUSED,
      "the store's custom-secret-id",
    );
    for (const other of ["ansible", "playwright"]) {
      expectAnswer(
        await bao(request, "POST", `auth/approle/role/${other}/secret-id/lookup`, store.token, { secret_id: store.secretId }),
        REFUSED,
        `the store's lookup on the role ${other}`,
      );
    }
  });

  test("store approle: owns the pinned host keys and no task reads them", async ({ request }) => {
    const { platform } = settings();
    const workspace = randomUUID();
    const entry = `store/hostkeys/ws-${workspace}/host.example/22`;
    const store = await storeIdentity(request, tokens);
    const line = { line: `ssh-ed25519 ${randomBytes(32).toString("base64")}` };
    for (const version of [1, 2]) {
      const written = await bao(request, "POST", `${platform}/data/${entry}`, store.token, { data: line });
      expectAnswer(written, [200], `the store's write ${version} of ${platform}/${entry}`);
    }
    const read = await bao(request, "GET", `${platform}/data/${entry}`, store.token);
    expectAnswer(read, [200], `the store's read of ${platform}/${entry}`);
    expect((await read.json()).data.data, "the pinned entry must hold exactly its line").toEqual(line);
    expectAnswer(await bao(request, "DELETE", `${platform}/metadata/${entry}`, store.token), [204], `the store's erasure of ${entry}`);
    expectAnswer(await bao(request, "GET", `${platform}/data/${entry}`, store.token), [404], `the store's read of the erased ${entry}`);
    expectAnswer(await bao(request, "GET", `${platform}/metadata/store/hostkeys/?list=true`, store.token), REFUSED, "the store's list of every pinned workspace");
    expectAnswer(await bao(request, "POST", `${platform}/data/store/other/x`, store.token, { data: line }), REFUSED, "the store's write of store/other/x");
  });

  test("store approle: recovers its own workspace key by version", async ({ request }) => {
    const { tenant, platform } = settings();
    const workspace = randomUUID();
    const key = `ws-${workspace}/ssh`;
    const record = `store/workspace-keys/ws-${workspace}`;
    const store = await storeIdentity(request, tokens);
    const keyWrite = async (cas, statuses, what) => {
      const response = await bao(request, "POST", `${tenant}/data/${key}`, store.token, {
        options: { cas },
        data: { private: randomBytes(32).toString("hex") },
      });
      expectAnswer(response, statuses, what);
      return response.status() === 200 ? (await response.json()).data.version : null;
    };
    const currentVersion = async () => {
      const response = await bao(request, "GET", `${tenant}/metadata/${key}`, store.token);
      expectAnswer(response, [200], `the store's read of the versions of ${tenant}/${key}`);
      return (await response.json()).data.current_version;
    };
    try {
      const version = await keyWrite(0, [200], `the store's first check-and-set write of ${tenant}/${key}`);
      const intent = { public: `ssh-ed25519 ${randomBytes(32).toString("base64")}`, version };
      expectAnswer(await bao(request, "POST", `${platform}/data/${record}`, store.token, { data: intent }), [200], `the store's write of ${platform}/${record}`);
      const read = await bao(request, "GET", `${platform}/data/${record}`, store.token);
      expectAnswer(read, [200], `the store's read of ${platform}/${record}`);
      expect((await read.json()).data.data, "the record must hold the public half and the version").toEqual(intent);
      expect(await currentVersion(), "an untouched key must still stand at the recorded version").toBe(version);
      expectAnswer(await bao(request, "GET", `${tenant}/data/${key}`, store.token), REFUSED, `the store's read of the value of ${tenant}/${key}`);
      await keyWrite(version, [200], `a later write of ${tenant}/${key} the record does not know`);
      expect(await currentVersion(), "a later write must move current_version past the record").toBe(version + 1);
      await keyWrite(version, [400], `a check-and-set write of ${tenant}/${key} on a stale version`);
    } finally {
      await tenantErase(request, store.token, key);
      expectAnswer(await bao(request, "DELETE", `${platform}/metadata/${record}`, store.token), [204], `the store's erasure of ${record}`);
    }
    expectAnswer(await bao(request, "GET", `${platform}/data/${record}`, store.token), [404], `the store's read of the erased ${record}`);
  });

  test("store approle: reads no zone token", async ({ request }) => {
    const { platform } = settings();
    const path = `${platform}/data/provision/cloudflare-zones`;
    const store = await storeIdentity(request, tokens);
    expectAnswer(await bao(request, "GET", path, store.token), REFUSED, `the store's read of ${path}`);
    expectAnswer(await bao(request, "POST", path, store.token, { data: { token: "planted" } }), REFUSED, `the store's write of ${path}`);
  });

  test("store approle: writes no credential of its own and erases nothing else", async ({ request }) => {
    const { tenant, platform, transit } = settings();
    const workspace = randomUUID();
    const store = await storeIdentity(request, tokens);
    for (const [method, target, data] of [
      ["POST", `${platform}/data/store/semaphore`, { data: { token: "planted" } }],
      ["POST", `${platform}/data/store/directory/ws-${workspace}`, { data: { secret: "planted" } }],
      ["GET", `${tenant}/metadata/?list=true`, undefined],
      ["DELETE", `${transit}/keys/ws-${workspace}-provision`, undefined],
      ["DELETE", `auth/jwt/role/ws-${workspace}`, undefined],
    ]) {
      expectAnswer(await bao(request, method, target, store.token, data), REFUSED, `the store's ${method} ${target}`);
    }
  });
});

test.describe.serial("openbao workspace keys and erasure", () => {
  const applied = new Set();
  const tokens = [];
  const own = randomUUID();
  const other = randomUUID();

  test.beforeEach(() => {
    skipWithoutPlaywrightAppRole();
    skipWithoutWorkspaces();
  });

  test.afterAll(async ({ playwright }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_MS));
    const request = await playwright.request.newContext({ ignoreHTTPSErrors: true });
    try {
      await revokeAll(request, tokens);
      for (const workspace of applied) {
        await workspaceRun(request, workspace, "destroy");
      }
    } finally {
      await request.dispose();
    }
  });

  test("transit: apply creates a non-exportable key once", async ({ request }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_MS));
    applied.add(own);
    await workspaceRun(request, own, "apply");
    const created = await transitKey(request, own);
    expect(
      [created.type, created.exportable, created.allow_plaintext_backup, created.deletion_allowed, created.latest_version],
      `apply must create ws-${own}-provision as ${KEY_TYPE}, neither exportable nor backed up in plaintext nor deletable`,
    ).toEqual([KEY_TYPE, false, false, false, 1]);
    await workspaceRun(request, own, "apply");
    const again = await transitKey(request, own);
    expect([again.latest_version, again.keys], `a second apply must leave ws-${own}-provision at its version`).toEqual([
      created.latest_version,
      created.keys,
    ]);
  });

  test("transit: a snapshot follows every new key", async ({ request }) => {
    const { openbao, platform, transitRecords } = settings();
    const key = await transitKey(request, own);
    const record = await openbaoRead(request, openbao, platform, `${transitRecords}/ws-${own}`);
    expect(record.status, `apply must record the snapshot of ws-${own}-provision at ${platform}/${transitRecords}/ws-${own}`).toBe(200);
    const newest = Math.max(...Object.values(key.keys).map(Number));
    expect(Number(record.data.key_created_at), "the record must name the creation of the newest key version").toBe(newest);
    expect(Number(record.data.snapshot_at), "the raft snapshot must be written after the key was created").toBeGreaterThanOrEqual(newest);
  });

  test("transit: destroy deletes the key after the states", async ({ request }) => {
    skipWithoutStateBuckets();
    test.setTimeout(resolveTimeout(3 * WORKSPACE_MS));
    const held = randomUUID();
    applied.add(held);
    await workspaceRun(request, held, "apply");
    const created = await transitKey(request, held);
    const state = await stateObject(request, held, "terraform.tfstate");
    expectAnswer(await state("PUT", "{}"), [200], `the state write to ws-${held}-state`);
    try {
      const refused = await workspaceAttempt(request, held, "destroy");
      expect(refused.status, `destroy task ${refused.id} must refuse while ws-${held}-state holds a state file`).toBe("error");
      expect(
        refused.lines.some((line) => line.includes("terraform.tfstate")),
        `destroy task ${refused.id} must name the state file it refuses for`,
      ).toBe(true);
      const kept = await transitKey(request, held);
      expect([kept.deletion_allowed, kept.keys], `the refused destroy must keep ws-${held}-provision as it was`).toEqual([
        false,
        created.keys,
      ]);
    } finally {
      expectAnswer(await state("DELETE"), [204], `the state removal from ws-${held}-state`);
    }
    await workspaceRun(request, held, "destroy");
    applied.delete(held);
    expect(await transitKey(request, held, [404]), `destroy must delete ws-${held}-provision once no state is left`).toBeNull();
  });

  test("erasure: destroy deletes every secret of the workspace", async ({ request }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_MS));
    applied.add(other);
    await workspaceRun(request, other, "apply");
    const store = await storeIdentity(request, tokens);
    const erased = [`ws-${own}/x`, `ws-${own}/nested/y`, `ws-${own}-provision/x`];
    const kept = `ws-${other}/x`;
    for (const path of [...erased, kept]) {
      await tenantWrite(request, store.token, path, { value: randomBytes(16).toString("hex") });
      await tenantWrite(request, store.token, path, { value: randomBytes(16).toString("hex") });
    }
    const otherSecrets = async () => {
      const found = {};
      for (const name of ["dns", "s3"]) {
        const read = await openbaoRead(request, settings().openbao, settings().tenant, `ws-${other}-provision/${name}`);
        found[name] = [read.status, read.status === 200 ? digest(read.data) : null];
      }
      return found;
    };
    const before = await otherSecrets();
    try {
      await workspaceRun(request, own, "destroy");
      applied.delete(own);
      for (const path of erased) {
        expect(await tenantWrite(request, store.token, path, { value: "after" }), `destroy of ws-${own} must leave no version of ${path}`).toBe(1);
      }
      expect(await tenantWrite(request, store.token, kept, { value: "after" }), `destroy of ws-${own} must keep both versions of ${kept}`).toBe(3);
      expect(await otherSecrets(), `destroy of ws-${own} must leave the provision secrets of ws-${other} as they were`).toEqual(before);
    } finally {
      for (const path of [...erased, kept]) {
        await tenantErase(request, store.token, path);
      }
    }
  });
});
