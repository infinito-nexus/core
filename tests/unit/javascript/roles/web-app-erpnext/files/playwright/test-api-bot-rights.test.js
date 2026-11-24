const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "https://erp.example.org";
const SUFFIX = "0a1b2c3d";
const KINDS = ["Role", "DocType", "Custom Field", "Server Script", "Webhook", "User"];
const CONTACT = `${BASE}/api/resource/Contact/Infinito%20Bot%20Probe`;
const warnings = [];

const { DERIVED, DERIVED_POLLS, PROBES, probeBody, proveCreateAndDelete } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-erpnext/files/playwright/test-api-bot-rights.js"),
  ["DERIVED", "DERIVED_POLLS", "PROBES", "probeBody", "proveCreateAndDelete"],
  {
    "@playwright/test": {
      test: () => undefined,
      expect: (actual, message) => ({ toBe: (expected) => assert.equal(actual, expected, message) }),
    },
    "./timeouts": { resolveTimeout: (value) => value },
  },
  { URL, console: { warn: (line) => warnings.push(line) }, setTimeout: (resolve) => resolve() },
);

/**
 * Args:
 *   doctype: the DocType of the posted record.
 *   body: the posted record.
 *
 * Returns:
 *   The name Frappe gives the record: the Custom Field joins its DocType and field name, a Role takes its role_name, a User its email, every other probe, the prompt-named Webhook included, its name.
 */
function frappeName(doctype, body) {
  if (doctype === "Custom Field") return `${body.dt}-${body.fieldname}`;
  return body.name || body.role_name || body.email;
}

function reply(status, payload) {
  return {
    ok: () => status >= 200 && status < 300,
    status: () => status,
    text: async () => JSON.stringify(payload),
    json: async () => payload,
  };
}

/**
 * Args:
 *   site.refuse: the requests the site answers with 403, as "<METHOD> <DocType>".
 *   site.keepOnDelete: true for a site that answers a delete with 202 and keeps the record.
 *   site.contactPolls: the Contact list queries answered empty before the background job of a new User has inserted its Contact; Infinity for a job that never runs.
 *   site.nameOf: the name the site gives a posted record, from its DocType and body.
 *
 * Returns:
 *   A stand-in of the API bot's request context on a Frappe site, with its stored records, the requests it saw and the queries left before a pending Contact appears. Deleting a User clears the user of its Contact and keeps the Contact, as User.on_trash does.
 */
function fakeSite(site) {
  const records = new Map();
  const calls = [];
  const pending = [];
  let emptyPolls = site.contactPolls;
  const target = (url) => {
    const [resource, query] = url.slice(`${BASE}/api/resource/`.length).split("?");
    return { parts: decodeURIComponent(resource).split("/"), query: new URLSearchParams(query || "") };
  };
  const refused = (method, doctype) => site.refuse.includes(`${method} ${doctype}`);
  const runJobs = () => {
    if (emptyPolls > 0) return;
    for (const contact of pending.splice(0)) records.set(`Contact/${contact.first_name}`, contact);
  };
  return {
    records,
    calls,
    post: async (url, { data }) => {
      const [doctype] = target(url).parts;
      calls.push(`POST ${doctype}`);
      if (refused("POST", doctype)) return reply(403, { exc_type: "PermissionError" });
      const name = site.nameOf(doctype, data);
      records.set(`${doctype}/${name}`, data);
      if (doctype === "User") pending.push({ first_name: data.first_name, email_id: data.email, user: name });
      return reply(200, { data: { ...data, name } });
    },
    get: async (url) => {
      const { parts, query } = target(url);
      const [doctype, name] = parts;
      runJobs();
      if (name === undefined) {
        calls.push(`LIST ${doctype}`);
        if (emptyPolls > 0) {
          emptyPolls -= 1;
          return reply(200, { data: [] });
        }
        runJobs();
        const [[field, , value]] = JSON.parse(query.get("filters"));
        const rows = [...records.entries()].filter(([key, row]) => key.startsWith(`${doctype}/`) && row[field] === value);
        return reply(200, { data: rows.map(([key]) => ({ name: key.slice(doctype.length + 1) })) });
      }
      calls.push(`GET ${doctype}`);
      return records.has(`${doctype}/${name}`) ? reply(200, { data: records.get(`${doctype}/${name}`) }) : reply(404, {});
    },
    delete: async (url) => {
      const [doctype, name] = target(url).parts;
      runJobs();
      calls.push(`DELETE ${doctype}`);
      if (refused("DELETE", doctype)) return reply(403, { exc_type: "PermissionError" });
      if (site.keepOnDelete) return reply(202, { data: "ok" });
      records.delete(`${doctype}/${name}`);
      for (const [key, row] of records) {
        if (doctype === "User" && key.startsWith("Contact/") && row.user === name) records.set(key, { ...row, user: null });
      }
      return reply(202, { data: "ok" });
    },
  };
}

