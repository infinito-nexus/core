const https = require("node:https");
const net = require("node:net");
const { X509Certificate, createHash, randomUUID } = require("node:crypto");

const { test, expect } = require("@playwright/test");
const { decodeDotenvJsonList, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const {
  WORKSPACE_RUN_MS,
  WORKSPACE_TEMPLATE,
  expectWorkspaceSuccess,
  openbaoRead,
  runWorkspaceTask,
  vaultedBreakglassSession,
} = require("./personas/utils/workspace");
const { resolveTimeout } = require("./timeouts");

const INSTANCE_MS = 1_200_000;
const AGENT_MS = 600_000;
const POLL_MS = 3_000;
const PROBE_SECONDS = 5;
const SSH_PORT = 22;
const DNS_PORT = 53;
const BRIDGE_NAME_MAX = 15;
const OPERATION_PENDING = new Set(["Pending", "Running"]);
const IMAGE_SERVERS = { images: "https://images.linuxcontainers.org" };
const SILENT_PORT_CODES = new Set(["ECONNREFUSED", "ECONNRESET", "ETIMEDOUT"]);
const CONNECT_TIMEOUT_CODE = "CONNECT_TIMEOUT";
const SSHD_MARKER_DROP_IN = "/etc/ssh/sshd_config.d/00-playwright-marker.conf";
const MARK_SSH_BANNER = 'printf "VersionAddendum %s\\n" "$1" > "$2" && systemctl try-reload-or-restart ssh';
const CONNECT_PROBE =
  "import socket,sys\n" +
  "s=socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET)\n" +
  "s.settimeout(float(sys.argv[4]))\n" +
  "s.bind((sys.argv[1],0))\n" +
  "s.connect((sys.argv[2],int(sys.argv[3])))\n" +
  "print('connected')";

const apiEnabled = process.env.INCUS_API_ENABLED === "true";
const workspacesEnabled =
  process.env.INCUS_WORKSPACES_ENABLED === "true" && process.env.SEMAPHORE_WORKSPACES_ENABLED === "true";

test.use({ ignoreHTTPSErrors: true });

function settings() {
  return {
    apiUrl: normalizeBaseUrl(requireDotenvValue(process.env.INCUS_API_URL, "INCUS_API_URL")),
    allowedSources: decodeDotenvJsonList(process.env.INCUS_API_ALLOWED_SOURCES_JSON, "INCUS_API_ALLOWED_SOURCES_JSON"),
    agentsProject: requireDotenvValue(process.env.INCUS_AGENTS_PROJECT, "INCUS_AGENTS_PROJECT"),
    bridgePrefix: requireDotenvValue(process.env.INCUS_BRIDGE_PREFIX, "INCUS_BRIDGE_PREFIX"),
    image: requireDotenvValue(process.env.INCUS_IMAGE, "INCUS_IMAGE"),
    restrictions: JSON.parse(requireDotenvValue(process.env.INCUS_WORKSPACE_RESTRICTIONS_JSON, "INCUS_WORKSPACE_RESTRICTIONS_JSON")),
    limits: JSON.parse(requireDotenvValue(process.env.INCUS_WORKSPACE_LIMITS_JSON, "INCUS_WORKSPACE_LIMITS_JSON")),
    provision: {
      mount: requireDotenvValue(process.env.INCUS_PROVISION_MOUNT, "INCUS_PROVISION_MOUNT"),
      path: requireDotenvValue(process.env.INCUS_PROVISION_PATH, "INCUS_PROVISION_PATH"),
    },
    tenantMount: requireDotenvValue(process.env.INCUS_TENANT_MOUNT, "INCUS_TENANT_MOUNT"),
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

function apiPort() {
  const match = settings().apiUrl.match(/:(\d+)$/);
  expect(match, `INCUS_API_URL ${settings().apiUrl} must end in the API port`).toBeTruthy();
  return Number(match[1]);
}

function project(workspace) {
  return `ws-${workspace}`;
}

function bridgeOf(workspace) {
  return `${settings().bridgePrefix}${workspace.replace(/-/g, "")}`.slice(0, BRIDGE_NAME_MAX);
}

function expectedProjectConfig(workspace) {
  const { restrictions, limits } = settings();
  return {
    ...Object.fromEntries(Object.entries(restrictions).map(([key, value]) => [key, String(value)])),
    "restricted.networks.access": bridgeOf(workspace),
    "limits.containers": "0",
    "limits.instances": String(limits.instances),
    "limits.cpu": String(limits.cpu),
    "limits.memory": String(limits.memory),
    "limits.disk": String(limits.disk),
  };
}

function digest(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function runWorkspace(request, workspace, action) {
  const { openbao, semaphore } = settings();
  const sem = await vaultedBreakglassSession(request, openbao, semaphore, semaphore.project, WORKSPACE_TEMPLATE);
  return runWorkspaceTask(sem, workspace, action, POLL_MS * 3);
}

async function expectWorkspace(request, workspace, action) {
  return expectWorkspaceSuccess(await runWorkspace(request, workspace, action), workspace, action);
}

async function serverPin(request) {
  const { openbao, provision } = settings();
  const record = await openbaoRead(request, openbao, provision.mount, provision.path);
  expect(record.status, `OpenBao must hold the server record ${provision.mount}/${provision.path}`).toBe(200);
  expect(Object.keys(record.data).sort(), "the server record must hold endpoint, fingerprint and certificate").toEqual([
    "certificate",
    "endpoint",
    "fingerprint",
  ]);
  return record.data;
}

async function workspaceCredentials(request, workspace) {
  const path = `${project(workspace)}-provision/incus`;
  const read = await openbaoRead(request, settings().openbao, settings().tenantMount, path);
  expect(read.status, `OpenBao must hold ${settings().tenantMount}/${path}`).toBe(200);
  expect(Object.keys(read.data).sort(), `${path} must hold project, certificate, key and fingerprint`).toEqual([
    "certificate",
    "fingerprint",
    "key",
    "project",
  ]);
  expect(read.data.project, `${path} must name the project of the workspace`).toBe(project(workspace));
  return read.data;
}

function incus(pin, credentials, pinnedFingerprint = pin.fingerprint) {
  const base = new URL(settings().apiUrl);
  return (method, path, body) =>
    new Promise((resolve, reject) => {
      const payload = body === undefined ? undefined : JSON.stringify(body);
      const request = https.request(
        new URL(path, base),
        {
          method,
          ca: pin.certificate,
          cert: credentials ? credentials.certificate : undefined,
          key: credentials ? credentials.key : undefined,
          checkServerIdentity: (_host, peer) =>
            peer.fingerprint256.replace(/:/g, "").toLowerCase() === pinnedFingerprint
              ? undefined
              : new Error(`the Incus API presented ${peer.fingerprint256}, not the pinned server certificate`),
          headers: payload ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) } : {},
          timeout: resolveTimeout(60_000),
        },
        (response) => {
          let text = "";
          response.setEncoding("utf8");
          response.on("data", (chunk) => {
            text += chunk;
          });
          response.on("end", () => {
            const json = String(response.headers["content-type"]).includes("application/json") ? JSON.parse(text) : null;
            resolve({ status: response.statusCode, text, json });
          });
        },
      );
      request.on("timeout", () => request.destroy(new Error(`${method} ${path} got no answer`)));
      request.on("error", reject);
      request.end(payload);
    });
}

function metadata(response, what) {
  expect(response.status, `${what} must succeed`).toBe(200);
  return response.json.metadata;
}

function forbidden(response, what) {
  expect(response.status, `${what} must be refused with 403`).toBe(403);
}

async function awaitOperation(client, started, scope, what) {
  expect(started.status, `${what} must start an operation`).toBe(202);
  let state;
  await expect
    .poll(
      async () => {
        state = metadata(await client("GET", `${started.json.operation}?project=${scope}`), `reading the operation of ${what}`);
        return OPERATION_PENDING.has(state.status);
      },
      { timeout: resolveTimeout(INSTANCE_MS), intervals: [POLL_MS], message: `the operation of ${what} must finish` },
    )
    .toBe(false);
  return state;
}

async function expectSuccess(client, started, scope, what) {
  const state = await awaitOperation(client, started, scope, what);
  expect(state.status, `${what} must succeed (${state.err})`).toBe("Success");
  return state;
}

function imageSource() {
  const [remote, alias] = settings().image.split(/:(.*)/s);
  expect(IMAGE_SERVERS[remote], `the image ${settings().image} must come from a known remote`).toBeTruthy();
  return { type: "image", alias, server: IMAGE_SERVERS[remote], protocol: "simplestreams" };
}

async function createVm(client, scope, created) {
  const name = `playwright-${randomUUID().slice(0, 8)}`;
  created.add(`${scope}/${name}`);
  await expectSuccess(
    client,
    await client("POST", `/1.0/instances?project=${scope}`, { name, type: "virtual-machine", source: imageSource(), start: true }),
    scope,
    `creating and starting ${name} in ${scope}`,
  );
  return name;
}

async function removeVm(client, scope, name, created) {
  await expectSuccess(
    client,
    await client("PUT", `/1.0/instances/${name}/state?project=${scope}`, { action: "stop", force: true }),
    scope,
    `stopping ${name}`,
  );
  await expectSuccess(client, await client("DELETE", `/1.0/instances/${name}?project=${scope}`), scope, `deleting ${name}`);
  created.delete(`${scope}/${name}`);
}

async function expectNotCreated(client, scope, name, response, what) {
  if (response.status === 202) {
    const state = await awaitOperation(client, response, scope, what);
    expect(state.status, `${what} must fail`).toBe("Failure");
  } else {
    expect(response.status, `${what} must be refused`).toBeGreaterThanOrEqual(400);
  }
  expect((await client("GET", `/1.0/instances/${name}?project=${scope}`)).status, `${what} must leave no instance ${name}`).toBe(
    404,
  );
}

async function execIn(client, scope, name, command) {
  const started = await client("POST", `/1.0/instances/${name}/exec?project=${scope}`, {
    command,
    "wait-for-websocket": false,
    "record-output": true,
    interactive: false,
  });
  if (started.status !== 202) {
    return { code: null, stdout: "", error: started.text };
  }
  const state = await expectSuccess(client, started, scope, `running ${command[0]} in ${name}`);
  const stdout = await client("GET", `${state.metadata.output["1"]}?project=${scope}`);
  expect(stdout.status, `the recorded output of ${command[0]} in ${name} must be readable`).toBe(200);
  return { code: state.metadata.return, stdout: stdout.text };
}

async function awaitAgent(client, scope, name) {
  await expect
    .poll(async () => (await execIn(client, scope, name, ["true"])).code, {
      timeout: resolveTimeout(AGENT_MS),
      intervals: [POLL_MS * 5],
      message: `the agent of ${name} must run commands`,
    })
    .toBe(0);
}

async function connectFrom(client, scope, name, source, target, port) {
  return execIn(client, scope, name, ["python3", "-c", CONNECT_PROBE, source, target, String(port), String(PROBE_SECONDS)]);
}

async function addressesOf(client, scope, name) {
  let addresses = [];
  await expect
    .poll(
      async () => {
        const state = metadata(await client("GET", `/1.0/instances/${name}/state?project=${scope}`), `reading ${name}`);
        addresses = ((state.network || {}).eth0 || { addresses: [] }).addresses.filter((entry) => entry.scope === "global");
        return ["inet", "inet6"].every((family) => addresses.some((entry) => entry.family === family));
      },
      { timeout: resolveTimeout(AGENT_MS), intervals: [POLL_MS], message: `${name} must hold a global IPv4 and IPv6 address on eth0` },
    )
    .toBe(true);
  return {
    ipv4: addresses.find((entry) => entry.family === "inet").address,
    ipv6: addresses.find((entry) => entry.family === "inet6").address,
  };
}

async function bridgeConfig(client, workspace) {
  return metadata(await client("GET", `/1.0/networks/${bridgeOf(workspace)}`), `reading the bridge of ${project(workspace)}`).config;
}

function gateways(config) {
  return { ipv4: config["ipv4.address"].split("/")[0], ipv6: config["ipv6.address"].split("/")[0] };
}

function hostAddresses(config) {
  return [
    {
      host: new URL(settings().apiUrl).hostname,
      openPort: apiEnabled ? apiPort() : null,
      reason: "services.incus.api.enabled is off, so no listener proves this host reachable",
    },
    {
      host: gateways(config).ipv4,
      openPort: null,
      reason: "the runner reaches no port of the bridge gateway that the spec knows to be open",
    },
  ];
}

function within(cidr, address) {
  const [network, prefix] = cidr.split("/");
  const family = network.includes(":") ? "ipv6" : "ipv4";
  const list = new net.BlockList();
  list.addSubnet(network, Number(prefix), family);
  return list.check(address, family);
}

function listed(address) {
  return settings().allowedSources.some((source) => {
    const [network, prefix] = String(source).split("/");
    const family = network.includes(":") ? "ipv6" : "ipv4";
    const list = new net.BlockList();
    list.addSubnet(network, Number(prefix || (family === "ipv6" ? 128 : 32)), family);
    return list.check(address, family);
  });
}

function sshBanner(host, port) {
  return new Promise((resolve, reject) => {
    const socket = net.connect({ host, port, timeout: resolveTimeout(15_000) });
    socket.once("data", (data) => {
      socket.destroy();
      resolve(data.toString("utf8"));
    });
    socket.once("timeout", () => {
      const connected = !socket.connecting;
      socket.destroy();
      reject(
        connected
          ? Object.assign(new Error(`${host}:${port} accepted the connection and sent no SSH banner`), { code: "ETIMEDOUT" })
          : Object.assign(new Error(`${host}:${port} did not complete its lookup and TCP connection before the probe timed out`), {
              code: CONNECT_TIMEOUT_CODE,
            }),
      );
    });
    socket.once("end", () => {
      socket.destroy();
      reject(Object.assign(new Error(`${host}:${port} closed without an SSH banner`), { code: "ECONNRESET" }));
    });
    socket.once("error", reject);
  });
}

async function sshBannerIfAny(host, port) {
  try {
    return await sshBanner(host, port);
  } catch (error) {
    if (SILENT_PORT_CODES.has(error.code)) {
      return "";
    }
    throw error;
  }
}

function answersAt(host, port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port, timeout: resolveTimeout(15_000) });
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", (error) => resolve(error.code === "ECONNREFUSED"));
  });
}

