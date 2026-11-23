const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-semaphore/files/playwright/test-provision.js");
const URL_UNDER_TEST = new URL("https://pve.example.org:8606/api2/json/version");

/**
 * Args:
 *   calls: collects `{url, options}` of every request.
 *
 * Returns:
 *   A `node:https` whose request answers 200 with an empty JSON body without a socket.
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
        callback(response);
        process.nextTick(() => {
          response.emit("data", "{}");
          response.emit("end");
        });
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
 *   `pinnedGet` of the spec.
 */
function load(file, calls) {
  return loadInternals(
    file,
    ["pinnedGet"],
    {
      "node:crypto": require("node:crypto"),
      "node:dgram": require("node:dgram"),
      "node:dns": require("node:dns"),
      "node:https": fakeHttps(calls),
      "node:net": require("node:net"),
      "node:tls": require("node:tls"),
      "@playwright/test": { test: () => {}, expect: () => ({}) },
      "./timeouts": { resolveTimeout: (ms) => ms },
    },
    { URL, Buffer },
  ).pinnedGet;
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
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "provision-plant-"));
  const file = path.join(directory, "test-provision.js");
  fs.writeFileSync(file, source.replace(old, replacement));
  return file;
}

test("pinnedGet opens a fresh TLS session that no caller option can pool", async () => {
  const calls = [];
  const answer = await load(SPEC, calls)(URL_UNDER_TEST, { ca: "PINNED", agent: "pooled" }, "Proxmox VE API");
  assert.equal(answer.status, 200);
  assert.equal(JSON.stringify(answer.json), "{}");
  const { options } = calls[0];
  assert.equal(options.agent, false, "a pooled keep-alive socket would skip the handshake that checks the pin");
  assert.equal(options.rejectUnauthorized, true);
  assert.equal(options.ca, "PINNED");
});

test("negative control: a request on the shared agent is caught", async () => {
  const calls = [];
  await load(planted("agent: false, ", ""), calls)(URL_UNDER_TEST, { ca: "PINNED" }, "Proxmox VE API");
  assert.notEqual(calls[0].options.agent, false);
});
