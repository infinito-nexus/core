const { createHash, randomUUID } = require("node:crypto");

const { test, expect } = require("@playwright/test");
const { decodeDotenvJsonList, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { canonicalQuery, sign } = require("./personas/utils/s3");
const {
  WORKSPACE_RUN_MS,
  WORKSPACE_TEMPLATE,
  expectWorkspaceSuccess,
  openbaoRead,
  runWorkspaceTask,
  vaultedBreakglassSession,
} = require("./personas/utils/workspace");
const { resolveTimeout } = require("./timeouts");

const SEMAPHORE_POLL_MS = 10_000;
const PROBE_INTERVAL_MS = 500;

const enabled = process.env.SEAWEEDFS_WORKSPACES_ENABLED === "true";

test.use({ ignoreHTTPSErrors: true });

function env() {
  return {
    s3Url: normalizeBaseUrl(requireDotenvValue(process.env.SEAWEEDFS_S3_URL, "SEAWEEDFS_S3_URL")),
    region: requireDotenvValue(process.env.SEAWEEDFS_REGION, "SEAWEEDFS_REGION"),
    admin: {
      access_key: requireDotenvValue(process.env.SEAWEEDFS_ADMIN_ACCESS_KEY, "SEAWEEDFS_ADMIN_ACCESS_KEY"),
      secret_key: requireDotenvValue(process.env.SEAWEEDFS_ADMIN_SECRET_KEY, "SEAWEEDFS_ADMIN_SECRET_KEY"),
    },
    consumerBuckets: decodeDotenvJsonList(process.env.SEAWEEDFS_CONSUMER_BUCKETS_JSON, "SEAWEEDFS_CONSUMER_BUCKETS_JSON"),
    tenantMount: requireDotenvValue(process.env.SEAWEEDFS_OPENBAO_MOUNT, "SEAWEEDFS_OPENBAO_MOUNT"),
    openbao: {
      baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL")),
      roleId: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_ROLE_ID, "OPENBAO_PLAYWRIGHT_ROLE_ID"),
      secretId: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SECRET_ID, "OPENBAO_PLAYWRIGHT_SECRET_ID"),
      mount: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_MOUNT, "OPENBAO_PLAYWRIGHT_MOUNT"),
    },
    semaphore: {
      baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.SEMAPHORE_BASE_URL, "SEMAPHORE_BASE_URL")),
      breakglassPath: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SEMAPHORE_PATH, "OPENBAO_PLAYWRIGHT_SEMAPHORE_PATH"),
      project: requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_PROJECT, "SEMAPHORE_WORKSPACES_PROJECT"),
    },
  };
}

function names(workspace) {
  return { bucket: `ws-${workspace}-state`, identity: `ws-${workspace}-provision` };
}

function digest(keys) {
  return createHash("sha256").update(`${keys.access_key}:${keys.secret_key}`).digest("hex");
}

async function runWorkspace(request, workspace, action) {
  const { openbao, semaphore } = env();
  const sem = await vaultedBreakglassSession(request, openbao, semaphore, semaphore.project, WORKSPACE_TEMPLATE);
  return runWorkspaceTask(sem, workspace, action, SEMAPHORE_POLL_MS);
}

async function expectWorkspace(request, workspace, action) {
  return expectWorkspaceSuccess(await runWorkspace(request, workspace, action), workspace, action);
}

async function workspaceKeys(request, workspace) {
  const { openbao, tenantMount } = env();
  const path = `${names(workspace).identity}/s3`;
  const read = await openbaoRead(request, openbao, tenantMount, path);
  expect(read.status, `OpenBao must hold ${tenantMount}/${path}`).toBe(200);
  expect(Object.keys(read.data).sort(), `${tenantMount}/${path} must hold exactly the two keys`).toEqual([
    "access_key",
    "secret_key",
  ]);
  return read.data;
}

