const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..", "..", "..",
  "roles", "web-app-worldmonitor", "files", "javascript", "javascript.js",
);
const PATCH = fs.readFileSync(SOURCE, "utf8");
const ORIGIN = "https://worldmonitor.example";

function load(source) {
  const sent = [];
  const window = {
    location: { href: `${ORIGIN}/`, origin: ORIGIN },
    URL,
    Request,
    fetch: (input, init) => {
      sent.push({ input, init });
      return Promise.resolve({ ok: true });
    },
  };
  vm.runInNewContext(source, { window });
  return { window, sent };
}

function credentialsOnTheWire({ input, init }) {
  if (init && init.credentials !== undefined) return init.credentials;
  return input instanceof Request ? input.credentials : undefined;
}

function upstreamPublicReads() {
  return [
    ["/api/bootstrap?tier=fast&public=1", { signal: new AbortController().signal, credentials: "omit" }],
    ["/api/product-catalog", { credentials: "omit", signal: new AbortController().signal }],
    [`${ORIGIN}/api/gpsjam`, { credentials: "omit" }],
    [new URL("/api/oref-alerts", ORIGIN), { credentials: "omit" }],
  ];
}

test("the public reads the pinned client sends without cookies reach the own API with the gate session", () => {
  const { window, sent } = load(PATCH);

  for (const [input, init] of upstreamPublicReads()) {
    window.fetch(input, init);
    const wire = sent.at(-1);
    assert.equal(credentialsOnTheWire(wire), "same-origin", String(input));
    assert.equal(wire.input, input);
    assert.equal(wire.init.signal, init.signal);
    assert.equal(init.credentials, "omit", "the caller's init must stay untouched");
  }
});

test("a Request object that omits credentials for the own API is upgraded too", () => {
  const { window, sent } = load(PATCH);
  const request = new Request(`${ORIGIN}/api/news/v1/list-feed-digest?variant=full&lang=en&public=1`, {
    credentials: "omit",
  });

  window.fetch(request);

  assert.equal(sent[0].input, request);
  assert.equal(credentialsOnTheWire(sent[0]), "same-origin");
});

test("the session interceptor the client installs later still sees the omit it keys its public-read bypass on", () => {
  const { window, sent } = load(PATCH);
  const inner = window.fetch;
  const seen = [];
  window.fetch = (input, init) => {
    seen.push(init.credentials);
    return inner(input, init);
  };

  window.fetch("/api/bootstrap?tier=slow&public=1", { credentials: "omit" });

  assert.deepEqual(seen, ["omit"]);
  assert.equal(credentialsOnTheWire(sent[0]), "same-origin");
});

test("every request outside the own API or with a credentials mode of its own passes through unchanged", () => {
  const { window, sent } = load(PATCH);
  const untouched = [
    ["https://nominatim.openstreetmap.org/reverse?lat=0&lon=0", { credentials: "omit" }],
    ["https://worldmonitor.example.evil.test/api/bootstrap?tier=fast&public=1", { credentials: "omit" }],
    ["/assets/analysis.worker.js", { credentials: "omit" }],
    ["/api-docs/index.html", { credentials: "omit" }],
    ["/api/bootstrap?keys=insights", { signal: new AbortController().signal }],
    ["/api/wm-session", { credentials: "include" }],
  ];

  for (const [input, init] of untouched) {
    window.fetch(input, init);
    const wire = sent.at(-1);
    assert.equal(wire.input, input);
    assert.equal(wire.init, init, input);
  }
  window.fetch(`${ORIGIN}/api/gpsjam`);
  assert.equal(sent.at(-1).init, undefined);
});

test("without the patch the same public reads leave the browser without the gate session", () => {
  const { window, sent } = load("");

  for (const [input, init] of upstreamPublicReads()) {
    window.fetch(input, init);
    assert.equal(credentialsOnTheWire(sent.at(-1)), "omit", String(input));
  }
});
