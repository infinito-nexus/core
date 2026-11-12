const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const { hostnameOf } = loadInternals(
  path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dom.js"),
  ["hostnameOf"],
  {},
  { URL },
);
const { proxyRefusal, failedTransport } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-worldmonitor/files/playwright/test-live-updates.js"),
  ["proxyRefusal", "failedTransport"],
  { "./personas": { hostnameOf } },
  { URL },
);
const HOST = "worldmonitor.example.org";

test("a redirect into the oauth2 gate or Keycloak is a refusal, any other redirect is not", () => {
  assert.equal(proxyRefusal(302, { location: "/oauth2/start?rd=%2Fapi%2Fnews" }), true);
  assert.equal(
    proxyRefusal(302, { location: "https://auth.example.org/realms/main/protocol/openid-connect/auth?client_id=x" }),
    true,
  );
  assert.equal(proxyRefusal(301, { location: "/api/news/" }), false);
  assert.equal(proxyRefusal(302, {}), false);
});

test("an HTML error page comes from the proxy, a JSON error is the app's own answer", () => {
  assert.equal(proxyRefusal(502, { "content-type": "text/html" }), true);
  assert.equal(proxyRefusal(401, { "content-type": "text/html; charset=utf-8" }), true);
  assert.equal(proxyRefusal(502, { "content-type": "application/json" }), false);
  assert.equal(proxyRefusal(503, {}), false);
  assert.equal(proxyRefusal(200, { "content-type": "text/html" }), false);
});

test("a transport failure counts on the canonical host only and never for an abort", () => {
  assert.equal(
    failedTransport("Failed to load resource: net::ERR_CONNECTION_REFUSED", `https://${HOST}/api/news`, HOST),
    true,
  );
  assert.equal(failedTransport("Failed to load resource: net::ERR_ABORTED", `https://${HOST}/api/news`, HOST), false);
  assert.equal(
    failedTransport("Failed to load resource: net::ERR_NAME_NOT_RESOLVED", "https://tiles.example.net/a.pbf", HOST),
    false,
  );
  assert.equal(
    failedTransport("Failed to load resource: the server responded with a status of 503 ()", `https://${HOST}/api/news`, HOST),
    false,
  );
});

test("a failed WebSocket counts by the socket's host, not by the script that opened it", () => {
  assert.equal(
    failedTransport(
      `WebSocket connection to 'wss://${HOST}/relay' failed: Unexpected response code: 502`,
      "https://cdn.example.net/app.js",
      HOST,
    ),
    true,
  );
  assert.equal(
    failedTransport("WebSocket connection to 'wss://relay.example.net/ws' failed", `https://${HOST}/assets/app.js`, HOST),
    false,
  );
});