function prove(site, doctype) {
  return proveCreateAndDelete(site, BASE, doctype, probeBody(doctype, SUFFIX));
}

test.beforeEach(() => {
  warnings.length = 0;
});

test("the probes cover every structure the API bot must manage", () => {
  assert.deepEqual(Object.keys(PROBES), KINDS);
});

test("every probe carries the run's suffix in the field Frappe names it by", () => {
  for (const doctype of KINDS) {
    assert.match(frappeName(doctype, probeBody(doctype, SUFFIX)), new RegExp(SUFFIX), doctype);
  }
});

test("every structure is read back, deleted and gone, and the User's Contact goes with its User", async () => {
  const site = fakeSite({ refuse: [], keepOnDelete: false, contactPolls: 1, nameOf: frappeName });
  for (const doctype of KINDS) {
    await prove(site, doctype);
  }
  assert.equal(site.records.size, 0);
  assert.deepEqual(warnings, []);
  assert.deepEqual(
    site.calls,
    KINDS.flatMap((doctype) =>
      doctype === "User"
        ? ["POST User", "GET User", "LIST Contact", "LIST Contact", "DELETE User", "GET User", "DELETE Contact"]
        : [`POST ${doctype}`, `GET ${doctype}`, `DELETE ${doctype}`, `GET ${doctype}`],
    ),
  );
});

test("without the Contact teardown the deleted User leaves its Contact behind, unlinked", async () => {
  const site = fakeSite({ refuse: [], keepOnDelete: false, contactPolls: 0, nameOf: frappeName });
  const derive = DERIVED.User;
  delete DERIVED.User;
  try {
    await prove(site, "User");
  } finally {
    DERIVED.User = derive;
  }
  assert.deepEqual([...site.records.keys()], ["Contact/Infinito Bot Probe"]);
  assert.equal(site.records.get("Contact/Infinito Bot Probe").user, null);
});

test("a Contact the background job never inserts is waited for a bounded time, warned about and not torn down", async () => {
  const site = fakeSite({ refuse: [], keepOnDelete: false, contactPolls: Infinity, nameOf: frappeName });
  await prove(site, "User");
  assert.equal(site.calls.filter((call) => call === "LIST Contact").length, DERIVED_POLLS);
  assert.equal(site.calls.includes("DELETE Contact"), false);
  assert.deepEqual(warnings, ["no Contact of the User probe appeared, so none is torn down"]);
});

test("a Contact delete the site refuses only warns and keeps the User check green", async () => {
  const site = fakeSite({ refuse: ["DELETE Contact"], keepOnDelete: false, contactPolls: 0, nameOf: frappeName });
  await prove(site, "User");
  assert.deepEqual(warnings, [`teardown of ${CONTACT} failed: HTTP 403`]);
  assert.deepEqual([...site.records.keys()], ["Contact/Infinito Bot Probe"]);
});

test("a record the site names apart from its posted name is deleted by the name the site returned", async () => {
  let serial = 0;
  const site = fakeSite({
    refuse: [],
    keepOnDelete: false,
    contactPolls: 0,
    nameOf: () => {
      serial += 1;
      return `hash${serial}`;
    },
  });
  await prove(site, "Webhook");
  assert.equal(site.records.size, 0);
  assert.deepEqual(site.calls, ["POST Webhook", "GET Webhook", "DELETE Webhook", "GET Webhook"]);
});

test("a create the site refuses fails the check and leaves nothing to tear down", async () => {
  const site = fakeSite({ refuse: ["POST Server Script"], keepOnDelete: false, contactPolls: 0, nameOf: frappeName });
  await assert.rejects(prove(site, "Server Script"), /the API bot must create a Server Script: HTTP 403/);
  assert.deepEqual(site.calls, ["POST Server Script"]);
});

test("a delete the site refuses fails the check and the teardown deletes again, warning", async () => {
  const site = fakeSite({ refuse: ["DELETE DocType"], keepOnDelete: false, contactPolls: 0, nameOf: frappeName });
  await assert.rejects(prove(site, "DocType"), /the API bot must delete the DocType Infinito Bot Probe 0a1b2c3d: HTTP 403/);
  assert.deepEqual(site.calls, ["POST DocType", "GET DocType", "DELETE DocType", "DELETE DocType"]);
  assert.deepEqual(warnings, [`teardown of ${BASE}/api/resource/DocType/Infinito%20Bot%20Probe%200a1b2c3d failed: HTTP 403`]);
});

test("a record still readable after its delete fails the check", async () => {
  const site = fakeSite({ refuse: [], keepOnDelete: true, contactPolls: 0, nameOf: frappeName });
  await assert.rejects(prove(site, "Webhook"), /the Webhook Infinito Bot Probe 0a1b2c3d must be gone after the API bot deleted it/);
  assert.deepEqual(site.calls, ["POST Webhook", "GET Webhook", "DELETE Webhook", "GET Webhook", "DELETE Webhook"]);
});
