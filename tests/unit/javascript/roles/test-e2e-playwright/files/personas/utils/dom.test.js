const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");

const loadModule = Module._load;
Module._load = function (request, ...rest) {
  return request === "@playwright/test" ? {} : loadModule.call(this, request, ...rest);
};

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { hostnameOf, LOGIN_CONTROL_NAME } = require(
  path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dom.js"),
);

Module._load = loadModule;

const FA_GLYPH = String.fromCodePoint(0xf2f6);

test("LOGIN_CONTROL_NAME matches a sign-in control behind an icon-font glyph", () => {
  for (const name of [
    "Login",
    ` ${FA_GLYPH} Login`,
    `${FA_GLYPH}Sign in`,
    "Sign in with Keycloak",
    `${FA_GLYPH} SSO`,
  ]) {
    assert.match(name, LOGIN_CONTROL_NAME);
  }
});

test("LOGIN_CONTROL_NAME ignores authenticated navigation entries", () => {
  for (const name of [
    `${FA_GLYPH} Logout`,
    "Accessories",
    "Login Enabled",
    `${FA_GLYPH} Login Enabled`,
  ]) {
    assert.doesNotMatch(name, LOGIN_CONTROL_NAME);
  }
});

test("hostnameOf rejects an IdP URL whose redirect_uri carries the app domain", () => {
  const domain = "app.example.org";
  assert.notEqual(
    hostnameOf(`https://auth.example.org/realms/r/protocol/openid-connect/auth?redirect_uri=https://${domain}/`),
    domain,
  );
  assert.notEqual(hostnameOf(`https://${domain}.evil.test/`), domain);
  assert.equal(hostnameOf(`https://${domain}/oauth2/callback?code=x`), domain);
  assert.equal(hostnameOf("http://abcdefghijklmnop.onion/"), "abcdefghijklmnop.onion");
});

test("hostnameOf returns an empty host for unparsable frame URLs", () => {
  assert.equal(hostnameOf(""), "");
  assert.equal(hostnameOf("about:blank"), "");
});
