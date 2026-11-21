const crypto = require("node:crypto");
const dgram = require("node:dgram");
const dns = require("node:dns");
const https = require("node:https");
const net = require("node:net");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvJsonList, decodeDotenvQuotedValue, requireDotenvValue } = require("./personas");
const { sign } = require("./personas/utils/s3");
const { TASK_FINISHED,sshEd25519PublicLine, strictFlag, targetAddressIn } = require("./personas/utils/workspace");
const workspaces = require("./workspace-fixture");

const LABEL = "provision";
const WORKSPACE_MS = 30 * 60_000;
const PROVISION_MS = 30 * 60_000;
const DESTROY_MS = 20 * 60_000;
const DNS_MS = 10 * 60_000;
const UNLOCK_MS = 10 * 60_000;
const PROBE_MS = 10 * 60_000;
const DEPLOY_LINE_MS = 15 * 60_000;
const BOOT_MS = 10 * 60_000;
const RECORD_MS = 2 * 60_000;
const REQUEST_MS = 30_000;
const DNS_QUERY_MS = 5_000;
const SSH_PROBE_MS = 15_000;
const POLL_MS = 5_000;
const BASE_MS = 2 * WORKSPACE_MS + 60 * REQUEST_MS;
const SERVER_MS = PROVISION_MS + DESTROY_MS + BOOT_MS + 4 * RECORD_MS;
const STATE_REGION = "us-east-1";
const PLATFORM_MOUNT = "platform";
const TENANT_MOUNT = "tenant";
const SSH_PORT = 22;
const DNS_PORT = 53;
const DNS_TRIES = 2;
const MINIMUM_OPENTOFU = [1, 10, 0];
const OUTPUT_KEYS = ["fqdn", "host", "host_key", "server_id"];
const HOST_KEY_LINE = /^ssh-ed25519 [A-Za-z0-9+/]+={0,3}$/;
const LOCK_FAILURE = "Error acquiring the state lock";
const INITIALIZED = "OpenTofu has been successfully initialized!";
const NOTHING_CHANGED = "Apply complete! Resources: 0 added, 0 changed, 0 destroyed.";
const APPLIED = /Apply complete! Resources: ([0-9]+) added, ([0-9]+) changed, ([0-9]+) destroyed\./;
const DESTROYED = /Destroy complete! Resources: ([0-9]+) destroyed\./;
const DEPLOYING = /^deploy\.sh: deploying (\S+) of (\S+)\/(\S+) to (\S+) as (\S+)$/;
const OPENTOFU_LINE = /^OpenTofu v/;
const INSECURE = /INSECURE/i;
const EMPTY_INVENTORY = "all:\n  hosts: {}\n";
const NO_CA_FILE = "none";
const PROVISION_SCRIPT = "roles/web-app-semaphore/files/shell/repository/provision.sh";
const LOGIN_PROBE_SCRIPT = [
  "set -uo pipefail",
  'export SALES_ORDER="$1" LINE="$2" PROVIDER_TOKEN="$3"',
  `"\${INFINITO_SRC_DIR}/${PROVISION_SCRIPT}" "$4"`,
  "printf 'PROBE exit %s\\n' \"$?\"",
  "",
].join("\n");
const ROUTE53_ORIGIN = "https://route53.amazonaws.com"; // nocheck: url  Reason: the Route 53 API endpoint; GET / answers 404, the API paths answer
const ROUTE53_VERSION = "2013-04-01";
const ROUTE53_NAMESPACE = `${ROUTE53_ORIGIN}/doc/${ROUTE53_VERSION}/`;
const ROUTE53_REGION = "us-east-1";
const ROUTE53_SERVICE = "route53";
const ROUTE53_CONTENT_TYPE = "text/xml";
const ROUTE53_SIGNED_HEADERS = "content-type;host;x-amz-date";
const PROVIDER_ROLES = { incus: "svc-virt-incus", proxmox: "web-app-proxmox" };
const PROVIDERS = ["incus", "proxmox"];
const JWT_MOUNT = "jwt";
const STORE_SEMAPHORE_PATH = "store/semaphore";
const GUEST = "guest";
const RUN_AND_READ = 1 | 128;
const ORDER_ACTIONS = ["provision", "destroy"];
const SHARED_KINDS = ["unlock", "dns", "zone"];
const ZONE_MS = 10 * 60_000;
const ZONE_KEYS = ["name_servers", "status", "zone", "zone_id"];
const ENVELOPE_KEYS = ["encrypted_data", "encryption_version"];
const PLAINTEXT_KEYS = ["resources", "outputs", "check_results"];
const STATE_LIST_FAILED = "tofu state list exited with";
const PROVISION_SECRET_ENV = /^(AWS_|HCLOUD_TOKEN$|IONOS_TOKEN$|OS_|PROXMOX_VE_|INCUS_|DNS_UPDATE_|CLOUDFLARE_API_TOKEN$|BAO_TOKEN$|VAULT_TOKEN$)/;
const PROVISION_PATHS = (workspace) => [
  `${TENANT_MOUNT}/data/ws-${workspace}-provision/s3`,
  `${TENANT_MOUNT}/data/ws-${workspace}-provision/dns`,
  `${TENANT_MOUNT}/data/ws-${workspace}-provision/incus`,
  `${TENANT_MOUNT}/data/ws-${workspace}-provision/proxmox`,
  `${TENANT_MOUNT}/data/ws-${workspace}-provision/scs`,
  `${PLATFORM_MOUNT}/data/provision/hetzner`,
  `${PLATFORM_MOUNT}/data/provision/ionos`,
  `${PLATFORM_MOUNT}/data/provision/cloudflare-zones`,
];
const CUSTOMER_TOKEN_PATH = (workspace, provider) => `ws-${workspace}-provision/providers/${provider}`;
const ALL_PROVIDERS = ["hetzner", "ionos", "scs", "proxmox", "incus"];
const PROBE_HOST = "probe";
const FOREIGN_ZONE = "example.net";
const PROBE_RUN_FIELDS = ["app", "playbook", "arguments", "repository_id", "inventory_id", "survey_vars"];
const FOREIGN_PROVIDER_PATHS = (workspace, provider) => [
  ...ALL_PROVIDERS.filter((other) => other !== provider).flatMap((other) => [
    `${PLATFORM_MOUNT}/data/provision/${other}`,
    `${PLATFORM_MOUNT}/data/provision/${other}-${PROBE_HOST}`,
    `${TENANT_MOUNT}/data/ws-${workspace}-provision/${other}`,
    `${TENANT_MOUNT}/data/${CUSTOMER_TOKEN_PATH(workspace, other)}`,
  ]),
  `${PLATFORM_MOUNT}/data/provision/cloudflare-zones`,
  `${PLATFORM_MOUNT}/data/provision/cloudflare/${FOREIGN_ZONE}`,
];
const SCS_REGION_KEYS = ["auth_url", "region", "network"];
const SCS_COMPUTE = "compute";
const SCS_INTERFACE = "public";
const DNS_UPDATE_OPCODE = 5;
const DNS_TYPES = { SOA: 6, A: 1, MX: 15, TXT: 16, TSIG: 250 };
const DNS_CLASS_IN = 1;
const DNS_CLASS_ANY = 255;
const DNS_RCODES = { 0: "NOERROR", 5: "REFUSED", 9: "NOTAUTH" };
const DNS_REFUSALS = ["REFUSED", "NOTAUTH"];
const TSIG_FUDGE = 300;
const UPDATE_TTL = 60;
const DNS_UPDATE_SENDS = 2;
const CONTROL_ADDRESS = "192.0.2.53";
const CURL_CA = '${cacert[@]+"${cacert[@]}"}';
const OWN_TENANT_PATH = (workspace) => `${TENANT_MOUNT}/data/ws-${workspace}/playwright-isolation-probe`;
const ISOLATION_PROBE_SCRIPT = [
  "set -euo pipefail",
  "for name in $(compgen -e); do printf 'PROBE env %s\\n' \"${name}\"; done",
  'origin="$1"; cafile="$2"; role="$3"; shift 3',
  'cacert=(); if [ -f "${cafile}" ]; then cacert=(--cacert "${cafile}"); fi',
  "body=$(python3 -c 'import json, os, sys; print(json.dumps({\"role\": sys.argv[1], \"jwt\": os.environ[\"SEMAPHORE_JWT\"]}))' \"${role}\")",
  `token=$(printf '%s' "\${body}" | curl -sS ${CURL_CA} -X POST -H 'Content-Type: application/json' --data @- "\${origin}/v1/auth/${JWT_MOUNT}/login" | python3 -c 'import json, sys; print(json.load(sys.stdin)["auth"]["client_token"])')`,
  "[ -n \"${token}\" ] || { printf 'PROBE login failed\\n'; exit 1; }",
  `for path in "$@"; do printf 'PROBE status %s %s\\n' "\${path}" "$(curl -sS -o /dev/null -w '%{http_code}' ${CURL_CA} -H "X-Vault-Token: \${token}" "\${origin}/v1/\${path}")"; done`,
  `curl -sS -o /dev/null ${CURL_CA} -X POST -H "X-Vault-Token: \${token}" "\${origin}/v1/auth/token/revoke-self"`,
  "",
].join("\n");
const LOGIN_STATUS_SCRIPT = [
  "set -euo pipefail",
  'origin="$1"; cafile="$2"; shift 2',
  'cacert=(); if [ -f "${cafile}" ]; then cacert=(--cacert "${cafile}"); fi',
  'answer="$(mktemp)"',
  'for role in "$@"; do',
  "  body=$(python3 -c 'import json, os, sys; print(json.dumps({\"role\": sys.argv[1], \"jwt\": os.environ[\"SEMAPHORE_JWT\"]}))' \"${role}\")",
  `  status=$(printf '%s' "\${body}" | curl -sS ${CURL_CA} -o "\${answer}" -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data @- "\${origin}/v1/auth/${JWT_MOUNT}/login")`,
  "  printf 'PROBE login %s %s\\n' \"${role}\" \"${status}\"",
  '  if [ "${status}" = 200 ]; then',
  `    token=$(python3 -c 'import json, sys; print(json.load(sys.stdin)["auth"]["client_token"])' < "\${answer}")`,
  `    curl -sS -o /dev/null ${CURL_CA} -X POST -H "X-Vault-Token: \${token}" "\${origin}/v1/auth/token/revoke-self"`,
  "  fi",
  "done",
  'rm -f "${answer}"',
  "",
].join("\n");
const LOGIN_REFUSED = ["400", "403"];

/**
 * Args:
 *   value: a value a catalog or an OpenBao record holds as a boolean or its text.
 *
 * Returns:
 *   Whether it reads as true.
 */
function truthy(value) {
  return String(value).toLowerCase() === "true";
}

const { bare, probeLines } = workspaces;

/**
 * Args:
 *   run: a result of `workspaces.runTemplate` that also carries `what`.
 *   needle: the text one output line has to hold.
 */
function expectLine(run, needle) {
  expect(
    run.lines.some((line) => bare(line).includes(needle)),
    `${run.what}: task ${run.task.id} must print "${needle}"; output tail:\n${workspaces.outputTail(run.lines)}`,
  ).toBe(true);
}

/**
 * Args:
 *   run: a result of `workspaces.runTemplate` that also carries `what`.
 *   needle: the text no output line may hold.
 */
function expectNoLine(run, needle) {
  expect(
    run.lines.some((line) => bare(line).includes(needle)),
    `${run.what}: task ${run.task.id} must not print "${needle}"; output tail:\n${workspaces.outputTail(run.lines)}`,
  ).toBe(false);
}

/**
 * Args:
 *   run: a result of `workspaces.runTemplate` that also carries `what`.
 *
 * Returns:
 *   `added`, `changed` and `destroyed` of the apply summary the task printed.
 */
function appliedCounts(run) {
  const match = run.lines.map((line) => APPLIED.exec(bare(line))).find(Boolean);
  expect(match, `${run.what}: task ${run.task.id} must print the apply summary; output tail:\n${workspaces.outputTail(run.lines)}`).toBeTruthy();
  return { added: Number(match[1]), changed: Number(match[2]), destroyed: Number(match[3]) };
}

/**
 * Args:
 *   run: a result of `workspaces.runTemplate` that also carries `what`.
 *
 * Returns:
 *   The count of the destroy summary the task printed.
 */
function destroyedCount(run) {
  const match = run.lines.map((line) => DESTROYED.exec(bare(line))).find(Boolean);
  expect(match, `${run.what}: task ${run.task.id} must print the destroy summary; output tail:\n${workspaces.outputTail(run.lines)}`).toBeTruthy();
  return Number(match[1]);
}

/**
 * Args:
 *   version: a dotted version such as 1.13.9.
 *   minimum: the lowest admitted version as numbers.
 *
 * Returns:
 *   Whether the version is the minimum or newer.
 */
function atLeast(version, minimum) {
  const parts = version.split(".").map(Number);
  for (const [index, floor] of minimum.entries()) {
    if ((parts[index] || 0) !== floor) {
      return (parts[index] || 0) > floor;
    }
  }
  return true;
}

/**
 * Returns:
 *   The last usable IPv4 address of the first private target network wide
 *   enough to hold one, an address workspace apply accepts as a target.
 */
function privateTargetAddress() {
  return targetAddressIn(
    decodeDotenvJsonList(process.env.SEMAPHORE_WORKSPACES_PRIVATE_TARGETS_JSON, "SEMAPHORE_WORKSPACES_PRIVATE_TARGETS_JSON"),
    LABEL,
  );
}

/**
 * Args:
 *   salesOrder: the Sales Order the line belongs to.
 *   line: the line number as text.
 *
 * Returns:
 *   The order line with a fresh DNS label and its name `<SALES_ORDER>-<LINE>`.
 */
