const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");

const playwrightStub = { expect: () => ({ toBe() {} }) };
const loadModule = Module._load;
Module._load = function (request, ...rest) {
  return request === "@playwright/test" ? playwrightStub : loadModule.call(this, request, ...rest);
};

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { isOidcCodeExchange } = require(
  path.join(PROJECT_ROOT, "roles/web-app-espocrm/files/playwright/_shared.js"),
);

Module._load = loadModule;

function fakeResponse(url, credentials) {
  const headers =
    credentials === undefined ? {} : { "espo-authorization": Buffer.from(credentials, "utf8").toString("base64") };
  return { url: () => url, request: () => ({ headers: () => headers }) };
}

const APP_USER = "http://espocrm.example.onion/api/v1/App/user";

test("matches the App/user call that exchanges the OIDC code", () => {
  assert.equal(isOidcCodeExchange(fakeResponse(APP_USER, "**oidc:7f3c2e")), true);
});

test("ignores the App/user revalidation of a token left in localStorage", () => {
  assert.equal(isOidcCodeExchange(fakeResponse(`${APP_USER}?`, "biber:0d9b4a51")), false);
});

test("ignores the cleared basic credentials of the client logout", () => {
  assert.equal(isOidcCodeExchange(fakeResponse(APP_USER, "**logout:logout")), false);
});

test("ignores App/user calls without EspoCRM credentials", () => {
  assert.equal(isOidcCodeExchange(fakeResponse(APP_USER)), false);
});

test("ignores OIDC credentials sent to another route", () => {
  assert.equal(
    isOidcCodeExchange(fakeResponse("http://espocrm.example.onion/api/v1/Oidc/authorizationData", "**oidc:7f3c2e")),
    false,
  );
});
