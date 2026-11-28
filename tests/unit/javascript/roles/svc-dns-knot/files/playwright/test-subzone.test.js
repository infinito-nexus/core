const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const dotenv = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dotenv.js"));

process.env.KNOT_ZONE = '"ws.example.test."';
process.env.KNOT_SERVERS = '"172.30.0.10:53"';

const internals = loadInternals(
  path.join(PROJECT_ROOT, "roles/svc-dns-knot/files/playwright/test-subzone.js"),
  ["knotServers", "servers", "zone"],
  { "./personas": dotenv },
  {},
);

/**
 * Args:
 *   raw: the KNOT_SERVERS value to parse.
 *
 * Returns:
 *   The parsed servers rebuilt in this realm; strict deep equality compares
 *   prototypes, and the spec's arrays come from the vm context's own Array.
 */
function serversOf(raw) {
  return structuredClone(internals.knotServers(raw));
}

test("the dotenv-quoted server list the container receives yields a numeric port", () => {
  assert.deepEqual(structuredClone(internals.servers), [{ host: "172.30.0.10", port: 53 }]);
});

test("the dotenv-quoted zone loses its quotes and its trailing dot", () => {
  assert.equal(internals.zone, "ws.example.test");
});

test("every comma-separated entry becomes one server", () => {
  assert.deepEqual(serversOf('"10.0.0.1:53,10.0.0.2:5353"'), [
    { host: "10.0.0.1", port: 53 },
    { host: "10.0.0.2", port: 5353 },
  ]);
});

test("an IPv6 address keeps its colons in the host", () => {
  assert.deepEqual(serversOf('"fd00::10:53"'), [{ host: "fd00::10", port: 53 }]);
});

test("an unquoted value is read as it is", () => {
  assert.deepEqual(serversOf("172.30.0.10:53"), [{ host: "172.30.0.10", port: 53 }]);
});

test("an empty value yields no server", () => {
  assert.deepEqual(serversOf(undefined), []);
});
