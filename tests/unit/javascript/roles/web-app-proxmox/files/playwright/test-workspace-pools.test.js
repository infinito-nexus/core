const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const tls = require("node:tls");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-proxmox/files/playwright/test-workspace-pools.js");
const HOST = "pve.example.org";
const FINGERPRINT = "ab".repeat(32);
const RECORD = { endpoint: `https://${HOST}:8606`, certificate: "PINNED-CERTIFICATE", fingerprint: FINGERPRINT };
const PEER = {
  subject: { CN: HOST },
  subjectaltname: `DNS:${HOST}`,
  fingerprint256: FINGERPRINT.toUpperCase().match(/../g).join(":"),
};

/**
 * Args:
 *   calls: collects `{url, options}` of every request.
 *
 * Returns:
 *   A `node:https` whose request answers 200 without a socket.
 */
function fakeHttps(calls) {
  return {
    request(url, options, callback) {
      calls.push({ url, options });
      const request = new EventEmitter();
      request.destroy = (error) => request.emit("error", error);
      request.end = () => {
        const response = new EventEmitter();
        response.statusCode = 200;
        response.setEncoding = () => {};
        response.resume = () => {};
        callback(response);
        process.nextTick(() => response.emit("end"));
      };
      return request;
    },
  };
}

/**
 * Args:
 *   file: the spec file to load.
 *   calls: collects the requests of its `node:https`.
 *
 * Returns:
 *   `pinnedStatus` of the spec.
 */
function load(file, calls) {
  const playwrightTest = Object.assign(() => {}, { use: () => {}, describe: Object.assign(() => {}, { serial: () => {} }) });
  return loadInternals(
    file,
    ["pinnedStatus"],
    {
      "node:crypto": require("node:crypto"),
      "node:https": fakeHttps(calls),
      "node:tls": tls,
      "@playwright/test": { test: playwrightTest, expect: () => ({}) },
      "./timeouts": { resolveTimeout: (ms) => ms },
    },
    { URL },
  ).pinnedStatus;
}

/**
 * Args:
 *   old: text the spec holds exactly once.
 *   replacement: its replacement.
 *
 * Returns:
 *   The path of a planted copy of the spec, for a negative control.
 */
function planted(old, replacement) {
  const source = fs.readFileSync(SPEC, "utf8");
  assert.equal(source.split(old).length, 2, `the plant ${old} must occur exactly once`);
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "pools-plant-"));
  const file = path.join(directory, "test-workspace-pools.js");
  fs.writeFileSync(file, source.replace(old, replacement));
  return file;
}

test("pinnedStatus opens a fresh TLS session for every call", async () => {
  const calls = [];
  const status = await load(SPEC, calls)(RECORD, "/version", { Authorization: "PVEAPIToken=t=s" });
  assert.equal(status, 200);
  assert.equal(calls.length, 1);
  const { url, options } = calls[0];
  assert.equal(url.href, `https://${HOST}:8606/api2/json/version`);
  assert.equal(options.agent, false, "a pooled keep-alive socket would skip the handshake that checks the pin");
  assert.equal(options.rejectUnauthorized, true);
  assert.equal(options.ca, RECORD.certificate);
});

test("pinnedStatus checks the name and the pinned fingerprint", async () => {
  const calls = [];
  await load(SPEC, calls)(RECORD, "/version", {});
  const identity = calls[0].options.checkServerIdentity;
  assert.equal(identity(HOST, PEER), undefined);
  assert.match(String(identity("other.example.org", PEER)), /other\.example\.org/);
  assert.match(String(identity(HOST, { ...PEER, fingerprint256: "00:".repeat(31) + "00" })), /other than the pinned one/);
});

test("negative control: a request on the shared agent is caught", async () => {
  const calls = [];
  await load(planted("agent: false,\n", ""), calls)(RECORD, "/version", {});
  assert.notEqual(calls[0].options.agent, false);
});
