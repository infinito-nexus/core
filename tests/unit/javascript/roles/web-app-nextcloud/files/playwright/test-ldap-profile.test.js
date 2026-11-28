const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-nextcloud/files/playwright/test-ldap-profile.js");
const USER_LDAP_ADDON = path.join(PROJECT_ROOT, "roles/web-app-nextcloud/meta/addons/user_ldap.yml");
const PROFILE_ATTRIBUTE_MAPPING = /configkey: "\{\{ NEXTCLOUD_LDAP_CONFIG_PREFIX \}\}ldap_attr_(\w+)"\s*\n\s*configvalue: (.*)/g;
const CURRENT_USER_URL = "https://next.example.org/ocs/v2.php/cloud/user?format=json";

const { DIRECTORY_MANAGED_FIELDS, phoneAfterPasswordLogin } = loadInternals(
  SPEC,
  ["DIRECTORY_MANAGED_FIELDS", "phoneAfterPasswordLogin"],
  {
    "@playwright/test": { test: () => undefined, expect: () => undefined },
    "./timeouts": { resolveTimeout: (ms) => ms },
    "./personas": { decodeDotenvQuotedValue: (value) => value, requireDotenvValue: (value) => value },
  },
  { URL, Buffer },
);

/**
 * Args:
 *   addonYaml: the text of the user_ldap addon definition.
 *
 * Returns:
 *   the sorted field names whose ldap_attr_<field> holds a non-empty attribute.
 */
function directoryMappedFields(addonYaml) {
  return [...addonYaml.matchAll(PROFILE_ATTRIBUTE_MAPPING)]
    .filter(([, , value]) => !["", '""', "''"].includes(value.trim()))
    .map(([, field]) => field)
    .sort();
}

/**
 * Args:
 *   status: the HTTP status every request answers with.
 *   phone: the profile phone every answer carries.
 *
 * Returns:
 *   the playwright stand-in and the contexts it opened, each with its options, requests and disposal.
 */
function recordingPlaywright(status, phone) {
  const contexts = [];
  const playwright = {
    request: {
      newContext: async (options) => {
        const context = {
          options,
          requests: [],
          disposed: false,
          get: async (url, init) => {
            context.requests.push({ url, init });
            return {
              ok: () => status < 400,
              status: () => status,
              json: async () => ({ ocs: { data: { phone } } }),
            };
          },
          dispose: async () => {
            context.disposed = true;
          },
        };
        contexts.push(context);
        return context;
      },
    },
  };
  return { playwright, contexts };
}

test("the spec treats exactly the profile fields user_ldap maps to a directory attribute as locked", () => {
  assert.deepEqual(
    [...DIRECTORY_MANAGED_FIELDS].sort(),
    directoryMappedFields(fs.readFileSync(USER_LDAP_ADDON, "utf8")),
    "user_ldap locks a profile field exactly while its ldap_attr_<field> names a directory attribute",
  );
});

test("the address the ldap_refresh hook composes is locked through the street user_ldap maps", () => {
  const address = [...fs.readFileSync(USER_LDAP_ADDON, "utf8").matchAll(PROFILE_ATTRIBUTE_MAPPING)].filter(
    ([, field]) => field === "address",
  );

  assert.ok(DIRECTORY_MANAGED_FIELDS.includes("address"), "the spec must assert the address locked");
  assert.deepEqual(
    address.map(([, , value]) => value.trim()),
    ['"{{ LDAP.USER.ATTRIBUTES.STREET }}"'],
    "an empty ldap_attr_address leaves the address editable although the hook overwrites it on its next run",
  );
});

test("every phone poll is a password login of its own, never a session a previous poll left behind", async () => {
  const { playwright, contexts } = recordingPlaywright(200, "+49301506147");

  assert.equal(await phoneAfterPasswordLogin(playwright, CURRENT_USER_URL, "YmliZXI6cHc="), "+49301506147");
  assert.equal(await phoneAfterPasswordLogin(playwright, CURRENT_USER_URL, "YmliZXI6cHc="), "+49301506147");

  assert.equal(contexts.length, 2, "each poll opens a request context without the cookies of the last one");
  for (const context of contexts) {
    assert.equal(context.disposed, true);
    assert.equal(context.options.ignoreHTTPSErrors, true);
    assert.deepEqual(context.requests.map((request) => request.url), [CURRENT_USER_URL]);
    assert.equal(context.requests[0].init.headers.Authorization, "Basic YmliZXI6cHc=");
  }
});

test("a refused password login reports its status and still closes its context", async () => {
  const { playwright, contexts } = recordingPlaywright(401, "");

  assert.equal(await phoneAfterPasswordLogin(playwright, CURRENT_USER_URL, "YmliZXI6d3Jvbmc="), "HTTP 401");
  assert.equal(contexts.length, 1);
  assert.equal(contexts[0].disposed, true);
});