function s3(request, keys) {
  const settings = env();
  const origin = new URL(settings.s3Url);
  return (method, bucket, key, { query = {}, body = "", headers = {} } = {}) => {
    const path = `/${bucket}${key ? `/${key}` : ""}`;
    const signed = sign({
      method,
      host: origin.host,
      path,
      region: settings.region,
      accessKey: keys.access_key,
      secretKey: keys.secret_key,
      query,
      payload: body,
    });
    const search = canonicalQuery(query);
    return request.fetch(`${origin.origin}${path}${search ? `?${search}` : ""}`, {
      method,
      headers: { ...headers, ...signed },
      data: body === "" ? undefined : body,
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
  };
}

async function expectDenied(response, what) {
  const body = await response.text();
  expect(response.status(), `${what} must be refused`).toBe(403);
  expect(body, `${what} must answer AccessDenied`).toContain("<Code>AccessDenied</Code>");
}

async function versioning(request, bucket) {
  const response = await s3(request, env().admin)("GET", bucket, "", { query: { versioning: "" } });
  expect(response.status(), `GetBucketVersioning on ${bucket} must answer`).toBe(200);
  return (await response.text()).match(/<Status>([^<]*)<\/Status>/)?.[1] || "";
}

async function versions(request, bucket) {
  const response = await s3(request, env().admin)("GET", bucket, "", { query: { versions: "" } });
  expect(response.status(), `ListObjectVersions on ${bucket} must answer`).toBe(200);
  const xml = await response.text();
  return [...xml.matchAll(/<(?:Version|DeleteMarker)>([\s\S]*?)<\/(?:Version|DeleteMarker)>/g)].map((entry) => ({
    key: entry[1].match(/<Key>([\s\S]*?)<\/Key>/)[1],
    versionId: entry[1].match(/<VersionId>([\s\S]*?)<\/VersionId>/)[1],
  }));
}

async function purge(request, bucket, key) {
  const admin = s3(request, env().admin);
  for (const version of (await versions(request, bucket)).filter((entry) => entry.key === key)) {
    const removed = await admin("DELETE", bucket, key, { query: { versionId: version.versionId } });
    expect(removed.status(), `version ${version.versionId} of ${bucket}/${key} must be deleted`).toBe(204);
  }
}

async function whileProbing(request, body) {
  const url = `${env().s3Url}/status`;
  const probes = { answered: 0, failed: [] };
  let running = true;
  const loop = (async () => {
    while (running) {
      const status = await request
        .get(url, { failOnStatusCode: false, timeout: resolveTimeout(5_000) })
        .then(
          (response) => response.status(),
          (error) => `no answer (${error.message.split("\n")[0]})`,
        );
      if (status === 200) {
        probes.answered += 1;
      } else {
        probes.failed.push(status);
      }
      await new Promise((resolve) => setTimeout(resolve, PROBE_INTERVAL_MS));
    }
  })();
  try {
    return { value: await body(), probes };
  } finally {
    running = false;
    await loop;
  }
}

function expectNoRestart(probes, what) {
  expect(probes.answered, `the S3 gateway must have been probed while ${what} ran`).toBeGreaterThan(0);
  expect(probes.failed, `the S3 gateway must answer every probe while ${what} runs, so it never restarts`).toEqual([]);
}

test.describe.serial("workspace buckets", () => {
  test.skip(!enabled, "no Semaphore Workspaces project with OpenBao runs beside SeaweedFS, so no workspace apply can start");

  const first = randomUUID();
  const second = randomUUID();
  const scratch = `playwright-${randomUUID()}`;
  const applied = new Set();

  test.afterAll(async ({ playwright }) => {
    test.setTimeout(resolveTimeout(3 * WORKSPACE_RUN_MS));
    const request = await playwright.request.newContext({ ignoreHTTPSErrors: true });
    try {
      for (const workspace of applied) {
        await expectWorkspace(request, workspace, "destroy");
      }
      const removed = await s3(request, env().admin)("DELETE", scratch, "");
      expect([204, 404], `the scratch bucket ${scratch} must be removed, got ${removed.status()}`).toContain(removed.status());
    } finally {
      await request.dispose();
    }
  });

  test("workspace buckets: apply creates a versioned bucket without a restart", async ({ request }) => {
    test.setTimeout(resolveTimeout(WORKSPACE_RUN_MS + 300_000));
    applied.add(first);
    const { probes } = await whileProbing(request, () => expectWorkspace(request, first, "apply"));
    expectNoRestart(probes, `apply of ws-${first}`);
    const { bucket } = names(first);
    expect(await versioning(request, bucket), `GetBucketVersioning must report ${bucket} Enabled`).toBe("Enabled");
    const keys = await workspaceKeys(request, first);
    const listed = await s3(request, keys)("GET", bucket, "", { query: { "list-type": "2" } });
    expect(listed.status(), `${names(first).identity} must list ${bucket} right after apply`).toBe(200);
  });

  test("workspace buckets: an identity reaches only its own bucket", async ({ request }) => {
    test.setTimeout(resolveTimeout(WORKSPACE_RUN_MS + 300_000));
    applied.add(second);
    await expectWorkspace(request, second, "apply");
    const created = await s3(request, env().admin)("PUT", scratch, "");
    expect(created.status(), `the administrator creates the scratch bucket ${scratch}`).toBe(200);
    const own = names(first).bucket;
    const asFirst = s3(request, await workspaceKeys(request, first));
    expect((await asFirst("PUT", own, "reach.txt", { body: "reach" })).status(), `the identity writes ${own}`).toBe(200);
    const read = await asFirst("GET", own, "reach.txt");
    expect(read.status(), `the identity reads ${own}`).toBe(200);
    expect(await read.text()).toBe("reach");
    expect((await asFirst("GET", own, "", { query: { "list-type": "2" } })).status(), `the identity lists ${own}`).toBe(200);
    const { consumerBuckets } = env();
    expect(consumerBuckets.length, "a consumer bucket must exist beside the workspace buckets to prove the denial on it").toBeGreaterThan(0);
    for (const foreign of [names(second).bucket, scratch, ...consumerBuckets]) {
      await expectDenied(await asFirst("GET", foreign, "", { query: { "list-type": "2" } }), `listing ${foreign}`);
      await expectDenied(await asFirst("PUT", foreign, "intrusion.txt", { body: "intrusion" }), `writing ${foreign}`);
      await expectDenied(await asFirst("GET", foreign, "reach.txt"), `reading ${foreign}`);
    }
    await expectDenied(await asFirst("PUT", `playwright-${randomUUID()}`, ""), "CreateBucket");
    await expectDenied(await asFirst("PUT", own, "", { query: { acl: "" } }), `PutBucketAcl on ${own}`);
  });

  test("workspace buckets: a second apply changes nothing", async ({ request }) => {
    test.setTimeout(resolveTimeout(WORKSPACE_RUN_MS + 300_000));
    const { bucket } = names(first);
    const before = await workspaceKeys(request, first);
    const asFirst = s3(request, before);
    expect((await asFirst("PUT", bucket, "kept.txt", { body: "kept" })).status(), `the identity writes ${bucket}`).toBe(200);
    await expectWorkspace(request, first, "apply");
    const after = await workspaceKeys(request, first);
    expect(digest(after), "a second apply must keep the keys of the workspace identity").toBe(digest(before));
    const kept = await asFirst("GET", bucket, "kept.txt");
    expect(kept.status(), `${bucket}/kept.txt must survive the second apply`).toBe(200);
    expect(await kept.text()).toBe("kept");
    expect(await versioning(request, bucket), `${bucket} must stay versioned`).toBe("Enabled");
  });

  test("workspace buckets: reload adds and removes identities live", async ({ request }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_RUN_MS + 300_000));
    const workspace = randomUUID();
    const { bucket } = names(workspace);
    applied.add(workspace);
    const added = await whileProbing(request, () => expectWorkspace(request, workspace, "apply"));
    const keys = await workspaceKeys(request, workspace);
    const asWorkspace = s3(request, keys);
    expect(
      (await asWorkspace("GET", bucket, "", { query: { "list-type": "2" } })).status(),
      "the first request with the new keys must succeed",
    ).toBe(200);
    const removed = await whileProbing(request, () => expectWorkspace(request, workspace, "destroy"));
    applied.delete(workspace);
    expect(
      (await asWorkspace("GET", bucket, "", { query: { "list-type": "2" } })).status(),
      "the first request with the removed keys must fail",
    ).toBe(403);
    expectNoRestart(added.probes, `apply of ws-${workspace}`);
    expectNoRestart(removed.probes, `destroy of ws-${workspace}`);
  });

  test("workspace buckets: one of two conditional writers wins", async ({ request }) => {
    const { bucket } = names(first);
    const key = `playwright-${randomUUID()}.tflock`;
    const asFirst = s3(request, await workspaceKeys(request, first));
    const payloads = ["writer-a", "writer-b"];
    try {
      const answers = await Promise.all(
        payloads.map((payload) => asFirst("PUT", bucket, key, { body: payload, headers: { "If-None-Match": "*" } })),
      );
      expect(
        answers.map((answer) => answer.status()).sort(),
        "two conditional writers of one lock key must end with one 200 and one 412",
      ).toEqual([200, 412]);
      const winner = payloads[answers.findIndex((answer) => answer.status() === 200)];
      const stored = await asFirst("GET", bucket, key);
      expect(stored.status(), `the lock ${key} must be readable after the race`).toBe(200);
      expect(await stored.text(), "the stored lock must be the winner's").toBe(winner);
    } finally {
      await purge(request, bucket, key);
    }
  });

  test("workspace buckets: destroy removes access first and then the bucket", async ({ request }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_RUN_MS + 300_000));
    const { bucket } = names(second);
    const asSecond = s3(request, await workspaceKeys(request, second));
    expect(
      (await asSecond("PUT", bucket, "terraform.tfstate", { body: "{}" })).status(),
      `the identity writes a state file to ${bucket}`,
    ).toBe(200);
    const refused = await runWorkspace(request, second, "destroy");
    expect(refused.status, `destroy task ${refused.id} must refuse while ${bucket} holds a state file`).toBe("error");
    expect(
      refused.lines.some((line) => line.includes("terraform.tfstate")),
      `destroy task ${refused.id} must name the state file it refuses for`,
    ).toBe(true);
    expect(
      (await asSecond("GET", bucket, "terraform.tfstate")).status(),
      "the refused destroy must leave the identity and the bucket in place",
    ).toBe(200);
    await purge(request, bucket, "terraform.tfstate");

    const seen = [];
    let watching = true;
    const watch = (async () => {
      while (watching) {
        seen.push((await asSecond("GET", bucket, "", { query: { "list-type": "2" } })).status());
        await new Promise((resolve) => setTimeout(resolve, PROBE_INTERVAL_MS));
      }
    })();
    try {
      await expectWorkspace(request, second, "destroy");
      applied.delete(second);
    } finally {
      watching = false;
      await watch;
    }
    const firstRefusal = seen.indexOf(403);
    expect(firstRefusal, "the identity must be refused once destroy removed it").toBeGreaterThanOrEqual(0);
    expect(
      seen.slice(0, firstRefusal).every((status) => status === 200),
      `the identity must reach the bucket until it is refused, never find it gone first (saw ${[...new Set(seen)].join(", ")})`,
    ).toBe(true);
    expect(
      seen.slice(firstRefusal).every((status) => status === 403),
      "once refused, the identity must stay refused",
    ).toBe(true);
    const gone = await s3(request, env().admin)("HEAD", bucket, "");
    expect(gone.status(), `${bucket} must be gone after destroy`).toBe(404);
    const listing = await s3(request, env().admin)("GET", bucket, "", { query: { versions: "" } });
    expect(listing.status(), `no object version of ${bucket} may remain`).toBe(404);
  });
});