function orderLine(salesOrder, line) {
  return { salesOrder, line, label: `pw${crypto.randomBytes(5).toString("hex")}`, name: `${salesOrder}-${line}` };
}

function freshSalesOrder() {
  return `PW${crypto.randomBytes(5).toString("hex").toUpperCase()}`;
}

/**
 * Args:
 *   order: an order line of `orderLine`.
 *
 * Returns:
 *   The survey of unlock.
 */
function orderSurvey(order) {
  return { SALES_ORDER: order.salesOrder, LINE: order.line };
}

/**
 * Args:
 *   order: an order line of `orderLine`.
 *
 * Returns:
 *   The survey of provision and destroy on the platform's provider token.
 */
function providerSurvey(order) {
  return { ...orderSurvey(order), PROVIDER_TOKEN: "platform" };
}

/**
 * Args:
 *   order: an order line of `orderLine`.
 *
 * Returns:
 *   The survey of provision and destroy on the customer's own credential.
 */
function customerSurvey(order) {
  return { ...orderSurvey(order), PROVIDER_TOKEN: "workspace" };
}

/**
 * Returns:
 *   `id` and `secret` of the application credential of the SCS test
 *   project; the test skips when either is empty. Only a test of
 *   `registerScs` may call it, since a trace keeps the body of the OpenBao
 *   write.
 */
function scsTestCredential() {
  const scsCredentialId = decodeDotenvQuotedValue(process.env.PROVISION_SCS_TEST_CREDENTIAL_ID);
  const scsCredentialSecret = decodeDotenvQuotedValue(process.env.PROVISION_SCS_TEST_CREDENTIAL_SECRET);
  test.skip(
    !scsCredentialId || !scsCredentialSecret,
    "PROVISION_SCS_TEST_CREDENTIAL_ID or PROVISION_SCS_TEST_CREDENTIAL_SECRET is empty: secrets.credentials.scs_test_application_credential_id and _secret name no SCS test project, so no customer credential can run",
  );
  return { id: scsCredentialId, secret: scsCredentialSecret };
}

/**
 * Args:
 *   method: the HTTP method.
 *   url: an `https` URL of the SCS cloud.
 *   headers: the request headers.
 *   body: the JSON body, `null` for none.
 *
 * Returns:
 *   `{status, headers, json()}` of the answer, sent from Node with TLS
 *   verified against Node's trust store and through no proxy, so neither
 *   the Tor exit of an onion pass nor a browser trace sees the request.
 *   `json()` parses the body, `null` for none, and throws if it is no JSON,
 *   so a caller holding a token revokes it first. A failure, also a
 *   connection that drops before the answer is complete, names the method,
 *   host and path, and the error code if any.
 */
function scsRequest(method, url, headers, body) {
  const target = new URL(url);
  const what = `${method} ${target.host}${target.pathname}`;
  const payload = body === null ? null : JSON.stringify(body);
  const sent = payload === null ? headers : { ...headers, "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) };
  return new Promise((resolve, reject) => {
    const request = https.request(
      target,
      { method, headers: sent, agent: new https.Agent(), rejectUnauthorized: true, timeout: resolveTimeout(REQUEST_MS) },
      (response) => {
        let text = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          text += chunk;
        });
        response.on("end", () => {
          resolve({
            status: response.statusCode,
            headers: response.headers,
            json() {
              let parsed;
              try {
                parsed = text ? JSON.parse(text) : null;
              } catch {
                parsed = undefined;
              }
              if (parsed === undefined) {
                throw new Error(`${what} answered no JSON`);
              }
              return parsed;
            },
          });
        });
        response.on("close", () => {
          if (!response.complete) {
            reject(new Error(`${what} failed: aborted`));
          }
        });
      },
    );
    request.on("timeout", () => request.destroy(Object.assign(new Error("timeout"), { code: "ETIMEDOUT" })));
    request.on("error", (error) => reject(new Error(`${what} failed${error.code ? `: ${error.code}` : ""}`)));
    request.end(payload === null ? undefined : payload);
  });
}

/**
 * Args:
 *   offer: an scs offer of `catalogOffers`.
 *   credential: the result of `scsTestCredential`, never logged.
 *
 * Returns:
 *   `project`, the project the credential is scoped to,
 *   `serversNamed(name)`, the servers of that name the project holds as
 *   `{id, tenant_id}`, both read through `scsRequest` with the credential at
 *   the catalog's Keystone, never with a platform credential, and
 *   `revoke()`, which revokes the Keystone token they use; a failure before
 *   the return revokes it at once.
 */
async function scsProject(offer, credential) {
  const keystone = offer.place.auth_url.replace(/\/+$/, "");
  const login = await scsRequest("POST", `${keystone}/auth/tokens`, { Accept: "application/json" }, {
    auth: {
      identity: { methods: ["application_credential"], application_credential: { id: credential.id, secret: credential.secret } },
    },
  });
  expect(login.status, `${LABEL}: the Keystone login of the SCS test credential`).toBe(201);
  const token = login.headers["x-subject-token"];
  const revoke = async () => {
    const response = await scsRequest("DELETE", `${keystone}/auth/tokens`, { "X-Auth-Token": token, "X-Subject-Token": token }, null);
    expect([200, 204], `${LABEL}: the revoke of the Keystone token of the SCS test credential`).toContain(response.status);
  };
  try {
    const body = login.json().token;
    const endpoint = (body.catalog || [])
      .filter((service) => service.type === SCS_COMPUTE)
      .flatMap((service) => service.endpoints)
      .find((candidate) => candidate.interface === SCS_INTERFACE && candidate.region === offer.place.region);
    expect(endpoint, `${LABEL}: Keystone must list a ${SCS_INTERFACE} ${SCS_COMPUTE} endpoint in ${offer.place.region}`).toBeTruthy();
    return {
      project: body.project.id,
      revoke,
      async serversNamed(name) {
        const response = await scsRequest(
          "GET",
          `${endpoint.url.replace(/\/+$/, "")}/servers/detail?name=${encodeURIComponent(`^${name}$`)}`,
          { Accept: "application/json", "X-Auth-Token": token },
          null,
        );
        expect(response.status, `${LABEL}: the Nova list of the servers named ${name}`).toBe(200);
        return response.json().servers.map((server) => ({ id: server.id, tenant_id: server.tenant_id }));
      },
    };
  } catch (error) {
    await revoke().catch((failure) => console.warn(String(failure && failure.message).split("\n")[0]));
    throw error;
  }
}

/**
 * Args:
 *   action: create, remove or unlock.
 *   order: an order line of `orderLine`.
 *   host: the address the record points at.
 *
 * Returns:
 *   The survey of dns.
 */
function dnsSurvey(action, order, host) {
  return { DNS_ACTION: action, ...orderSurvey(order), HOST: host, DNS_LABEL: order.label };
}

/**
 * Args:
 *   provider: incus or proxmox.
 *
 * Returns:
 *   Whether the inventory holds the role that serves the provider's root module.
 */
function providerEnabled(provider) {
  return provider === "incus"
    ? strictFlag(process.env.PROVISION_INCUS_ENABLED, "PROVISION_INCUS_ENABLED")
    : strictFlag(process.env.PROVISION_PROXMOX_ENABLED, "PROVISION_PROXMOX_ENABLED");
}

/**
 * Args:
 *   provider: incus or proxmox.
 */
function requireProvider(provider) {
  test.skip(
    !providerEnabled(provider),
    `PROVISION_${provider.toUpperCase()}_ENABLED=false: the inventory holds no ${PROVIDER_ROLES[provider]}, so the ${provider} root module has no target`,
  );
}

/**
 * Returns:
 *   The provider whose root module has a target in this inventory, incus first.
 */
function anyProvider() {
  const provider = PROVIDERS.find(providerEnabled);
  test.skip(
    provider === undefined,
    "PROVISION_INCUS_ENABLED=false and PROVISION_PROXMOX_ENABLED=false: the inventory holds neither svc-virt-incus nor web-app-proxmox, so no root module has a target",
  );
  return provider;
}

function dnsFlavor() {
  return requireDotenvValue(process.env.PROVISION_DNS_FLAVOR, "PROVISION_DNS_FLAVOR");
}

function requireDnsLive() {
  test.skip(
    !strictFlag(process.env.PROVISION_DNS_LIVE, "PROVISION_DNS_LIVE"),
    requireDotenvValue(process.env.PROVISION_DNS_LIVE_MESSAGE, "PROVISION_DNS_LIVE_MESSAGE"),
  );
}

/**
 * Returns:
 *   The domain the zone specs create and delete in the Cloudflare account of the zone token.
 */
function requireZoneLive() {
  test.skip(
    !strictFlag(process.env.PROVISION_ZONE_LIVE, "PROVISION_ZONE_LIVE"),
    "PROVISION_ZONE_LIVE=false: secrets.credentials.cloudflare_zones_token, cloudflare_zones_account_id or services.semaphore.workspaces.dns.zone_probe is empty",
  );
  return requireDotenvValue(process.env.PROVISION_ZONE_PROBE, "PROVISION_ZONE_PROBE");
}

/**
 * Args:
 *   action: create, show, delete or unlock.
 *   order: an order line of `orderLine`.
 *   domain: the zone apex, taken by create and show only.
 *
 * Returns:
 *   The survey of zone.
 */
function zoneSurvey(action, order, domain) {
  const survey = { ZONE_ACTION: action, ...orderSurvey(order) };
  return ["create", "show"].includes(action) ? { ...survey, DOMAIN: domain } : survey;
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   action: create, show, delete or unlock.
 *   order: an order line of `orderLine`.
 *   domain: the zone apex.
 *
 * Returns:
 *   The finished zone run.
 */
function zoneTask(shared, fixture, action, order, domain) {
  return runPlatform(shared, fixture, "zone", zoneSurvey(action, order, domain), ZONE_MS, `zone ${action} of ${order.name} in ws-${fixture.workspace}`);
}

/**
 * Args:
 *   run: a zone run of `zoneTask`.
 *
 * Returns:
 *   The JSON object of the run's last output line.
 */
function zoneLine(run) {
  const line = run.lines
    .map(bare)
    .reverse()
    .find((candidate) => candidate.startsWith("{"));
  expect(line, `${run.what}: task ${run.task.id} must end with a JSON line; output tail:\n${workspaces.outputTail(run.lines)}`).toBeTruthy();
  return JSON.parse(line);
}

/**
 * Args:
 *   run: a create or show run of `zoneTask`.
 *   domain: the zone apex.
 *
 * Returns:
 *   The zone line, checked to hold exactly zone, zone_id, status and name_servers.
 */
function zoneOutputs(run, domain) {
  const outputs = zoneLine(run);
  expect(Object.keys(outputs).sort(), `${run.what}: the zone line must hold exactly ${ZONE_KEYS.join(", ")}`).toEqual(ZONE_KEYS);
  expect(outputs.zone, `${run.what}: the zone line must name ${domain}`).toBe(domain);
  expect(typeof outputs.zone_id === "string" && outputs.zone_id !== "", `${run.what}: zone_id must name the zone`).toBe(true);
  expect(typeof outputs.status === "string" && outputs.status !== "", `${run.what}: status must carry the provider's zone status`).toBe(true);
  expect(
    Array.isArray(outputs.name_servers) && outputs.name_servers.length > 0,
    `${run.what}: name_servers must list the assigned name servers, it is ${JSON.stringify(outputs.name_servers)}`,
  ).toBe(true);
  return outputs;
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   order: an order line of `orderLine`.
 *   domain: the zone apex.
 */
async function deleteZone(shared, fixture, order, domain) {
  const run = await zoneTask(shared, fixture, "delete", order, domain);
  workspaces.expectSucceeded(run, run.what);
}

function pinnedOpentofu() {
  return requireDotenvValue(process.env.PROVISION_OPENTOFU_VERSION, "PROVISION_OPENTOFU_VERSION");
}

/**
 * Args:
 *   provider: incus, proxmox or scs.
 *   keys: the region keys an offer must name, `["host"]` for incus and
 *     proxmox, `SCS_REGION_KEYS` for scs.
 *
 * Returns:
 *   Every catalog region of the provider that names each of the keys, as
 *   `provider`, `flavor`, `region`, its catalog entry `place` and the first
 *   `size` of the flavor.
 */
function catalogOffers(provider, keys) {
  const catalog = JSON.parse(requireDotenvValue(process.env.PROVISION_CATALOGS_JSON, "PROVISION_CATALOGS_JSON"))[provider] || {};
  return Object.entries(catalog).flatMap(([flavor, entry]) =>
    Object.entries(entry.regions || {})
      .filter(([, place]) => keys.every((key) => Boolean(place[key])))
      .map(([region, place]) => ({ provider, flavor, region, place, size: Object.keys(entry.sizes || {})[0] })),
  );
}

/**
 * Args:
 *   context: a browser context.
 *   mount: the KV v2 mount.
 *   path: the secret path below the mount.
 *
 * Returns:
 *   The data of the newest version, read with the Playwright AppRole whose
 *   token is revoked afterwards; a missing secret fails the test.
 */
async function vaultRecord(context, mount, path) {
  const login = await workspaces.http(context, "POST", `${openbaoOrigin()}/v1/auth/approle/login`, {
    data: {
      role_id: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_ROLE_ID, "OPENBAO_PLAYWRIGHT_ROLE_ID"),
      secret_id: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SECRET_ID, "OPENBAO_PLAYWRIGHT_SECRET_ID"),
    },
  });
  await workspaces.expectStatus(login, [200], `${LABEL}: the OpenBao login of the Playwright AppRole`);
  return readWithToken(context, (await login.json()).auth.client_token, mount, path);
}

