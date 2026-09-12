const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");

const loadModule = Module._load;
Module._load = function (request, ...rest) {
  return request === "@playwright/test" ? { expect: () => ({}) } : loadModule.call(this, request, ...rest);
};

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { apiFetchOnion, apiGetOnion } = require(
  path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/env.js"),
);

Module._load = loadModule;

const ONION = "http://mattermost.abcdefghijklmnop.onion/api/v4/users/me";
const CLEARNET = "https://mattermost.example.org/api/v4/users/me";

function scriptedRequest(outcomes) {
  const calls = [];
  return {
    calls,
    async fetch(url, opts) {
      calls.push({ url, method: opts.method });
      const next = outcomes.shift();
      if (next instanceof Error) throw next;
      return next;
    },
  };
}

test("an onion request survives a rejected SOCKS circuit", async () => {
  const request = scriptedRequest([
    new Error("apiRequestContext.post: Socks5 proxy rejected connection - Failure"),
    "response",
  ]);
  const response = await apiFetchOnion(request, ONION, { method: "POST" });
  assert.equal(response, "response");
  assert.deepEqual(request.calls.map((call) => call.method), ["POST", "POST"]);
});

test("a clearnet request gets exactly one attempt", async () => {
  const request = scriptedRequest([new Error("socket hang up"), "response"]);
  await assert.rejects(apiFetchOnion(request, CLEARNET, { method: "GET" }), /socket hang up/);
  assert.equal(request.calls.length, 1);
});

test("a non-transport failure is not retried over tor either", async () => {
  const request = scriptedRequest([new Error("apiRequestContext.post: Invalid URL"), "response"]);
  await assert.rejects(apiFetchOnion(request, ONION, { method: "POST" }), /Invalid URL/);
  assert.equal(request.calls.length, 1);
});

test("apiGetOnion is the GET shorthand", async () => {
  const request = scriptedRequest(["response"]);
  await apiGetOnion(request, ONION, { headers: { a: "b" } });
  assert.deepEqual(request.calls, [{ url: ONION, method: "GET" }]);
});