async function hostSshBanner(address, port, note) {
  try {
    return await sshBannerIfAny(address.host, port);
  } catch (error) {
    if (error.code !== CONNECT_TIMEOUT_CODE) {
      throw error;
    }
    if (address.openPort === null) {
      note(`${address.host}:${port} did not connect and was not probed further: ${address.reason}`);
      return "";
    }
    if (await answersAt(address.host, address.openPort)) {
      return "";
    }
    throw new Error(`${address.host} is unreachable: neither port ${port} nor its open port ${address.openPort} completed a connection`, {
      cause: error,
    });
  }
}

async function expectNoInstanceSsh(address, port, marker, name, note) {
  expect(
    await hostSshBanner(address, port, note),
    `${name} must not answer SSH on ${address.host}:${port}, an address of the host`,
  ).not.toContain(marker);
}

async function markSshBanner(client, scope, name) {
  const marker = `playwright${randomUUID().replace(/-/g, "")}`;
  expect(
    (await execIn(client, scope, name, ["sh", "-c", MARK_SSH_BANNER, "sh", marker, SSHD_MARKER_DROP_IN])).code,
    `${name} must append ${marker} to its SSH banner`,
  ).toBe(0);
  return marker;
}

test("incus api: the listener answers on 8443", async ({ request }) => {
  test.skip(!apiEnabled, "services.incus.api.enabled is off in this variant, so the role opens no listener");
  expect(apiPort(), "the API listens on the conventional port").toBe(8443);
  const server = metadata(await incus(await serverPin(request))("GET", "/1.0"), "GET /1.0 on the Incus API");
  expect(server.api_version, "the listener must serve the Incus REST API").toBe("1.0");
  expect(server.auth, "a client without a certificate must stay untrusted").toBe("untrusted");
});