function openbaoOrigin() {
  return new URL(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL")).origin;
}

/**
 * Args:
 *   context: a browser context.
 *   token: an OpenBao token the spec owns, revoked after the read.
 *   mount: the KV v2 mount.
 *   path: the secret path below the mount.
 *
 * Returns:
 *   The data of the newest version; a missing secret fails the test.
 */
async function readWithToken(context, token, mount, path) {
  try {
    const data = await workspaces.vaultRead(context, token, mount, path);
    expect(data, `${LABEL}: OpenBao must hold ${mount}/${path}`).not.toBeNull();
    return data;
  } finally {
    const revoke = await workspaces.http(context, "POST", `${openbaoOrigin()}/v1/auth/token/revoke-self`, {
      headers: { "X-Vault-Token": token },
    });
    await workspaces.expectStatus(revoke, [204], `${LABEL}: the revocation of the spec's OpenBao token`);
  }
}

/**
 * Args:
 *   context: a browser context.
 *
 * Returns:
 *   The store's Semaphore API token, read with the store's own AppRole.
 */
async function storeSemaphoreToken(context) {
  const record = await readWithToken(context, await workspaces.storeVaultToken(context), PLATFORM_MOUNT, STORE_SEMAPHORE_PATH);
  expect(Boolean(record.token), `${LABEL}: ${PLATFORM_MOUNT}/${STORE_SEMAPHORE_PATH} must hold the store's Semaphore token`).toBe(true);
  return record.token;
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   context: a browser context.
 *   token: the store's Semaphore API token.
 *   method: the HTTP method.
 *   path: the path below `/api`.
 *   data: the JSON body, undefined for none.
 *
 * Returns:
 *   The response of the Semaphore API to the store, whatever its status.
 */
function asStore(shared, context, token, method, path, data) {
  return workspaces.http(context, method, `${shared.env.semaphoreBaseUrl}/api${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
}

/**
 * Args:
 *   context: a browser context.
 *   provider: incus or proxmox.
 *
 * Returns:
 *   The catalog offer a provision of the provider runs on; for proxmox the
 *   region whose kvm mode the target's platform record names, with that
 *   `record`.
 */
async function placement(context, provider) {
  const offers = catalogOffers(provider, ["host"]);
  expect(offers.length, `${LABEL}: services.semaphore.workspaces.catalog.${provider} must offer a region that names a host`).toBeGreaterThan(0);
  if (provider !== "proxmox") {
    return offers[0];
  }
  const host = offers[0].place.host;
  const record = await vaultRecord(context, PLATFORM_MOUNT, `provision/proxmox-${host}`);
  const offer = offers.find((candidate) => candidate.place.host === host && truthy(candidate.place.kvm) === truthy(record.kvm));
  expect(
    offer,
    `${LABEL}: the proxmox catalog must offer a region on ${host} with kvm ${truthy(record.kvm)}, the mode ${PLATFORM_MOUNT}/provision/proxmox-${host} records`,
  ).toBeTruthy();
  return { ...offer, record };
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *   name: the template name.
 *
 * Returns:
 *   The identity apply returned for the template.
 */
function templateOf(fixture, name) {
  const identity = fixture.result.templates[name];
  expect(identity, `${LABEL}: workspace apply must return the template "${name}" of ws-${fixture.workspace}`).toBeTruthy();
  return identity;
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *   kind: unlock, dns, zone, or `<action>-<provider>` for the provision and
 *     destroy template of one provider.
 *
 * Returns:
 *   The identity of the workspace's template of that kind in the provision
 *   project. Every template there runs with the same environment and runner.
 */
function platformTemplate(fixture, kind) {
  return templateOf(fixture, `${kind} ws-${fixture.workspace}`);
}

/**
 * Args:
 *   action: provision or destroy.
 *   order: an order line `commitValues` committed, which names its provider.
 *
 * Returns:
 *   The kind of the template of that action that pins the line's provider.
 */
function orderKind(action, order) {
  expect(order.provider, `${LABEL}: ${order.name} must name the provider its values were committed for`).toBeTruthy();
  return `${action}-${order.provider}`;
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *   action: provision or destroy.
 *   order: an order line `commitValues` committed.
 *
 * Returns:
 *   The identity of the template of `orderKind`.
 */
function orderTemplate(fixture, action, order) {
  return platformTemplate(fixture, orderKind(action, order));
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   kind: a kind of `platformTemplate`.
 *   survey: the survey answers.
 *   runMs: the longest the task may run, before timeout scaling.
 *   what: the run the failure messages name.
 *
 * Returns:
 *   The finished task, its output lines and `what`.
 */
async function runPlatform(shared, fixture, kind, survey, runMs, what) {
  const identity = platformTemplate(fixture, kind);
  return { ...(await workspaces.runTemplate(shared, fixture.page, identity.project_id, identity.template_id, survey, runMs, what)), what };
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *
 * Returns:
 *   `zone` and `zoneId` of the environment workspace apply wrote for the provision templates.
 */
async function workspaceDns(shared, fixture) {
  const identity = platformTemplate(fixture, "unlock");
  const environment = await shared.api(fixture.page, "GET", `/project/${identity.project_id}/environment/${identity.environment_id}`);
  const variables = JSON.parse(environment.env || "{}");
  expect(variables.WORKSPACE, `${LABEL}: the provision environment must name the workspace ws-${fixture.workspace}`).toBe(
    `ws-${fixture.workspace}`,
  );
  expect(Boolean(variables.WORKSPACE_DNS_ZONE), `${LABEL}: the provision environment of ws-${fixture.workspace} must name WORKSPACE_DNS_ZONE`).toBe(
    true,
  );
  return { zone: variables.WORKSPACE_DNS_ZONE, zoneId: variables.WORKSPACE_DNS_ZONE_ID || "" };
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *   order: an order line of `orderLine`.
 *   offer: the catalog offer of `placement`.
 *
 * Returns:
 *   The commit that carries `provision/<SALES_ORDER>-<LINE>.tfvars.json`.
 *   The order takes the offer's `provider`, the one its provision and
 *   destroy templates pin.
 */
function commitValues(fixture, order, offer) {
  order.provider = offer.provider;
  return workspaces.commitWorkspaceFile(
    fixture,
    `provision/${order.name}.tfvars.json`,
    JSON.stringify({
      name: order.name,
      flavor: offer.flavor,
      size: offer.size,
      region: offer.region,
      ssh_public_key: sshEd25519PublicLine(),
      dns_label: order.label,
    }),
    LABEL,
  );
}

/**
 * Args:
 *   run: a provision run of `runPlatform`.
 *
 * Returns:
 *   The four outputs the run printed as its JSON line.
 */
function outputsOf(run) {
  const line = run.lines
    .map(bare)
    .reverse()
    .find((candidate) => candidate.startsWith("{") && candidate.includes('"fqdn"'));
  expect(line, `${run.what}: task ${run.task.id} must print the outputs of the root as a JSON line; output tail:\n${workspaces.outputTail(run.lines)}`).toBeTruthy();
  const outputs = JSON.parse(line);
  expect(Object.keys(outputs).sort(), `${run.what}: the outputs must be exactly fqdn, host, host_key and server_id`).toEqual(OUTPUT_KEYS);
  expect(
    Array.isArray(outputs.host) && outputs.host.length > 0 && outputs.host.every((address) => net.isIP(address) !== 0),
    `${run.what}: host must list the addresses of the server, it is ${JSON.stringify(outputs.host)}`,
  ).toBe(true);
  expect(typeof outputs.server_id === "string" && outputs.server_id !== "", `${run.what}: server_id must name the server`).toBe(true);
  expect(typeof outputs.host_key === "string", `${run.what}: host_key must be a text`).toBe(true);
  return outputs;
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   order: an order line whose tfvars the workspace repository holds.
 *
 * Returns:
 *   The outputs of a successful provision.
 */
async function provision(shared, fixture, order) {
  return provisionWith(shared, fixture, order, providerSurvey(order));
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   order: an order line whose tfvars the workspace repository holds.
 *   survey: `providerSurvey` or `customerSurvey` of the order.
 *
 * Returns:
 *   The outputs of a successful provision.
 */
async function provisionWith(shared, fixture, order, survey) {
  const run = await runPlatform(shared, fixture, orderKind("provision", order), survey, PROVISION_MS, `provision of ${order.name} in ws-${fixture.workspace}`);
  workspaces.expectSucceeded(run, run.what);
  return outputsOf(run);
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   order: an order line whose tfvars the workspace repository holds.
 *
 * Returns:
 *   The successful destroy run.
 */
async function destroy(shared, fixture, order) {
  return destroyWith(shared, fixture, order, providerSurvey(order));
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   order: an order line whose tfvars the workspace repository holds.
 *   survey: `providerSurvey` or `customerSurvey` of the order.
 *
 * Returns:
 *   The successful destroy run.
 */
async function destroyWith(shared, fixture, order, survey) {
  const run = await runPlatform(shared, fixture, orderKind("destroy", order), survey, DESTROY_MS, `destroy of ${order.name} in ws-${fixture.workspace}`);
  workspaces.expectSucceeded(run, run.what);
  return run;
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   action: create, remove or unlock.
 *   order: an order line of `orderLine`.
 *   host: the address the record points at.
 *
 * Returns:
 *   The finished dns run.
 */
function dnsTask(shared, fixture, action, order, host) {
  return runPlatform(shared, fixture, "dns", dnsSurvey(action, order, host), DNS_MS, `dns ${action} of ${order.name} in ws-${fixture.workspace}`);
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   order: an order line of `orderLine`.
 *   host: the address the record points at.
 */
async function removeRecord(shared, fixture, order, host) {
  const run = await dnsTask(shared, fixture, "remove", order, host);
  workspaces.expectSucceeded(run, run.what);
}

/**
 * Args:
 *   context: a browser context.
 *   keys: `access_key` and `secret_key` of the state bucket.
 *   method: HEAD, PUT or DELETE.
 *   path: `/<bucket>/<key>`.
 *   body: the object body of a PUT.
 *
 * Returns:
 *   The response, whatever its status.
 */
function stateRequest(context, keys, method, path, body) {
  const endpoint = new URL(requireDotenvValue(process.env.PROVISION_STATE_ENDPOINT, "PROVISION_STATE_ENDPOINT"));
  const headers = sign({
    method,
    host: endpoint.host,
    path,
    region: STATE_REGION,
    accessKey: keys.access_key,
    secretKey: keys.secret_key,
    payload: body,
  });
  return workspaces.http(context, method, `${endpoint.origin}${path}`, { headers, data: body === "" ? undefined : body });
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *
 * Returns:
 *   `bucket` and `exists`, `get`, `put` and `remove` on the workspace's
 *   state bucket with the workspace's own keys.
 */
async function stateBucket(fixture) {
  const keys = await vaultRecord(fixture.context, TENANT_MOUNT, `ws-${fixture.workspace}-provision/s3`);
  const bucket = `ws-${fixture.workspace}-state`;
  return {
    bucket,
    async exists(key) {
      const response = await stateRequest(fixture.context, keys, "HEAD", `/${bucket}/${key}`, "");
      await workspaces.expectStatus(response, [200, 404], `${LABEL}: the HEAD of ${bucket}/${key}`);
      return response.status() === 200;
    },
    async get(key) {
      const response = await stateRequest(fixture.context, keys, "GET", `/${bucket}/${key}`, "");
      await workspaces.expectStatus(response, [200], `${LABEL}: the GET of ${bucket}/${key}`);
      return response.text();
    },
    async put(key, body) {
      const response = await stateRequest(fixture.context, keys, "PUT", `/${bucket}/${key}`, body);
      await workspaces.expectStatus(response, [200], `${LABEL}: the PUT of ${bucket}/${key}`);
    },
    async remove(key) {
      const response = await stateRequest(fixture.context, keys, "DELETE", `/${bucket}/${key}`, "");
      await workspaces.expectStatus(response, [204, 404], `${LABEL}: the DELETE of ${bucket}/${key}`);
    },
  };
}

/**
 * Args:
 *   state: a result of `stateBucket`.
 *   key: the state key the lock guards.
 *
 * Returns:
 *   The key of the planted lock file, whose LockInfo no running task holds.
 */
async function plantLock(state, key) {
  const lock = `${key}.tflock`;
  await state.put(
    lock,
    JSON.stringify({
      ID: crypto.randomUUID(),
      Operation: "OperationTypeApply",
      Info: "",
      Who: `playwright@${LABEL}`,
      Version: pinnedOpentofu(),
      Created: new Date().toISOString(),
      Path: `${state.bucket}/${key}`,
    }),
  );
  return lock;
}

/**
 * Args:
 *   host: a host name or address.
 *   port: the DNS port.
 *
 * Returns:
 *   The server in the form `dns.Resolver.setServers` takes.
 */
async function serverAddress(host, port) {
  const { address, family } = await dns.promises.lookup(host);
  return family === 6 ? `[${address}]:${port}` : `${address}:${port}`;
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *   zone: the deploy zone.
 *
 * Returns:
 *   The authoritative servers of the zone: the update server under knot,
 *   the zone's name servers otherwise.
 */
async function recordServers(fixture, zone) {
  if (dnsFlavor() === "knot") {
    const record = await vaultRecord(fixture.context, TENANT_MOUNT, `ws-${fixture.workspace}-provision/dns`);
    return [await serverAddress(record.server, Number(record.port))];
  }
  const names = await new dns.promises.Resolver({ timeout: resolveTimeout(DNS_QUERY_MS), tries: DNS_TRIES }).resolveNs(zone);
  expect(names.length, `${LABEL}: the zone ${zone} must name its name servers`).toBeGreaterThan(0);
  return Promise.all(names.map((name) => serverAddress(name, DNS_PORT)));
}

/**
 * Args:
 *   servers: the servers of `recordServers`.
 *   fqdn: the name to resolve.
 *
 * Returns:
 *   The sorted A and AAAA addresses the servers answer, empty for a name that holds none.
 */
async function addressesOf(servers, fqdn) {
  const resolver = new dns.promises.Resolver({ timeout: resolveTimeout(DNS_QUERY_MS), tries: DNS_TRIES });
  resolver.setServers(servers);
  const found = [];
  for (const query of ["resolve4", "resolve6"]) {
    try {
      found.push(...(await resolver[query](fqdn)));
    } catch (error) {
      if (![dns.NODATA, dns.NOTFOUND].includes(error.code)) {
        throw new Error(`${LABEL}: ${query} of ${fqdn} at ${servers.join(", ")} failed with ${error.code}`, { cause: error });
      }
    }
  }
  return found.sort();
}

/**
 * Args:
 *   servers: the servers of `recordServers`.
 *   fqdn: the record name.
 *   addresses: the addresses the name has to resolve to, empty for none.
 *   what: the step the failure message names.
 */
async function expectRecord(servers, fqdn, addresses, what) {
  await expect
    .poll(() => addressesOf(servers, fqdn), {
      timeout: resolveTimeout(RECORD_MS),
      intervals: [POLL_MS],
      message: `${what}: ${fqdn} must resolve to ${addresses.join(", ") || "no address"} at ${servers.join(", ")}`,
    })
    .toEqual([...addresses].sort());
}

/**
 * Args:
 *   host: the address of the server.
 *
 * Returns:
 *   The first line the SSH port sends, or the error code of the attempt.
 */
function sshBanner(host) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port: SSH_PORT });
    socket.setTimeout(resolveTimeout(SSH_PROBE_MS));
    socket.once("data", (data) => {
      socket.destroy();
      resolve(data.toString("utf8").split("\r\n")[0]);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve("ETIMEDOUT");
    });
    socket.once("error", (error) => resolve(error.code));
  });
}

/**
 * Args:
 *   host: the address of the server.
 *   what: the server the failure message names.
 */
async function expectSsh(host, what) {
  await expect
    .poll(async () => (await sshBanner(host)).startsWith("SSH-2.0-"), {
      timeout: resolveTimeout(BOOT_MS),
      intervals: [POLL_MS],
      message: `${what}: ${host}:${SSH_PORT} must boot and answer with an SSH banner`,
    })
    .toBe(true);
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *   offer: the incus offer of `placement`.
 *
 * Returns:
 *   `expectRunning(outputs, order)` and `expectGone(order)` on the Incus
 *   project of the workspace, read with the workspace's client certificate
 *   against the pinned server certificate.
 */
async function incusTarget(fixture, offer) {
  const server = await vaultRecord(fixture.context, PLATFORM_MOUNT, `provision/incus-${offer.place.host}`);
  const client = await vaultRecord(fixture.context, TENANT_MOUNT, `ws-${fixture.workspace}-provision/incus`);
  const base = new URL(server.endpoint);
  const project = `ws-${fixture.workspace}`;
  const get = (path) =>
    new Promise((resolve, reject) => {
      const request = https.request(
        new URL(path, base),
        {
          method: "GET",
          ca: server.certificate,
          cert: client.certificate,
          key: client.key,
          checkServerIdentity: (_host, peer) =>
            peer.fingerprint256.replace(/:/g, "").toLowerCase() === String(server.fingerprint).toLowerCase()
              ? undefined
              : new Error(`the Incus API at ${base.host} presented a certificate other than the pinned one`),
          timeout: resolveTimeout(REQUEST_MS),
        },
        (response) => {
          let text = "";
          response.setEncoding("utf8");
          response.on("data", (chunk) => {
            text += chunk;
          });
          response.on("end", () => {
            try {
              resolve({ status: response.statusCode, json: text ? JSON.parse(text) : null });
            } catch (error) {
              reject(error);
            }
          });
        },
      );
      request.on("timeout", () => request.destroy(new Error(`GET ${path} on the Incus API got no answer`)));
      request.on("error", reject);
      request.end();
    });
  const named = async (name) => {
    const listed = await get(`/1.0/instances?project=${project}&recursion=1`);
    expect(listed.status, `${LABEL}: the workspace certificate must list the instances of the Incus project ${project}`).toBe(200);
    return listed.json.metadata.filter((instance) => instance.name === name);
  };
  return {
    async expectRunning(outputs, order) {
      expect(outputs.server_id, `${LABEL}: the incus root must return the instance name as server_id`).toBe(order.name);
      expect(
        HOST_KEY_LINE.test(outputs.host_key),
        `${LABEL}: the incus root must return the ed25519 host key cloud-init installs, it returned ${JSON.stringify(outputs.host_key)}`,
      ).toBe(true);
      expect(
        (await named(order.name)).map((instance) => [instance.type, instance.status]),
        `${LABEL}: exactly one running virtual machine ${order.name} must exist in the Incus project ${project}`,
      ).toEqual([["virtual-machine", "Running"]]);
    },
    async expectGone(order) {
      expect(await named(order.name), `${LABEL}: the destroy must leave no instance ${order.name} in the Incus project ${project}`).toEqual([]);
    },
  };
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *   offer: the proxmox offer of `placement`, carrying the platform `record`.
 *
 * Returns:
 *   `expectRunning(outputs, order)` and `expectGone(order)` on the pool of
 *   the workspace, read with the workspace's own API token.
 */
async function proxmoxTarget(fixture, offer) {
  const token = await vaultRecord(fixture.context, TENANT_MOUNT, `ws-${fixture.workspace}-provision/proxmox`);
  const origin = new URL(offer.record.endpoint).origin;
  const headers = { Authorization: `PVEAPIToken=${token.token_id}=${token.secret}` };
  const pool = `ws-${fixture.workspace}`;
  const get = async (path) => {
    const response = await workspaces.http(fixture.context, "GET", `${origin}/api2/json${path}`, { headers });
    await workspaces.expectStatus(response, [200], `${LABEL}: GET /api2/json${path} with the token of ${pool}`);
    return (await response.json()).data;
  };
  const named = async (name) => (await get("/cluster/resources?type=vm")).filter((vm) => vm.name === name);
  const kvm = truthy(offer.place.kvm);
  return {
    async expectRunning(outputs, order) {
      expect(outputs.host_key, `${LABEL}: the proxmox root sets no host key, so host_key must be empty`).toBe("");
      const vms = await named(order.name);
      expect(
        vms.map((vm) => [String(vm.vmid), vm.pool, vm.status]),
        `${LABEL}: exactly one running VM ${order.name} with the id ${outputs.server_id} must exist in the pool ${pool}`,
      ).toEqual([[outputs.server_id, pool, "running"]]);
      const config = await get(`/nodes/${vms[0].node}/qemu/${vms[0].vmid}/config`);
      expect(String(config.net0), `${LABEL}: VM ${vms[0].vmid} must sit on the bridge ${offer.place.bridge}`).toContain(
        `bridge=${offer.place.bridge}`,
      );
      expect(
        String(config.scsi0).startsWith(`${offer.place.storage}:`),
        `${LABEL}: the disk scsi0 of VM ${vms[0].vmid} must lie on ${offer.place.storage}, it is ${config.scsi0}`,
      ).toBe(true);
      expect(
        config.kvm === undefined ? 1 : Number(config.kvm),
        `${LABEL}: VM ${vms[0].vmid} of the region ${offer.region} must run with kvm ${kvm ? 1 : 0}`,
      ).toBe(kvm ? 1 : 0);
    },
    async expectGone(order) {
      expect(await named(order.name), `${LABEL}: the destroy must leave no VM ${order.name} in the pool ${pool}`).toEqual([]);
    },
  };
}

/**
 * Args:
 *   fixture: the result of `workspaces.openWorkspace`.
 *   provider: incus or proxmox.
 *   offer: the offer of `placement`.
 *
 * Returns:
 *   The checks on the provider's own API.
 */
function serverTarget(fixture, provider, offer) {
  return provider === "proxmox" ? proxmoxTarget(fixture, offer) : incusTarget(fixture, offer);
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   page: a page carrying the administrator session.
 *   projectId: the project of the task.
 *   taskId: the task.
 *   pattern: the line the task has to print while it runs.
 *   runMs: the longest the wait may take, before timeout scaling.
 *   what: the task the failure message names.
 *
 * Returns:
 *   The first output line matching the pattern.
 */
async function awaitLine(shared, page, projectId, taskId, pattern, runMs, what) {
  let found;
  let task;
  let lines = [];
  await expect
    .poll(
      async () => {
        task = await shared.api(page, "GET", `/project/${projectId}/tasks/${taskId}`);
        lines = (await shared.api(page, "GET", `/project/${projectId}/tasks/${taskId}/output`)).map((line) => line.output);
        found = lines.map(bare).find((line) => pattern.test(line));
        if (found !== undefined) {
          return "printed";
        }
        return TASK_FINISHED.has(task.status) ? "finished" : "pending";
      },
      { timeout: resolveTimeout(runMs), intervals: [POLL_MS], message: `${what}: task ${taskId} must print a line matching ${pattern}` },
    )
    .not.toBe("pending");
  expect(found, `${what}: task ${taskId} ended ${task.status} without a line matching ${pattern}; output tail:\n${workspaces.outputTail(lines)}`).toBeTruthy();
  return found;
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   browser: the Playwright browser.
 *   provider: incus or proxmox.
 *
 * Returns:
 *   The state objects of the order line the destroy left in the bucket.
 */
async function serverLifecycle(shared, browser, provider) {
  return workspaces.withWorkspace(shared, browser, LABEL, `${privateTargetAddress()}:${SSH_PORT}`, async (fixture, cleanup) => {
    const offer = await placement(fixture.context, provider);
    const order = orderLine(freshSalesOrder(), "1");
    await commitValues(fixture, order, offer);
    cleanup(() => destroy(shared, fixture, order));
    expect(
      orderTemplate(fixture, "provision", order).environment_variables.filter((name) => INSECURE.test(name)),
      `${LABEL}: the provision template of ws-${fixture.workspace} must carry no variable that turns certificate checks off`,
    ).toEqual([]);
    const target = await serverTarget(fixture, provider, offer);
    const { zone } = await workspaceDns(shared, fixture);
    const servers = await recordServers(fixture, zone);
    const outputs = await provision(shared, fixture, order);
    await target.expectRunning(outputs, order);
    await expectSsh(outputs.host[0], `${LABEL}: ${provider} server ${order.name}`);
    await expectRecord(servers, outputs.fqdn, outputs.host, `${LABEL}: the record of ${order.name} after the provision`);
    const destroyed = await destroy(shared, fixture, order);
    expect(destroyedCount(destroyed), `${destroyed.what}: the destroy must remove the server and its record`).toBeGreaterThan(0);
    await target.expectGone(order);
    await expectRecord(servers, outputs.fqdn, [], `${LABEL}: the record of ${order.name} after the destroy`);
    const state = await stateBucket(fixture);
    const left = [];
    for (const key of [`${order.salesOrder}/${order.line}.tfstate`, `${order.salesOrder}/${order.line}.tfstate.tflock`, `${order.salesOrder}/${order.line}.provision.json`]) {
      if (await state.exists(key)) {
        left.push(`${state.bucket}/${key}`);
      }
    }
    return left;
  });
}

/**
 * Args:
 *   keys: `access_key` and `secret_key` of a Route 53 identity.
 *   path: the request path.
 *   body: the request body.
 *
 * Returns:
 *   The SigV4 headers of a Route 53 POST.
 */
function route53Headers(keys, path, body) {
  const amzDate = `${new Date().toISOString().replace(/[-:]|\.\d{3}/g, "").slice(0, 15)}Z`;
  const day = amzDate.slice(0, 8);
  const host = new URL(ROUTE53_ORIGIN).host;
  const digest = (text) => crypto.createHash("sha256").update(text, "utf8").digest("hex");
  const canonical = [
    "POST",
    path,
    "",
    `content-type:${ROUTE53_CONTENT_TYPE}\nhost:${host}\nx-amz-date:${amzDate}\n`,
    ROUTE53_SIGNED_HEADERS,
    digest(body),
  ].join("\n");
  const scope = `${day}/${ROUTE53_REGION}/${ROUTE53_SERVICE}/aws4_request`;
  const hmac = (key, text) => crypto.createHmac("sha256", key).update(text, "utf8").digest();
  const signingKey = [day, ROUTE53_REGION, ROUTE53_SERVICE, "aws4_request"].reduce(hmac, `AWS4${keys.secret_key}`);
  const signature = crypto
    .createHmac("sha256", signingKey)
    .update(["AWS4-HMAC-SHA256", amzDate, scope, digest(canonical)].join("\n"), "utf8")
    .digest("hex");
  return {
    "Content-Type": ROUTE53_CONTENT_TYPE,
    "X-Amz-Date": amzDate,
    Authorization: `AWS4-HMAC-SHA256 Credential=${keys.access_key}/${scope}, SignedHeaders=${ROUTE53_SIGNED_HEADERS}, Signature=${signature}`,
  };
}

/**
 * Args:
 *   context: a browser context.
 *   keys: `access_key` and `secret_key` of a Route 53 identity.
 *   zoneId: the hosted zone.
 *   action: CREATE or DELETE.
 *   name: the record name.
 *   host: the IPv4 address of the record.
 *
 * Returns:
 *   The response of ChangeResourceRecordSets, whatever its status.
 */
function changeRecord(context, keys, zoneId, action, name, host) {
  const path = `/${ROUTE53_VERSION}/hostedzone/${zoneId}/rrset/`;
  const body =
    `<?xml version="1.0" encoding="UTF-8"?><ChangeResourceRecordSetsRequest xmlns="${ROUTE53_NAMESPACE}"><ChangeBatch><Changes><Change>` +
    `<Action>${action}</Action><ResourceRecordSet><Name>${name}</Name><Type>A</Type><TTL>60</TTL>` +
    `<ResourceRecords><ResourceRecord><Value>${host}</Value></ResourceRecord></ResourceRecords></ResourceRecordSet>` +
    "</Change></Changes></ChangeBatch></ChangeResourceRecordSetsRequest>";
  return workspaces.http(context, "POST", `${ROUTE53_ORIGIN}${path}`, { headers: route53Headers(keys, path, body), data: body });
}

/**
 * Args:
 *   text: a state object as the bucket holds it.
 *   plaintexts: values the plaintext state of the run holds.
 *   what: the object the failure messages name.
 */
function expectEncryptedState(text, plaintexts, what) {
  let state;
  try {
    state = JSON.parse(text);
  } catch (error) {
    throw new Error(`${what}: the state object must be OpenTofu's JSON envelope`, { cause: error });
  }
  expect(ENVELOPE_KEYS.filter((key) => !(key in state)), `${what}: the state object must be OpenTofu's encrypted envelope`).toEqual([]);
  expect(PLAINTEXT_KEYS.filter((key) => key in state), `${what}: the state object must hold no plaintext state`).toEqual([]);
  expect(plaintexts.filter((value) => text.includes(value)), `${what}: the state object must not carry a value of the run in clear`).toEqual([]);
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   paths: the OpenBao API paths the probe reads.
 *
 * Returns:
 *   `names`, the environment names a probe task in the workspace project
 *   sees, and `statuses`, the HTTP status OpenBao answered it per path,
 *   after its own tenant path answered 404.
 */
async function workspaceProbe(shared, fixture, paths) {
  const control = OWN_TENANT_PATH(fixture.workspace);
  const what = `${LABEL}: isolation probe in ws-${fixture.workspace}`;
  const run = await workspaces.runProbe(
    shared,
    fixture,
    fixture.result.project_id,
    ISOLATION_PROBE_SCRIPT,
    [...(await openbaoReach(shared, fixture)), `ws-${fixture.workspace}`, control, ...paths],
    what,
  );
  workspaces.expectSucceeded(run, what);
  const { [control]: own, ...statuses } = Object.fromEntries(probeLines(run, "status").map((line) => line.split(" ")));
  expect(own, `${what}: the token of ws-${fixture.workspace} must reach its own tenant path ${control}`).toBe("404");
  expect(Object.keys(statuses).sort(), `${what}: the probe must report one OpenBao status per path`).toEqual([...paths].sort());
  return { names: probeLines(run, "env"), statuses, what };
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *
 * Returns:
 *   `[origin, cafile]` of OpenBao as the provision environment names them,
 *   the first two arguments of the probe scripts.
 */
async function openbaoReach(shared, fixture) {
  const identity = platformTemplate(fixture, "unlock");
  const environment = await shared.api(fixture.page, "GET", `/project/${identity.project_id}/environment/${identity.environment_id}`);
  const variables = JSON.parse(environment.env || "{}");
  return [variables.BAO_ADDR || openbaoOrigin(), variables.PROVISION_CA_FILE || NO_CA_FILE];
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   kind: the `platformTemplate` kind whose task token the probe carries.
 *   script: the probe script.
 *   args: its arguments.
 *   what: the run the failure messages name.
 *
 * Returns:
 *   The finished task. The template runs the probe script of its project
 *   for this one task, so the task token names that template, and gets its
 *   own run definition back afterwards.
 */
async function asTemplate(shared, fixture, kind, script, args, what) {
  const identity = platformTemplate(fixture, kind);
  const project = identity.project_id;
  const original = await shared.api(fixture.page, "GET", `/project/${project}/templates/${identity.template_id}`);
  const probe = await workspaces.namedTemplate(shared, fixture.page, project, `probe ${fixture.result.alias}`);
  await shared.api(fixture.page, "PUT", `/project/${project}/templates/${original.id}`, {
    ...original,
    ...Object.fromEntries(PROBE_RUN_FIELDS.map((field) => [field, probe[field]])),
  });
  try {
    return await workspaces.runTemplate(shared, fixture.page, project, original.id, { PROBE_SCRIPT: script, PROBE_ARGS: args.join(" ") }, PROBE_MS, what);
  } finally {
    await shared.api(fixture.page, "PUT", `/project/${project}/templates/${original.id}`, original);
  }
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   provider: the provider whose provision template carries the task token.
 *   paths: the OpenBao API paths the probe reads.
 *
 * Returns:
 *   `statuses`, the HTTP status OpenBao answered a task of the provider's
 *   provision template, logged in with that provider's role, per path,
 *   after the state keys of the workspace answered 200.
 */
async function provisionProbe(shared, fixture, provider, paths) {
  const control = `${TENANT_MOUNT}/data/ws-${fixture.workspace}-provision/s3`;
  const role = `ws-${fixture.workspace}-provision-${provider}`;
  const what = `${LABEL}: provision-${provider} task of ws-${fixture.workspace} logged in as ${role}`;
  const args = [...(await openbaoReach(shared, fixture)), role, control, ...paths];
  const run = await asTemplate(shared, fixture, `provision-${provider}`, ISOLATION_PROBE_SCRIPT, args, what);
  workspaces.expectSucceeded(run, what);
  const { [control]: own, ...statuses } = Object.fromEntries(probeLines(run, "status").map((line) => line.split(" ")));
  expect(own, `${what}: the token of ${role} must read the state keys ${control}`).toBe("200");
  expect(Object.keys(statuses).sort(), `${what}: the probe must report one OpenBao status per path`).toEqual([...paths].sort());
  return { statuses, what };
}

/**
 * Args:
 *   shared: the role's shared helpers.
 *   fixture: the result of `workspaces.openWorkspace`.
 *   kind: the `platformTemplate` kind whose task token the probe carries.
 *   roles: the task token roles of the jwt mount the probe logs in to.
 *
 * Returns:
 *   `logins`, the HTTP status OpenBao answered the task token per role.
 */
async function loginProbe(shared, fixture, kind, roles) {
  const what = `${LABEL}: ${kind} task of ws-${fixture.workspace} logging in to each provision role`;
  const run = await asTemplate(shared, fixture, kind, LOGIN_STATUS_SCRIPT, [...(await openbaoReach(shared, fixture)), ...roles], what);
  workspaces.expectSucceeded(run, what);
  const logins = Object.fromEntries(probeLines(run, "login").map((line) => line.split(" ")));
  expect(Object.keys(logins).sort(), `${what}: the probe must report one login status per role`).toEqual([...roles].sort());
  return { logins, what };
}

function u16(value) {
  const buffer = Buffer.alloc(2);
  buffer.writeUInt16BE(value);
  return buffer;
}

function u32(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32BE(value);
  return buffer;
}

function u48(value) {
  const buffer = Buffer.alloc(6);
  buffer.writeUIntBE(value, 0, 6);
  return buffer;
}

/**
 * Args:
 *   name: a domain name, with or without its final dot.
 *
 * Returns:
 *   The name in DNS wire format, lowercased as TSIG hashes it.
 */
function wireName(name) {
  const labels = name.toLowerCase().replace(/\.$/, "").split(".").filter(Boolean);
  return Buffer.concat([...labels.map((label) => Buffer.concat([Buffer.from([label.length]), Buffer.from(label, "ascii")])), Buffer.from([0])]);
}

function resourceRecord(name, type, klass, ttl, rdata) {
  return Buffer.concat([wireName(name), u16(type), u16(klass), u32(ttl), u16(rdata.length), rdata]);
}

function aRecord(address) {
  return Buffer.from(address.split(".").map(Number));
}

function txtRecord(text) {
  return Buffer.concat([Buffer.from([text.length]), Buffer.from(text, "ascii")]);
}

function mxRecord(exchange) {
  return Buffer.concat([u16(10), wireName(exchange)]);
}

/**
 * Args:
 *   key: the knot record of a workspace: `key_name`, `key_algorithm` and
 *     `key_secret`.
 *   zone: the zone the update names.
 *   changes: `{ name, type, rdata }` to add a record, `{ name, type, remove: true }`
 *     to delete the record set of that name and type.
 *
 * Returns:
 *   The RFC 2136 update, signed with the key as RFC 8945 TSIG.
 */
function signedUpdate(key, zone, changes) {
  const id = crypto.randomInt(0, 0x10000);
  const unsigned = Buffer.concat([
    u16(id),
    u16(DNS_UPDATE_OPCODE << 11),
    u16(1),
    u16(0),
    u16(changes.length),
    u16(0),
    wireName(zone),
    u16(DNS_TYPES.SOA),
    u16(DNS_CLASS_IN),
    ...changes.map((change) =>
      change.remove
        ? resourceRecord(change.name, DNS_TYPES[change.type], DNS_CLASS_ANY, 0, Buffer.alloc(0))
        : resourceRecord(change.name, DNS_TYPES[change.type], DNS_CLASS_IN, UPDATE_TTL, change.rdata),
    ),
  ]);
  const algorithm = key.key_algorithm.replace(/\.$/, "");
  const signedAt = Math.floor(Date.now() / 1000);
  const variables = Buffer.concat([
    wireName(key.key_name),
    u16(DNS_CLASS_ANY),
    u32(0),
    wireName(algorithm),
    u48(signedAt),
    u16(TSIG_FUDGE),
    u16(0),
    u16(0),
  ]);
  const mac = crypto
    .createHmac(algorithm.replace(/^hmac-/, ""), Buffer.from(key.key_secret, "base64"))
    .update(Buffer.concat([unsigned, variables]))
    .digest();
  const tsig = resourceRecord(
    key.key_name,
    DNS_TYPES.TSIG,
    DNS_CLASS_ANY,
    0,
    Buffer.concat([wireName(algorithm), u48(signedAt), u16(TSIG_FUDGE), u16(mac.length), mac, u16(id), u16(0), u16(0)]),
  );
  const message = Buffer.concat([unsigned, tsig]);
  message.writeUInt16BE(1, 10);
  return message;
}

/**
 * Args:
 *   key: the knot record of a workspace, also carrying `server` and `port`.
 *   zone: the zone the update names.
 *   changes: as for `signedUpdate`.
 *
 * Returns:
 *   The name of the RCODE the server answered the signed update with.
 */
async function knotUpdate(key, zone, changes) {
  const message = signedUpdate(key, zone, changes);
  const { address, family } = await dns.promises.lookup(key.server);
  const reply = await new Promise((resolve, reject) => {
    const socket = dgram.createSocket(family === 6 ? "udp6" : "udp4");
    let timer;
    const attempt = (left) => {
      socket.send(message);
      timer = setTimeout(() => {
        if (left > 0) {
          attempt(left - 1);
          return;
        }
        socket.close();
        reject(new Error(`${LABEL}: ${key.server}:${key.port} did not answer the DNS update, sent ${DNS_UPDATE_SENDS} times`));
      }, resolveTimeout(DNS_QUERY_MS));
    };
    socket.once("message", (answer) => {
      clearTimeout(timer);
      socket.close();
      resolve(answer);
    });
    socket.once("error", (error) => {
      clearTimeout(timer);
      socket.close();
      reject(error);
    });
    socket.connect(Number(key.port), address, () => attempt(DNS_UPDATE_SENDS - 1));
  });
  expect(reply.readUInt16BE(0), `${LABEL}: the answer of ${key.server} must carry the id of the update`).toBe(message.readUInt16BE(0));
  const rcode = reply[3] & 0x0f;
  return DNS_RCODES[rcode] || `RCODE ${rcode}`;
}

exports.register = function (shared) {
  test("provision: the deploy domain equals the provision fqdn", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const provider = anyProvider();
    test.setTimeout(resolveTimeout(BASE_MS + SERVER_MS + DEPLOY_LINE_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const offer = await placement(fixture.context, provider);
      const order = orderLine(freshSalesOrder(), "1");
      await commitValues(fixture, order, offer);
      cleanup(() => destroy(shared, fixture, order));
      const outputs = await provision(shared, fixture, order);
      const commit = await workspaces.commitWorkspaceFile(fixture, "devices.yml", EMPTY_INVENTORY, LABEL);
      const deploy = templateOf(fixture, "deploy");
      const role = requireDotenvValue(process.env.SEMAPHORE_WORKSPACE_PROBE_ROLE, "SEMAPHORE_WORKSPACE_PROBE_ROLE");
      const taskId = await workspaces.startTask(shared, fixture.page, deploy.project_id, deploy.template_id, {
        SALES_ORDER: order.salesOrder,
        LINE: order.line,
        HOST: host,
        HOST_KEY: sshEd25519PublicLine(),
        ROLES: role,
        DNS_LABEL: order.label,
        INVENTORY_COMMIT: commit,
      });
      let line;
      try {
        line = await awaitLine(shared, fixture.page, deploy.project_id, taskId, DEPLOYING, DEPLOY_LINE_MS, `${LABEL}: deploy of ${order.name}`);
      } finally {
        await shared.stopUnfinishedTask(fixture.page, deploy.project_id, taskId);
      }
      const [, roles, salesOrder, lineNumber, , domain] = DEPLOYING.exec(line);
      expect([roles, salesOrder, lineNumber], `${LABEL}: the deploy must serve ${role} of ${order.salesOrder}/${order.line}`).toEqual([
        role,
        order.salesOrder,
        order.line,
      ]);
      expect(domain, `${LABEL}: the domain the deploy of ${order.name} builds must be the fqdn its provision returned`).toBe(outputs.fqdn);
    });
  });

  test("provision runner: tofu reports the pinned version", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const pinned = pinnedOpentofu();
    expect(atLeast(pinned, MINIMUM_OPENTOFU), `${LABEL}: the pinned OpenTofu ${pinned} must be ${MINIMUM_OPENTOFU.join(".")} or newer`).toBe(true);
    test.setTimeout(resolveTimeout(BASE_MS + PROBE_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const identity = platformTemplate(fixture, "unlock");
      const what = `${LABEL}: tofu version on the runner ${identity.runner_tag}`;
      const run = await workspaces.runProbe(shared, fixture, identity.project_id, "tofu version", [], what);
      workspaces.expectSucceeded(run, what);
      expect(
        run.lines.map(bare).filter((line) => OPENTOFU_LINE.test(line)),
        `${what}: the provision runner must report exactly one OpenTofu, the pinned v${pinned}; output tail:\n${workspaces.outputTail(run.lines)}`,
      ).toEqual([`OpenTofu v${pinned}`]);
    });
  });

  test("provision: proxmox creates and destroys a server", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireProvider("proxmox");
    test.setTimeout(resolveTimeout(BASE_MS + SERVER_MS));
    expect(await serverLifecycle(shared, browser, "proxmox"), `${LABEL}: the destroy of the proxmox server must delete its state and lock`).toEqual([]);
  });

  test("provision: a second writer waits for the lock", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const provider = anyProvider();
    test.setTimeout(resolveTimeout(BASE_MS + 2 * PROVISION_MS + DESTROY_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const offer = await placement(fixture.context, provider);
      const order = orderLine(freshSalesOrder(), "1");
      await commitValues(fixture, order, offer);
      cleanup(() => destroy(shared, fixture, order));
      const target = await serverTarget(fixture, provider, offer);
      const identity = orderTemplate(fixture, "provision", order);
      const ids = [
        await workspaces.startTask(shared, fixture.page, identity.project_id, identity.template_id, providerSurvey(order)),
        await workspaces.startTask(shared, fixture.page, identity.project_id, identity.template_id, providerSurvey(order)),
      ];
      const runs = [];
      try {
        for (const [index, id] of ids.entries()) {
          const what = `${LABEL}: provision writer ${index + 1} of ${order.name}`;
          runs.push({ ...(await workspaces.awaitTask(shared, fixture.page, identity.project_id, id, 2 * PROVISION_MS, what)), what });
        }
      } finally {
        for (const id of ids) {
          await shared.stopUnfinishedTask(fixture.page, identity.project_id, id);
        }
      }
      const [first, second] = runs;
      workspaces.expectSucceeded(first, first.what);
      const outputs = outputsOf(first);
      const overlapped = Boolean(second.task.start && first.task.end) && new Date(second.task.start) < new Date(first.task.end);
      if (overlapped) {
        workspaces.expectRefused(second, LOCK_FAILURE, second.what);
      } else {
        workspaces.expectSucceeded(second, second.what);
        expectLine(second, NOTHING_CHANGED);
        expect(outputsOf(second).server_id, `${second.what}: the second writer must find the server of the first`).toBe(outputs.server_id);
      }
      await target.expectRunning(outputs, order);
    });
  });

  test("provision: unlock clears only a stale lock", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const provider = anyProvider();
    test.setTimeout(resolveTimeout(BASE_MS + 2 * UNLOCK_MS + PROVISION_MS + DESTROY_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const salesOrder = freshSalesOrder();
      const stale = orderLine(salesOrder, "1");
      const running = orderLine(salesOrder, "2");
      const state = await stateBucket(fixture);
      const lock = await plantLock(state, `${stale.salesOrder}/${stale.line}.tfstate`);
      cleanup(() => state.remove(lock));
      const cleared = await runPlatform(shared, fixture, "unlock", orderSurvey(stale), UNLOCK_MS, `${LABEL}: unlock of the stale lock of ${stale.name}`);
      workspaces.expectSucceeded(cleared, cleared.what);
      expectNoLine(cleared, "holds no lock");
      expect(await state.exists(lock), `${cleared.what}: the unlock must delete ${state.bucket}/${lock}`).toBe(false);

      await commitValues(fixture, running, await placement(fixture.context, provider));
      cleanup(() => destroy(shared, fixture, running));
      const identity = orderTemplate(fixture, "provision", running);
      const taskId = await workspaces.startTask(shared, fixture.page, identity.project_id, identity.template_id, providerSurvey(running));
      try {
        await awaitLine(shared, fixture.page, identity.project_id, taskId, new RegExp(INITIALIZED), PROVISION_MS, `${LABEL}: provision of ${running.name}`);
        const refused = await runPlatform(shared, fixture, "unlock", orderSurvey(stale), UNLOCK_MS, `${LABEL}: unlock while ${running.name} provisions`);
        workspaces.expectRefused(refused, `a provision or destroy task of ws-${fixture.workspace} is running`, refused.what);
        const what = `${LABEL}: provision of ${running.name}`;
        workspaces.expectSucceeded(await workspaces.awaitTask(shared, fixture.page, identity.project_id, taskId, PROVISION_MS, what), what);
      } finally {
        await shared.stopUnfinishedTask(fixture.page, identity.project_id, taskId);
      }
    });
  });

  test("provision: incus creates and destroys a server", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireProvider("incus");
    test.setTimeout(resolveTimeout(BASE_MS + SERVER_MS));
    expect(await serverLifecycle(shared, browser, "incus"), `${LABEL}: the destroy of the incus server must delete its state and lock`).toEqual([]);
  });

  test("dns: a BYO record is created once and removed", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireDnsLive();
    test.setTimeout(resolveTimeout(BASE_MS + 5 * DNS_MS + 4 * RECORD_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const order = orderLine(freshSalesOrder(), "1");
      const { zone } = await workspaceDns(shared, fixture);
      const servers = await recordServers(fixture, zone);
      const fqdn = `${order.label}.ws-${fixture.workspace}.${zone}`;
      cleanup(() => removeRecord(shared, fixture, order, host));
      const created = await dnsTask(shared, fixture, "create", order, host);
      workspaces.expectSucceeded(created, created.what);
      expect(appliedCounts(created).added, `${created.what}: the first create must add the record`).toBeGreaterThan(0);
      await expectRecord(servers, fqdn, [host], created.what);
      const again = await dnsTask(shared, fixture, "create", order, host);
      workspaces.expectSucceeded(again, `second ${again.what}`);
      expectLine(again, NOTHING_CHANGED);
      await expectRecord(servers, fqdn, [host], `second ${again.what}`);
      const removed = await dnsTask(shared, fixture, "remove", order, host);
      workspaces.expectSucceeded(removed, removed.what);
      expect(destroyedCount(removed), `${removed.what}: the remove must delete the record`).toBeGreaterThan(0);
      await expectRecord(servers, fqdn, [], removed.what);
      const removedAgain = await dnsTask(shared, fixture, "remove", order, host);
      workspaces.expectSucceeded(removedAgain, `second ${removedAgain.what}`);
      expectLine(removedAgain, '{"destroyed": [], "state": "deleted"}');
    });
  });

  test("dns: remove deletes only its own record", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireDnsLive();
    test.setTimeout(resolveTimeout(BASE_MS + 5 * DNS_MS + 4 * RECORD_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const salesOrder = freshSalesOrder();
      const removedLine = orderLine(salesOrder, "1");
      const keptLine = orderLine(salesOrder, "2");
      const { zone } = await workspaceDns(shared, fixture);
      const servers = await recordServers(fixture, zone);
      const name = (order) => `${order.label}.ws-${fixture.workspace}.${zone}`;
      for (const order of [removedLine, keptLine]) {
        cleanup(() => removeRecord(shared, fixture, order, host));
        const created = await dnsTask(shared, fixture, "create", order, host);
        workspaces.expectSucceeded(created, created.what);
        await expectRecord(servers, name(order), [host], created.what);
      }
      await removeRecord(shared, fixture, removedLine, host);
      await expectRecord(servers, name(removedLine), [], `${LABEL}: dns remove of ${removedLine.name}`);
      expect(
        await addressesOf(servers, name(keptLine)),
        `${LABEL}: the record of ${keptLine.name} must still resolve to ${host} after the remove of ${removedLine.name}`,
      ).toEqual([host]);
    });
  });

  test("dns: a taken name is refused", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireDnsLive();
    const provider = anyProvider();
    test.setTimeout(resolveTimeout(BASE_MS + 3 * DNS_MS + PROVISION_MS + DESTROY_MS + 4 * RECORD_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const salesOrder = freshSalesOrder();
      const owner = orderLine(salesOrder, "1");
      const record = { ...orderLine(salesOrder, "2"), label: owner.label };
      const server = { ...orderLine(salesOrder, "3"), label: owner.label };
      const { zone } = await workspaceDns(shared, fixture);
      const servers = await recordServers(fixture, zone);
      const fqdn = `${owner.label}.ws-${fixture.workspace}.${zone}`;
      const refusal = `${fqdn} already holds an A, AAAA or CNAME record`;
      const state = await stateBucket(fixture);
      cleanup(() => removeRecord(shared, fixture, owner, host));
      const created = await dnsTask(shared, fixture, "create", owner, host);
      workspaces.expectSucceeded(created, created.what);
      await expectRecord(servers, fqdn, [host], created.what);

      cleanup(() => removeRecord(shared, fixture, record, host));
      const taken = await dnsTask(shared, fixture, "create", record, host);
      workspaces.expectRefused(taken, refusal, taken.what);
      expect(
        await state.exists(`${record.salesOrder}/${record.line}.dns.tfstate`),
        `${taken.what}: the refusal must come before any write, so no record state may exist`,
      ).toBe(false);
      await expectRecord(servers, fqdn, [host], `${LABEL}: the record of ${owner.name} after the refused create`);

      await commitValues(fixture, server, await placement(fixture.context, provider));
      cleanup(() => destroy(shared, fixture, server));
      const provisioned = await runPlatform(
        shared,
        fixture,
        orderKind("provision", server),
        providerSurvey(server),
        PROVISION_MS,
        `${LABEL}: provision of ${server.name} on ${fqdn}`,
      );
      workspaces.expectRefused(provisioned, refusal, provisioned.what);
      expect(
        await state.exists(`${server.salesOrder}/${server.line}.tfstate`),
        `${provisioned.what}: the refusal must come before any write, so no server state may exist`,
      ).toBe(false);
      await expectRecord(servers, fqdn, [host], `${LABEL}: the record of ${owner.name} after the refused provision`);
    });
  });

  test("dns: unlock clears a stale record lock", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireDnsLive();
    test.setTimeout(resolveTimeout(BASE_MS + UNLOCK_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const order = orderLine(freshSalesOrder(), "1");
      const state = await stateBucket(fixture);
      const lock = await plantLock(state, `${order.salesOrder}/${order.line}.dns.tfstate`);
      cleanup(() => state.remove(lock));
      const cleared = await dnsTask(shared, fixture, "unlock", order, host);
      workspaces.expectSucceeded(cleared, cleared.what);
      expectNoLine(cleared, "holds no lock");
      expect(await state.exists(lock), `${cleared.what}: the unlock must delete ${state.bucket}/${lock}`).toBe(false);
    });
  });

  test("provision: the record lies in the workspace's zone", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const provider = anyProvider();
    test.setTimeout(resolveTimeout(BASE_MS + SERVER_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const offer = await placement(fixture.context, provider);
      const order = orderLine(freshSalesOrder(), "1");
      await commitValues(fixture, order, offer);
      cleanup(() => destroy(shared, fixture, order));
      const { zone } = await workspaceDns(shared, fixture);
      const servers = await recordServers(fixture, zone);
      const outputs = await provision(shared, fixture, order);
      expect(outputs.fqdn, `${LABEL}: the provision of ${order.name} must name its record <label>.ws-<id>.<WORKSPACE_DNS_ZONE>`).toBe(
        `${order.label}.ws-${fixture.workspace}.${zone}`,
      );
      await expectRecord(servers, outputs.fqdn, outputs.host, `${LABEL}: the record of ${order.name} in ${zone}`);
      await destroy(shared, fixture, order);
      await expectRecord(servers, outputs.fqdn, [], `${LABEL}: the record of ${order.name} after the destroy`);
    });
  });

  test("provision: a route53 key runs the whole record lifecycle", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const flavor = dnsFlavor();
    test.skip(flavor !== "route53", `PROVISION_DNS_FLAVOR=${flavor}: services.semaphore.workspaces.dns.flavor is not route53`);
    requireDnsLive();
    test.setTimeout(resolveTimeout(BASE_MS + 3 * DNS_MS + 3 * RECORD_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const order = orderLine(freshSalesOrder(), "1");
      const { zone, zoneId } = await workspaceDns(shared, fixture);
      expect(Boolean(zoneId), `${LABEL}: under route53 the provision environment of ws-${fixture.workspace} must name WORKSPACE_DNS_ZONE_ID`).toBe(true);
      const servers = await recordServers(fixture, zone);
      const fqdn = `${order.label}.ws-${fixture.workspace}.${zone}`;
      cleanup(() => removeRecord(shared, fixture, order, host));
      const created = await dnsTask(shared, fixture, "create", order, host);
      workspaces.expectSucceeded(created, created.what);
      await expectRecord(servers, fqdn, [host], created.what);
      const again = await dnsTask(shared, fixture, "create", order, host);
      workspaces.expectSucceeded(again, `second ${again.what}`);
      expectLine(again, NOTHING_CHANGED);
      const removed = await dnsTask(shared, fixture, "remove", order, host);
      workspaces.expectSucceeded(removed, removed.what);
      await expectRecord(servers, fqdn, [], removed.what);

      const keys = await vaultRecord(fixture.context, TENANT_MOUNT, `ws-${fixture.workspace}-provision/dns`);
      const foreign = `probe.ws-${crypto.randomUUID()}.${zone}`;
      const intrusion = await changeRecord(fixture.context, keys, zoneId, "CREATE", foreign, host);
      if (intrusion.status() === 200) {
        cleanup(async () => {
          const undone = await changeRecord(fixture.context, keys, zoneId, "DELETE", foreign, host);
          await workspaces.expectStatus(undone, [200], `${LABEL}: the delete of the record ${foreign} the key of ws-${fixture.workspace} wrongly created`);
        });
      }
      expect(intrusion.status(), `${LABEL}: the Route 53 key of ws-${fixture.workspace} must be refused on ${foreign}`).toBe(403);
      expect(await intrusion.text(), `${LABEL}: Route 53 must answer AccessDenied on ${foreign}`).toContain("AccessDenied");
    });
  });

  /**
   * Args:
   *   page: a page carrying the administrator session.
   *   identity: a template identity of `platformTemplate`.
   *
   * Returns:
   *   `[role, permissions]` of every grant on the template, none for a
   *   template that is gone.
   */
  async function grantsOf(page, identity) {
    const response = await shared.apiResponse(page, "GET", `/project/${identity.project_id}/templates/${identity.template_id}/perms`);
    expect([200, 404], `${LABEL}: GET the grants of template ${identity.template_id} answered ${response.status()}`).toContain(response.status());
    return response.status() === 404 ? [] : (await response.json()).map((grant) => [grant.role_slug, grant.permissions]);
  }

  test("provision: the state is encrypted with the workspace key", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const provider = anyProvider();
    test.setTimeout(resolveTimeout(2 * BASE_MS + 2 * PROVISION_MS + DESTROY_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const offer = await placement(fixture.context, provider);
      const order = orderLine(freshSalesOrder(), "1");
      await commitValues(fixture, order, offer);
      cleanup(() => destroy(shared, fixture, order));
      const outputs = await provision(shared, fixture, order);
      const key = `${order.salesOrder}/${order.line}.tfstate`;
      const sealed = await (await stateBucket(fixture)).get(key);
      expectEncryptedState(sealed, [order.name, order.label, ...outputs.host], `${LABEL}: ${key} of ws-${fixture.workspace}`);
      await workspaces.withWorkspace(shared, browser, LABEL, "", async (other, otherCleanup) => {
        await commitValues(other, order, offer);
        const foreign = await stateBucket(other);
        await foreign.put(key, sealed);
        otherCleanup(() => foreign.remove(key));
        const run = await runPlatform(
          shared,
          other,
          orderKind("provision", order),
          providerSurvey(order),
          PROVISION_MS,
          `${LABEL}: provision of ${order.name} in ws-${other.workspace} over the state of ws-${fixture.workspace}`,
        );
        workspaces.expectRefused(run, STATE_LIST_FAILED, run.what);
        expectNoLine(run, "Apply complete!");
        expect(await foreign.get(key), `${run.what}: the failed read must leave the state of ws-${fixture.workspace} as it was`).toBe(sealed);
      });
    });
  });

  test("provision: no unencrypted state without the key", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const provider = anyProvider();
    test.setTimeout(resolveTimeout(BASE_MS + PROVISION_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const order = orderLine(freshSalesOrder(), "1");
      await commitValues(fixture, order, await placement(fixture.context, provider));
      const identity = orderTemplate(fixture, "provision", order);
      const what = `${LABEL}: provision of ${order.name} from the probe ws-${fixture.workspace}, which the OpenBao role ws-${fixture.workspace}-provision-${order.provider} does not bind`;
      const survey = providerSurvey(order);
      const run = {
        ...(await workspaces.runProbe(
          shared,
          fixture,
          identity.project_id,
          LOGIN_PROBE_SCRIPT,
          [survey.SALES_ORDER, survey.LINE, survey.PROVIDER_TOKEN, order.provider],
          what,
        )),
        what,
      };
      workspaces.expectSucceeded(run, what);
      const exits = probeLines(run, "exit");
      expect(exits.length === 1 && exits[0] !== "0", `${what}: the provision script must exit non-zero, it reported ${exits.join(", ")}`).toBe(true);
      expectNoLine(run, INITIALIZED);
      const state = await stateBucket(fixture);
      for (const key of [`${order.salesOrder}/${order.line}.tfstate`, `${order.salesOrder}/${order.line}.tfstate.tflock`, `${order.salesOrder}/${order.line}.provision.json`]) {
        expect(await state.exists(key), `${what}: the run must write no ${state.bucket}/${key}`).toBe(false);
      }
    });
  });

  test("provision isolation: a workspace task reads no provision secret", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(BASE_MS + PROBE_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const paths = PROVISION_PATHS(fixture.workspace);
      const probe = await workspaceProbe(shared, fixture, paths);
      expect(
        probe.names.filter((name) => PROVISION_SECRET_ENV.test(name)),
        `${probe.what}: the workspace runner must hold no provider token, DNS credential or S3 identity in its environment`,
      ).toEqual([]);
      expect(probe.statuses, `${probe.what}: OpenBao must answer 403 on every provision path`).toEqual(
        Object.fromEntries(paths.map((path) => [path, "403"])),
      );
    });
  });

  test("provision isolation: a workspace task reads no customer token", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(BASE_MS + PROBE_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const path = `${TENANT_MOUNT}/data/${CUSTOMER_TOKEN_PATH(fixture.workspace, "hetzner")}`;
      const probe = await workspaceProbe(shared, fixture, [path]);
      expect(probe.statuses, `${probe.what}: OpenBao must answer 403 on the customer token ${path}`).toEqual({ [path]: "403" });
    });
  });

  test("provision isolation: a provider template's task token logs in to its own provider role only", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const kinds = [...ALL_PROVIDERS.map((provider) => ["provision", provider]), ["destroy", ALL_PROVIDERS[0]]];
    test.setTimeout(resolveTimeout(BASE_MS + kinds.length * PROBE_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const roles = [
        `ws-${fixture.workspace}-provision`,
        `ws-${fixture.workspace}-zone`,
        ...ALL_PROVIDERS.map((provider) => `ws-${fixture.workspace}-provision-${provider}`),
      ];
      for (const [action, provider] of kinds) {
        const own = `ws-${fixture.workspace}-provision-${provider}`;
        const { logins, what } = await loginProbe(shared, fixture, `${action}-${provider}`, roles);
        expect(logins[own], `${what}: the task token of ${action}-${provider} must log in to ${own}`).toBe("200");
        for (const role of roles.filter((candidate) => candidate !== own)) {
          expect(LOGIN_REFUSED, `${what}: OpenBao must refuse the task token of ${action}-${provider} on ${role}, it answered ${logins[role]}`).toContain(
            logins[role],
          );
        }
      }
    });
  });

  test("provision isolation: a provision task reads no foreign provider secret", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(BASE_MS + PROVIDERS.length * PROBE_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      for (const provider of PROVIDERS) {
        const paths = FOREIGN_PROVIDER_PATHS(fixture.workspace, provider);
        const probe = await provisionProbe(shared, fixture, provider, paths);
        expect(
          probe.statuses,
          `${probe.what}: OpenBao must answer 403 on every secret of another provider, on the zone token and on the DNS token of another zone`,
        ).toEqual(Object.fromEntries(paths.map((path) => [path, "403"])));
      }
    });
  });

  test("provision rights: the store runs and reads its granted templates and changes none", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(BASE_MS + 2 * PROVISION_MS + 10 * REQUEST_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const token = await storeSemaphoreToken(fixture.context);
      const store = (method, path, data) => asStore(shared, fixture.context, token, method, path, data);
      const kind = `provision-${ALL_PROVIDERS[0]}`;
      const identity = platformTemplate(fixture, kind);
      const project = identity.project_id;
      const order = orderLine(freshSalesOrder(), "1");
      const started = await store("POST", `/project/${project}/tasks`, {
        template_id: identity.template_id,
        environment: JSON.stringify(providerSurvey(order)),
      });
      await workspaces.expectStatus(started, [200, 201], `${LABEL}: the store's task of ${kind} ws-${fixture.workspace}`);
      const taskId = (await started.json()).id;
      try {
        await workspaces.awaitTask(shared, fixture.page, project, taskId, PROVISION_MS, `${LABEL}: the store's task ${taskId}`);
      } finally {
        await shared.stopUnfinishedTask(fixture.page, project, taskId);
      }
      for (const path of [
        `/project/${project}/templates/${identity.template_id}`,
        `/project/${project}/tasks/${taskId}`,
        `/project/${project}/tasks/${taskId}/raw_output`,
      ]) {
        await workspaces.expectStatus(await store("GET", path), [200], `${LABEL}: the store's GET ${path}`);
      }
      const template = await shared.api(fixture.page, "GET", `/project/${project}/templates/${identity.template_id}`);
      const ungranted = await workspaces.namedTemplate(shared, fixture.page, project, `probe ws-${fixture.workspace}`);
      for (const [method, path, data] of [
        ["PUT", `/project/${project}/templates/${identity.template_id}`, { ...template, description: LABEL }],
        ["POST", `/project/${project}/templates`, { ...template, id: undefined, name: `${LABEL} ws-${fixture.workspace}` }],
        ["POST", `/project/${project}/tasks`, { template_id: ungranted.id, environment: "{}" }],
      ]) {
        await workspaces.expectStatus(await store(method, path, data), [403], `${LABEL}: the store's ${method} ${path}`);
      }
    });
  });

  test("provision rights: destroy removes the grants", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(BASE_MS + 10 * REQUEST_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const token = await storeSemaphoreToken(fixture.context);
      const kinds = [...ORDER_ACTIONS.flatMap((action) => ALL_PROVIDERS.map((provider) => `${action}-${provider}`)), ...SHARED_KINDS];
      const identities = kinds.map((kind) => platformTemplate(fixture, kind));
      for (const identity of identities) {
        expect(await grantsOf(fixture.page, identity), `${LABEL}: apply must grant ${GUEST} run and read on template ${identity.template_id}`).toEqual([
          [GUEST, RUN_AND_READ],
        ]);
      }
      await workspaces.destroyWorkspace(shared, fixture, LABEL);
      const [provisionIdentity] = identities;
      const refused = await asStore(shared, fixture.context, token, "POST", `/project/${provisionIdentity.project_id}/tasks`, {
        template_id: provisionIdentity.template_id,
        environment: JSON.stringify(providerSurvey(orderLine(freshSalesOrder(), "1"))),
      });
      await workspaces.expectStatus(refused, [403, 404], `${LABEL}: the store's task of ${kinds[0]} ws-${fixture.workspace} after destroy`);
      for (const identity of identities) {
        expect(await grantsOf(fixture.page, identity), `${LABEL}: destroy must leave no grant on template ${identity.template_id}`).toEqual([]);
      }
    });
  });

  test("provision rights: apply creates the dns template with its grant", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(BASE_MS + 10 * REQUEST_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const identity = platformTemplate(fixture, "dns");
      const name = `dns ws-${fixture.workspace}`;
      const named = await workspaces.namedTemplates(shared, fixture.page, identity.project_id, name);
      expect(named.map((template) => template.id), `${LABEL}: apply must create exactly one ${name} in the provision project`).toEqual([
        identity.template_id,
      ]);
      workspaces.expectLockedTemplate(await shared.api(fixture.page, "GET", `/project/${identity.project_id}/templates/${identity.template_id}`), LABEL);
      expect(await grantsOf(fixture.page, identity), `${LABEL}: apply must grant ${GUEST} run and read on ${name}`).toEqual([[GUEST, RUN_AND_READ]]);
      await workspaces.destroyWorkspace(shared, fixture, LABEL);
      expect(await workspaces.namedTemplates(shared, fixture.page, identity.project_id, name), `${LABEL}: destroy must remove ${name}`).toEqual([]);
      expect(await grantsOf(fixture.page, identity), `${LABEL}: destroy must remove the grant of ${name}`).toEqual([]);
    });
  });

  test("provision rights: apply creates the zone template with its grant", async ({ browser }) => {
    workspaces.requireWorkspaces();
    test.setTimeout(resolveTimeout(BASE_MS + 10 * REQUEST_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture) => {
      const identity = platformTemplate(fixture, "zone");
      const name = `zone ws-${fixture.workspace}`;
      const named = await workspaces.namedTemplates(shared, fixture.page, identity.project_id, name);
      expect(named.map((template) => template.id), `${LABEL}: apply must create exactly one ${name} in the provision project`).toEqual([
        identity.template_id,
      ]);
      workspaces.expectLockedTemplate(await shared.api(fixture.page, "GET", `/project/${identity.project_id}/templates/${identity.template_id}`), LABEL);
      expect(await grantsOf(fixture.page, identity), `${LABEL}: apply must grant ${GUEST} run and read on ${name}`).toEqual([[GUEST, RUN_AND_READ]]);
      await workspaces.destroyWorkspace(shared, fixture, LABEL);
      expect(await workspaces.namedTemplates(shared, fixture.page, identity.project_id, name), `${LABEL}: destroy must remove ${name}`).toEqual([]);
      expect(await grantsOf(fixture.page, identity), `${LABEL}: destroy must remove the grant of ${name}`).toEqual([]);
    });
  });

  test("zone: a zone is created once, shown and deleted", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const domain = requireZoneLive();
    test.setTimeout(resolveTimeout(BASE_MS + 5 * ZONE_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const order = orderLine(freshSalesOrder(), "1");
      cleanup(() => deleteZone(shared, fixture, order, domain));
      const created = await zoneTask(shared, fixture, "create", order, domain);
      workspaces.expectSucceeded(created, created.what);
      expect(appliedCounts(created).added, `${created.what}: the first create must add the zone`).toBe(1);
      const zone = zoneOutputs(created, domain);
      const state = await stateBucket(fixture);
      const key = `${order.salesOrder}/${order.line}.zone.tfstate`;
      expectEncryptedState(await state.get(key), [domain, zone.zone_id], `${LABEL}: ${key} of ws-${fixture.workspace}`);
      const again = await zoneTask(shared, fixture, "create", order, domain);
      workspaces.expectSucceeded(again, `second ${again.what}`);
      expectLine(again, NOTHING_CHANGED);
      expect(zoneOutputs(again, domain).zone_id, `second ${again.what}: a repeated create must keep the zone`).toBe(zone.zone_id);
      const shown = await zoneTask(shared, fixture, "show", order, domain);
      workspaces.expectSucceeded(shown, shown.what);
      expect(zoneOutputs(shown, domain).zone_id, `${shown.what}: show must print the zone_id of create`).toBe(zone.zone_id);
      expectNoLine(shown, "Apply complete!");
      const deleted = await zoneTask(shared, fixture, "delete", order, domain);
      workspaces.expectSucceeded(deleted, deleted.what);
      expect(destroyedCount(deleted), `${deleted.what}: the delete must remove the zone`).toBe(1);
      expect(zoneLine(deleted), `${deleted.what}: the delete must name the deleted zone`).toEqual({ deleted: true, zone: domain });
      expect(await state.exists(key), `${deleted.what}: the delete must remove the zone state`).toBe(false);
      const deletedAgain = await zoneTask(shared, fixture, "delete", order, domain);
      workspaces.expectSucceeded(deletedAgain, `second ${deletedAgain.what}`);
      expect(zoneLine(deletedAgain), `second ${deletedAgain.what}: a delete without a zone must succeed with nothing to do`).toEqual({
        deleted: true,
        zone: null,
      });
    });
  });

  test("zone: a foreign zone is refused", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const domain = requireZoneLive();
    test.setTimeout(resolveTimeout(BASE_MS + 4 * ZONE_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const salesOrder = freshSalesOrder();
      const owner = orderLine(salesOrder, "1");
      const foreign = orderLine(salesOrder, "2");
      const state = await stateBucket(fixture);
      cleanup(() => deleteZone(shared, fixture, owner, domain));
      const created = await zoneTask(shared, fixture, "create", owner, domain);
      workspaces.expectSucceeded(created, created.what);
      const zone = zoneOutputs(created, domain);
      cleanup(() => deleteZone(shared, fixture, foreign, domain));
      const refused = await zoneTask(shared, fixture, "create", foreign, domain);
      workspaces.expectRefused(refused, `the Cloudflare account already holds DOMAIN ${domain}`, refused.what);
      expect(
        await state.exists(`${foreign.salesOrder}/${foreign.line}.zone.tfstate`),
        `${refused.what}: the refusal must come before any write, so no zone state may exist`,
      ).toBe(false);
      const shown = await zoneTask(shared, fixture, "show", owner, domain);
      workspaces.expectSucceeded(shown, shown.what);
      expect(zoneOutputs(shown, domain).zone_id, `${shown.what}: the refused create must leave the zone of ${owner.name}`).toBe(zone.zone_id);
    });
  });

  test("dns: the record state is encrypted", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireDnsLive();
    test.setTimeout(resolveTimeout(BASE_MS + 2 * DNS_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const order = orderLine(freshSalesOrder(), "1");
      const { zone } = await workspaceDns(shared, fixture);
      cleanup(() => removeRecord(shared, fixture, order, host));
      const created = await dnsTask(shared, fixture, "create", order, host);
      workspaces.expectSucceeded(created, created.what);
      const key = `${order.salesOrder}/${order.line}.dns.tfstate`;
      expectEncryptedState(await (await stateBucket(fixture)).get(key), [order.label, host, zone], `${LABEL}: ${key} of ws-${fixture.workspace}`);
    });
  });

  test("provision: a route53 key changes only its own names", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const flavor = dnsFlavor();
    test.skip(flavor !== "route53", `PROVISION_DNS_FLAVOR=${flavor}: services.semaphore.workspaces.dns.flavor is not route53`);
    requireDnsLive();
    test.setTimeout(resolveTimeout(BASE_MS + 6 * REQUEST_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const { zone, zoneId } = await workspaceDns(shared, fixture);
      const keys = await vaultRecord(fixture.context, TENANT_MOUNT, `ws-${fixture.workspace}-provision/dns`);
      const change = async (action, name, statuses) => {
        const response = await changeRecord(fixture.context, keys, zoneId, action, name, host);
        await workspaces.expectStatus(response, statuses, `${LABEL}: ${action} of ${name} with the Route 53 key of ws-${fixture.workspace}`);
        return response;
      };
      const own = `probe.ws-${fixture.workspace}.${zone}`;
      await change("CREATE", own, [200]);
      await change("DELETE", own, [200]);
      const foreign = `probe.ws-${crypto.randomUUID()}.${zone}`;
      const intrusion = await changeRecord(fixture.context, keys, zoneId, "CREATE", foreign, host);
      if (intrusion.status() === 200) {
        cleanup(() => change("DELETE", foreign, [200]));
      }
      expect(intrusion.status(), `${LABEL}: the Route 53 key of ws-${fixture.workspace} must be refused on ${foreign}`).toBe(403);
      expect(await intrusion.text(), `${LABEL}: Route 53 must answer AccessDenied on ${foreign}`).toContain("AccessDenied");
    });
  });

  test("provision: route53 and the state backend keep their own keys", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const flavor = dnsFlavor();
    test.skip(flavor !== "route53", `PROVISION_DNS_FLAVOR=${flavor}: services.semaphore.workspaces.dns.flavor is not route53`);
    requireDnsLive();
    const provider = anyProvider();
    test.setTimeout(resolveTimeout(BASE_MS + SERVER_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, "", async (fixture, cleanup) => {
      const offer = await placement(fixture.context, provider);
      const order = orderLine(freshSalesOrder(), "1");
      await commitValues(fixture, order, offer);
      cleanup(() => destroy(shared, fixture, order));
      const { zone } = await workspaceDns(shared, fixture);
      const servers = await recordServers(fixture, zone);
      const outputs = await provision(shared, fixture, order);
      const key = `${order.salesOrder}/${order.line}.tfstate`;
      const state = await stateBucket(fixture);
      expect(await state.exists(key), `${LABEL}: the provision of ${order.name} must write its state ${state.bucket}/${key} to SeaweedFS`).toBe(true);
      await expectRecord(servers, outputs.fqdn, outputs.host, `${LABEL}: the Route 53 record of ${order.name}`);
    });
  });

  function requireKnot() {
    const flavor = dnsFlavor();
    test.skip(flavor !== "knot", `PROVISION_DNS_FLAVOR=${flavor}: services.semaphore.workspaces.dns.flavor is not knot`);
    requireDnsLive();
  }

  test("provision: a knot key changes only its own names", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireKnot();
    test.setTimeout(resolveTimeout(BASE_MS + 2 * DNS_MS + 4 * RECORD_MS + 10 * REQUEST_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const order = orderLine(freshSalesOrder(), "1");
      const { zone } = await workspaceDns(shared, fixture);
      const servers = await recordServers(fixture, zone);
      const key = await vaultRecord(fixture.context, TENANT_MOUNT, `ws-${fixture.workspace}-provision/dns`);
      const fqdn = `${order.label}.ws-${fixture.workspace}.${zone}`;
      cleanup(() => removeRecord(shared, fixture, order, host));
      const created = await dnsTask(shared, fixture, "create", order, host);
      workspaces.expectSucceeded(created, created.what);
      await expectRecord(servers, fqdn, [host], created.what);
      const removed = await dnsTask(shared, fixture, "remove", order, host);
      workspaces.expectSucceeded(removed, removed.what);
      await expectRecord(servers, fqdn, [], removed.what);

      const own = `probe.ws-${fixture.workspace}.${zone}`;
      const what = (target) => `${LABEL}: an update of ${target} with the knot key of ws-${fixture.workspace}`;
      cleanup(() => knotUpdate(key, zone, [{ name: own, type: "A", remove: true }]));
      expect(await knotUpdate(key, zone, [{ name: own, type: "A", rdata: aRecord(host) }]), what(own)).toBe("NOERROR");
      await expectRecord(servers, own, [host], what(own));
      expect(await knotUpdate(key, zone, [{ name: own, type: "A", remove: true }]), `${what(own)} that deletes it`).toBe("NOERROR");
      await expectRecord(servers, own, [], `${what(own)} that deletes it`);
      for (const [target, change] of [
        ["a name of another workspace", { name: `probe.ws-${crypto.randomUUID()}.${zone}`, type: "A", rdata: aRecord(host) }],
        [`the apex of ${zone}`, { name: zone, type: "TXT", rdata: txtRecord(LABEL) }],
        [`an MX record on ${own}`, { name: own, type: "MX", rdata: mxRecord(own) }],
      ]) {
        expect(DNS_REFUSALS, `${what(target)} must be refused`).toContain(await knotUpdate(key, zone, [change]));
      }
    });
  });

  test("dns: without the taken-name check a create loses the other line's record", async ({ browser }) => {
    workspaces.requireWorkspaces();
    requireKnot();
    test.setTimeout(resolveTimeout(BASE_MS + 2 * DNS_MS + 4 * RECORD_MS + 10 * REQUEST_MS));
    const host = privateTargetAddress();
    await workspaces.withWorkspace(shared, browser, LABEL, `${host}:${SSH_PORT}`, async (fixture, cleanup) => {
      const owner = orderLine(freshSalesOrder(), "1");
      const { zone } = await workspaceDns(shared, fixture);
      const servers = await recordServers(fixture, zone);
      const key = await vaultRecord(fixture.context, TENANT_MOUNT, `ws-${fixture.workspace}-provision/dns`);
      const fqdn = `${owner.label}.ws-${fixture.workspace}.${zone}`;
      cleanup(() => removeRecord(shared, fixture, owner, host));
      const created = await dnsTask(shared, fixture, "create", owner, host);
      workspaces.expectSucceeded(created, created.what);
      await expectRecord(servers, fqdn, [host], created.what);
      const unchecked = `${LABEL}: the second line's record on ${fqdn}, written with the workspace key and without the taken-name check`;
      expect(await knotUpdate(key, zone, [{ name: fqdn, type: "A", rdata: aRecord(CONTROL_ADDRESS) }]), unchecked).toBe("NOERROR");
      await expectRecord(servers, fqdn, [host, CONTROL_ADDRESS], `${unchecked}: the record set must take both lines' addresses`);
      expect(await knotUpdate(key, zone, [{ name: fqdn, type: "A", remove: true }]), `${unchecked}, removed as its record set`).toBe("NOERROR");
      await expectRecord(servers, fqdn, [], `${unchecked}: its removal must take the record of ${owner.name} with it`);
    });
  });
};

/**
 * Args:
 *   shared: the role's shared helpers. The spec file that passes them sets
 *     `trace`, `video` and `screenshot` to `off` at file level, because
 *     this test writes the SCS secret to OpenBao through the browser
 *     context and `trace` is a worker option no `describe` can set; the
 *     role's `PLAYWRIGHT_MAX_WORKERS=1` keeps it from running beside the
 *     other workspace tests.
 */
exports.registerScs = function (shared) {
  test("provision: scs runs in the customer's own project", async ({ browser }) => {
    workspaces.requireWorkspaces();
    const credential = scsTestCredential();
    const [offer] = catalogOffers("scs", SCS_REGION_KEYS);
    test.skip(
      offer === undefined,
      `services.semaphore.workspaces.catalog.scs offers no region that names ${SCS_REGION_KEYS.join(", ")}, so the SCS test project has no endpoint`,
    );
    expect(
      test.info().config.workers,
      "an scs provision beside test-workspace-runners.js changes the runners and tokens it counts, so PLAYWRIGHT_MAX_WORKERS must keep the semaphore spec files on one worker",
    ).toBe(1);
    test.setTimeout(resolveTimeout(BASE_MS + SERVER_MS));
    await workspaces.withWorkspace(shared, browser, LABEL, `${privateTargetAddress()}:${SSH_PORT}`, async (fixture, cleanup) => {
      const path = CUSTOMER_TOKEN_PATH(fixture.workspace, "scs");
      fixture.staged.push(path);
      await workspaces.vaultWrite(fixture.context, await workspaces.storeVaultToken(fixture.context), TENANT_MOUNT, path, {
        application_credential_id: credential.id,
        application_credential_secret: credential.secret,
      });
      const project = await scsProject(offer, credential);
      cleanup(() => project.revoke());
      const order = orderLine(freshSalesOrder(), "1");
      await commitValues(fixture, order, offer);
      cleanup(() => destroyWith(shared, fixture, order, customerSurvey(order)));
      const outputs = await provisionWith(shared, fixture, order, customerSurvey(order));
      expect(
        await project.serversNamed(order.name),
        `${LABEL}: the scs server ${order.name} must exist exactly once, as ${outputs.server_id}, in the project ${project.project} of the customer's credential`,
      ).toEqual([{ id: outputs.server_id, tenant_id: project.project }]);
      const destroyed = await destroyWith(shared, fixture, order, customerSurvey(order));
      expect(destroyedCount(destroyed), `${destroyed.what}: the destroy must remove the scs server and its record`).toBeGreaterThan(0);
      expect(await project.serversNamed(order.name), `${LABEL}: the destroy must remove ${order.name} from the project ${project.project}`).toEqual([]);
    });
  });
};