test("incus api: the provision runner pins the server certificate", async ({ request }) => {
  test.skip(!apiEnabled, "services.incus.api.enabled is off in this variant, so no server record is stored");
  const pin = await serverPin(request);
  expect(pin.endpoint, "the server record must name the address a container on this host dials").toBe(settings().apiUrl);
  expect(
    new X509Certificate(pin.certificate).fingerprint256.replace(/:/g, "").toLowerCase(),
    "the stored fingerprint must be the SHA-256 of the stored server certificate",
  ).toBe(pin.fingerprint);
  metadata(await incus(pin)("GET", "/1.0"), "a request pinned to the stored fingerprint");
  let answered = false;
  const wrong = digest(`not ${pin.fingerprint}`);
  const attempt = incus(pin, null, wrong)("POST", "/1.0/instances", { name: "never-sent" }).then((response) => {
    answered = true;
    return response;
  });
  await expect(attempt, "a client with the wrong pin must stop at the handshake").rejects.toThrow(/not the pinned server certificate/);
  expect(answered, "the server must never answer a client that stopped at the pin").toBe(false);
});

test.describe.serial("incus workspaces", () => {
  test.skip(!workspacesEnabled, "workspaces or the Semaphore Workspaces project are off in this variant, so no workspace apply can start");

  const first = randomUUID();
  const second = randomUUID();
  const applied = new Set();
  const created = new Set();
  const runsOfFirst = [];
  let instance;

  async function clientOf(request, workspace) {
    return incus(await serverPin(request), await workspaceCredentials(request, workspace));
  }

  test.afterAll(async ({ playwright }) => {
    test.setTimeout(resolveTimeout(3 * WORKSPACE_RUN_MS));
    const request = await playwright.request.newContext({ ignoreHTTPSErrors: true });
    try {
      for (const workspace of applied) {
        try {
          const client = await clientOf(request, workspace);
          for (const entry of [...created].filter((key) => key.startsWith(`${project(workspace)}/`))) {
            await removeVm(client, project(workspace), entry.split("/")[1], created);
          }
        } finally {
          await expectWorkspace(request, workspace, "destroy");
        }
      }
      expect([...created], "every instance the spec created must be removed").toEqual([]);
    } finally {
      await request.dispose();
    }
  });

  test("incus workspaces: apply creates a restricted project and certificate once", async ({ request }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_RUN_MS + 300_000));
    applied.add(first);
    runsOfFirst.push(await expectWorkspace(request, first, "apply"));
    const before = await workspaceCredentials(request, first);
    const client = incus(await serverPin(request), before);
    expect(metadata(await client("GET", "/1.0"), "GET /1.0 with the workspace certificate").auth, "the workspace certificate must be trusted").toBe(
      "trusted",
    );
    const config = metadata(await client("GET", `/1.0/projects/${project(first)}`), `reading ${project(first)}`).config;
    expect(config, `${project(first)} must carry the agents restrictions, its own bridge, VMs only and the plan's limits`).toEqual(
      expect.objectContaining(expectedProjectConfig(first)),
    );
    const trust = metadata(await client("GET", "/1.0/certificates?recursion=1"), "listing the trust store").filter(
      (entry) => entry.name === project(first),
    );
    expect(trust, `the trust store must hold exactly one entry for ${project(first)}`).toHaveLength(1);
    expect(trust[0].restricted, `the entry of ${project(first)} must be restricted`).toBe(true);
    expect(trust[0].projects, `the entry of ${project(first)} must reach its project alone`).toEqual([project(first)]);
    expect(trust[0].fingerprint, "OpenBao must hold the fingerprint of the trusted certificate").toBe(before.fingerprint);

    runsOfFirst.push(await expectWorkspace(request, first, "apply"));
    const after = await workspaceCredentials(request, first);
    expect(after.fingerprint, "a second apply must keep the certificate").toBe(before.fingerprint);
    expect(digest(after.key), "a second apply must keep the client key").toBe(digest(before.key));
    expect(
      metadata(await client("GET", `/1.0/projects/${project(first)}`), `reading ${project(first)} again`).config,
      "a second apply must leave the project as it was",
    ).toEqual(config);
    expect(
      metadata(await client("GET", "/1.0/certificates?recursion=1"), "listing the trust store again").filter(
        (entry) => entry.name === project(first),
      ),
      "a second apply must leave the trust entry as it was",
    ).toEqual(trust);
  });

  test("incus workspaces: no private key and no token on the host", async ({ request }) => {
    const credentials = await workspaceCredentials(request, first);
    expect(credentials.key, "OpenBao must hold the private key of the workspace certificate").toMatch(/^-----BEGIN PRIVATE KEY-----/);
    const client = incus(await serverPin(request), credentials);
    const entry = metadata(await client("GET", `/1.0/certificates/${credentials.fingerprint}`), "reading the trust entry");
    expect(entry.certificate.trim(), "the trust entry must hold the certificate OpenBao holds").toBe(credentials.certificate.trim());
    expect(entry.certificate, "the trust entry must hold no private key").not.toContain("PRIVATE KEY");
    const keyLines = credentials.key.split("\n").filter((line) => line.length > 0 && !line.startsWith("-----"));
    expect(runsOfFirst, "the apply runs of the first workspace must be on record").toHaveLength(2);
    for (const run of runsOfFirst) {
      expect(
        run.lines.filter((line) => line.includes("PRIVATE KEY") || keyLines.some((part) => line.includes(part))),
        `no line of workspace apply task ${run.id} may hold the private key`,
      ).toHaveLength(0);
    }
  });

  test("incus workspaces: a certificate reaches only its own project", async ({ request }) => {
    test.setTimeout(resolveTimeout(WORKSPACE_RUN_MS + 3 * INSTANCE_MS));
    applied.add(second);
    await expectWorkspace(request, second, "apply");
    const client = await clientOf(request, first);
    const own = project(first);
    const vm = await createVm(client, own, created);
    await removeVm(client, own, vm, created);

    for (const foreign of [project(second), settings().agentsProject]) {
      forbidden(await client("GET", `/1.0/instances?project=${foreign}`), `listing the instances of ${foreign}`);
      forbidden(
        await client("POST", `/1.0/instances?project=${foreign}`, { name: "intrusion", type: "virtual-machine", source: imageSource() }),
        `creating an instance in ${foreign}`,
      );
    }
    const container = `playwright-${randomUUID().slice(0, 8)}`;
    await expectNotCreated(
      client,
      own,
      container,
      await client("POST", `/1.0/instances?project=${own}`, { name: container, type: "container", source: imageSource() }),
      "creating a container",
    );
    const privileged = `playwright-${randomUUID().slice(0, 8)}`;
    await expectNotCreated(
      client,
      own,
      privileged,
      await client("POST", `/1.0/instances?project=${own}`, {
        name: privileged,
        type: "container",
        source: imageSource(),
        config: { "security.privileged": "true" },
      }),
      "creating a privileged instance",
    );
    const hostPath = `playwright-${randomUUID().slice(0, 8)}`;
    await expectNotCreated(
      client,
      own,
      hostPath,
      await client("POST", `/1.0/instances?project=${own}`, {
        name: hostPath,
        type: "virtual-machine",
        source: imageSource(),
        devices: { host: { type: "disk", source: "/etc", path: "/mnt/host" } },
      }),
      "attaching a host-path disk",
    );
    forbidden(
      await client("PATCH", `/1.0/projects/${own}`, { config: { "limits.instances": "99" } }),
      `setting limits.instances of ${own}`,
    );
    forbidden(await client("PATCH", "/1.0", { config: { "user.playwright": "intrusion" } }), "setting a server key");
  });

  test("incus workspaces: an instance answers on its own addresses", async ({ request }) => {
    test.setTimeout(resolveTimeout(2 * INSTANCE_MS));
    const client = await clientOf(request, first);
    const own = project(first);
    instance = await createVm(client, own, created);
    await awaitAgent(client, own, instance);
    const addresses = await addressesOf(client, own, instance);
    const config = await bridgeConfig(client, first);
    expect(within(config["ipv4.address"], addresses.ipv4), `${instance} must hold an IPv4 address of its slice`).toBe(true);
    expect(within(config["ipv6.address"], addresses.ipv6), `${instance} must hold an IPv6 address of its slice`).toBe(true);
    expect([config["ipv4.nat"], config["ipv6.nat"]], `the bridge of ${own} must route without NAT`).toEqual(["false", "false"]);
    expect(
      metadata(await client("GET", `/1.0/networks/${bridgeOf(first)}/forwards`), "listing the forwards of the bridge"),
      `no host address may forward to ${instance}`,
    ).toEqual([]);
    const marker = await markSshBanner(client, own, instance);
    await expect
      .poll(async () => sshBannerIfAny(addresses.ipv4, SSH_PORT), {
        timeout: resolveTimeout(AGENT_MS),
        intervals: [POLL_MS],
        message: `${instance} must answer SSH on ${addresses.ipv4} from outside the host with the banner it marked`,
      })
      .toMatch(new RegExp(`^SSH-2\\.0-[^\\r\\n]* ${marker}`));
    for (const address of hostAddresses(config)) {
      await expectNoInstanceSsh(address, SSH_PORT, marker, instance, (description) =>
        test.info().annotations.push({ type: "host address not probed", description }),
      );
    }
  });

  test("incus workspaces: a spoofed source address is dropped", async ({ request }) => {
    test.setTimeout(resolveTimeout(AGENT_MS));
    const client = await clientOf(request, first);
    const own = project(first);
    expect(instance, "the instance of the previous test must exist").toBeTruthy();
    const addresses = await addressesOf(client, own, instance);
    const gateway = gateways(await bridgeConfig(client, first));
    const gatewayOctets = gateway.ipv4.split(".");
    const foreignHost = [13, 12]
      .map((offset) => [...gatewayOctets.slice(0, 3), String(Number(gatewayOctets[3]) + offset)].join("."))
      .find((candidate) => candidate !== addresses.ipv4);
    const spoofed = { ipv4: foreignHost, ipv6: gateway.ipv6.replace(/::1$/, "::5ca1:ab1e") };
    expect(spoofed.ipv6, `the IPv6 gateway ${gateway.ipv6} must end in ::1 so a foreign address of the slice can be built`).not.toBe(gateway.ipv6);
    expect((await execIn(client, own, instance, ["ip", "addr", "add", `${spoofed.ipv4}/32`, "dev", "eth0"])).code, "the spoofed IPv4 address must be added").toBe(0);
    expect(
      (await execIn(client, own, instance, ["ip", "-6", "addr", "add", `${spoofed.ipv6}/128`, "dev", "eth0", "nodad"])).code,
      "the spoofed IPv6 address must be added",
    ).toBe(0);
    for (const family of ["ipv4", "ipv6"]) {
      expect(
        (await connectFrom(client, own, instance, addresses[family], gateway[family], DNS_PORT)).code,
        `${instance} must reach the bridge DNS from its own ${family} address`,
      ).toBe(0);
      expect(
        (await connectFrom(client, own, instance, spoofed[family], gateway[family], DNS_PORT)).code,
        `a packet from the foreign ${family} address ${spoofed[family]} must be dropped`,
      ).not.toBe(0);
    }
  });

  test("incus api: an address off the list is dropped", async ({ request }) => {
    test.skip(!apiEnabled, "services.incus.api.enabled is off in this variant, so the role opens no listener");
    test.setTimeout(resolveTimeout(AGENT_MS));
    const client = await clientOf(request, first);
    const own = project(first);
    expect(instance, "the instance of a previous test must exist").toBeTruthy();
    const addresses = await addressesOf(client, own, instance);
    const gateway = gateways(await bridgeConfig(client, first));
    for (const family of ["ipv4", "ipv6"]) {
      expect(listed(addresses[family]), `${addresses[family]} must lie off services.incus.api.allowed_sources`).toBe(false);
      expect(
        (await connectFrom(client, own, instance, addresses[family], gateway[family], DNS_PORT)).code,
        `${instance} must reach the host on ${gateway[family]}`,
      ).toBe(0);
      expect(
        (await connectFrom(client, own, instance, addresses[family], gateway[family], apiPort())).code,
        `the API port must drop ${addresses[family]}, which is off the list`,
      ).not.toBe(0);
    }
  });

  test("incus workspaces: workspace bridges are isolated", async ({ request }) => {
    test.setTimeout(resolveTimeout(2 * INSTANCE_MS));
    const asFirst = await clientOf(request, first);
    const asSecond = await clientOf(request, second);
    expect(instance, "the instance of a previous test must exist").toBeTruthy();
    const neighbour = await createVm(asSecond, project(second), created);
    await awaitAgent(asSecond, project(second), neighbour);
    const mine = await addressesOf(asFirst, project(first), instance);
    const theirs = await addressesOf(asSecond, project(second), neighbour);
    expect(await sshBanner(theirs.ipv4, SSH_PORT), `${neighbour} must answer SSH, so a refused connection means isolation`).toMatch(/^SSH-2\.0-/);
    for (const family of ["ipv4", "ipv6"]) {
      expect(
        (await connectFrom(asFirst, project(first), instance, mine[family], theirs[family], SSH_PORT)).code,
        `${project(first)} must not reach ${project(second)} over ${family}`,
      ).not.toBe(0);
      expect(
        (await connectFrom(asSecond, project(second), neighbour, theirs[family], mine[family], SSH_PORT)).code,
        `${project(second)} must not reach ${project(first)} over ${family}`,
      ).not.toBe(0);
    }
    await removeVm(asSecond, project(second), neighbour, created);
  });

  test("incus workspaces: destroy removes project, bridge and certificate", async ({ request }) => {
    test.setTimeout(resolveTimeout(2 * WORKSPACE_RUN_MS + INSTANCE_MS));
    const credentials = await workspaceCredentials(request, first);
    const pin = await serverPin(request);
    const client = incus(pin, credentials);
    const own = project(first);
    expect(instance, "the instance of a previous test must exist").toBeTruthy();
    const refused = await runWorkspace(request, first, "destroy");
    expect(refused.status, `destroy task ${refused.id} must refuse while ${own} holds ${instance}`).toBe("error");
    expect(
      refused.lines.some((line) => line.includes(instance)),
      `destroy task ${refused.id} must name the instance it refuses for`,
    ).toBe(true);
    expect(metadata(await client("GET", "/1.0"), "GET /1.0 after the refused destroy").auth, "the refused destroy must keep the certificate").toBe(
      "trusted",
    );
    await removeVm(client, own, instance, created);

    await expectWorkspace(request, first, "destroy");
    applied.delete(first);
    expect(metadata(await client("GET", "/1.0"), "GET /1.0 after destroy").auth, "destroy must remove the trust entry").toBe("untrusted");
    const witness = await clientOf(request, second);
    expect(
      metadata(await witness("GET", "/1.0/certificates?recursion=1"), "listing the trust store").filter((entry) => entry.name === own),
      `no trust entry of ${own} may remain`,
    ).toEqual([]);
    expect(
      metadata(await witness("GET", "/1.0/networks?recursion=1"), "listing the networks")
        .filter((network) => (network.config || {})["user.infinito.workspace"] === first)
        .map((network) => network.name),
      `no bridge of ${own} may remain`,
    ).toEqual([]);
    const record = await openbaoRead(request, settings().openbao, settings().tenantMount, `${own}-provision/incus`);
    expect(record.status, "destroy must drop the client key from OpenBao").toBe(404);
  });
});
