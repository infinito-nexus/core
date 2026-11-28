const crypto = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const serverScriptsEnabled = process.env.SERVER_SCRIPTS_ENABLED === "true";

const PROBE = "Infinito Bot Probe";
const PROBE_SLUG = "infinito_bot_probe";
const PROBE_TARGET = "ToDo";
const SERVER_SCRIPT = "Server Script";

const PROBES = {
  Role: ({ label }) => ({ role_name: label, desk_access: 0 }),
  DocType: ({ label }) => ({
    name: label,
    module: "Custom",
    custom: 1,
    autoname: "hash",
    fields: [{ fieldname: "note", label: "Note", fieldtype: "Data" }],
    permissions: [{ role: "System Manager", read: 1, write: 1, create: 1, delete: 1 }],
  }),
  "Custom Field": ({ label, slug }) => ({
    dt: PROBE_TARGET,
    fieldname: slug,
    label,
    fieldtype: "Data",
    insert_after: "description",
  }),
  [SERVER_SCRIPT]: ({ label, slug }) => ({
    name: label,
    script_type: "API",
    api_method: slug,
    allow_guest: 0,
    disabled: 1,
    script: 'frappe.response["message"] = "probe"',
  }),
  Webhook: ({ label, slug }) => ({
    name: label,
    webhook_doctype: PROBE_TARGET,
    webhook_docevent: "on_update",
    request_url: `https://example.invalid/${slug}`,
    request_method: "POST",
    request_structure: "Form URL-Encoded",
    webhook_data: [{ fieldname: "name", key: "name" }],
    enabled: 0,
  }),
  User: ({ slug }) => ({
    email: `${slug.replaceAll("_", "-")}@example.invalid`,
    first_name: PROBE,
    send_welcome_email: 0,
    enabled: 0,
  }),
};

const DERIVED = {
  User: (body) => ({ doctype: "Contact", filters: [["email_id", "=", body.email]] }),
};
const DERIVED_POLLS = 60;
const DERIVED_POLL_MS = 1_000;

/**
 * Args:
 *   api: the API request context of the API bot.
 *   baseUrl: the ERPNext base URL.
 *   doctype: the DocType of the probe, which Frappe may derive further records from, as a background job after the commit of its insert.
 *   body: the record the probe was created from.
 *
 * Returns:
 *   The URL of every record Frappe derived from the probe, once at least one is listed or the polls ran out; empty for a DocType that derives none.
 */
async function derivedRecords(api, baseUrl, doctype, body) {
  if (!Object.hasOwn(DERIVED, doctype)) return [];
  const derived = DERIVED[doctype](body);
  const collection = `${baseUrl}/api/resource/${encodeURIComponent(derived.doctype)}`;
  const query = `${collection}?filters=${encodeURIComponent(JSON.stringify(derived.filters))}&fields=${encodeURIComponent('["name"]')}`;
  for (let poll = 0; poll < DERIVED_POLLS; poll += 1) {
    const listed = await api.get(query, { timeout: resolveTimeout(60_000) });
    const names = listed.ok() ? (await listed.json()).data.map((row) => row.name) : [];
    if (names.length > 0) return names.map((name) => `${collection}/${encodeURIComponent(name)}`);
    await new Promise((resolve) => setTimeout(resolve, DERIVED_POLL_MS));
  }
  console.warn(`no ${derived.doctype} of the ${doctype} probe appeared, so none is torn down`);
  return [];
}

/**
 * Args:
 *   doctype: the ERPNext DocType of the probe, a key of PROBES.
 *   suffix: random hex that keeps the probe apart from every other run and from every consumer namespace.
 *
 * Returns:
 *   The body the API bot posts to /api/resource/<doctype>.
 */
function probeBody(doctype, suffix) {
  return PROBES[doctype]({ label: `${PROBE} ${suffix}`, slug: `${PROBE_SLUG}_${suffix}` });
}

/**
 * Args:
 *   api: the API request context of the API bot, which creates, reads back, deletes and reads the absence of the record.
 *   baseUrl: the ERPNext base URL.
 *   doctype: the DocType of the record.
 *   body: the record to create; a record a failed step leaves behind and every record Frappe derived from it, such as the Contact of a User, which deleting the User only unlinks, are deleted in the teardown, whose failure only warns.
 */
async function proveCreateAndDelete(api, baseUrl, doctype, body) {
  const collection = `${baseUrl}/api/resource/${encodeURIComponent(doctype)}`;
  const created = await api.post(collection, { data: body, timeout: resolveTimeout(60_000) });
  expect(created.ok(), `the API bot must create a ${doctype}: HTTP ${created.status()} ${(await created.text()).slice(0, 500)}`).toBe(true);
  const { name } = (await created.json()).data;
  const record = `${collection}/${encodeURIComponent(name)}`;
  let present = true;
  let derived = [];
  try {
    const read = await api.get(record, { timeout: resolveTimeout(60_000) });
    expect(read.status(), `the ${doctype} ${name} the API bot created must be readable`).toBe(200);
    derived = await derivedRecords(api, baseUrl, doctype, body);
    const removed = await api.delete(record, { timeout: resolveTimeout(60_000) });
    expect(removed.ok(), `the API bot must delete the ${doctype} ${name}: HTTP ${removed.status()}`).toBe(true);
    const gone = await api.get(record, { timeout: resolveTimeout(60_000) });
    expect(gone.status(), `the ${doctype} ${name} must be gone after the API bot deleted it`).toBe(404);
    present = false;
  } finally {
    const leftovers = present ? [record, ...derived] : derived;
    for (const leftover of leftovers) {
      const failure = await api.delete(leftover, { timeout: resolveTimeout(30_000) }).then(
        (response) => (response.ok() ? "" : `HTTP ${response.status()}`),
        (error) => `${error}`,
      );
      if (failure) console.warn(`teardown of ${leftover} failed: ${failure}`);
    }
  }
}

exports.register = function (shared) {
  test.describe("erpnext API bot rights", () => {
    for (const doctype of Object.keys(PROBES)) {
      test(`api bot: creates and deletes a ${doctype}`, async () => {
        test.skip(
          doctype === SERVER_SCRIPT && !serverScriptsEnabled,
          "SERVER_SCRIPTS_ENABLED=false: services.erpnext.server_scripts is off, so the deploy revokes Script Manager from the API bot",
        );
        test.setTimeout(resolveTimeout(240_000));

        const api = await shared.breakGlassApi();
        try {
          await proveCreateAndDelete(api, shared.env.erpnextBaseUrl, doctype, probeBody(doctype, crypto.randomBytes(4).toString("hex")));
        } finally {
          await api.dispose().catch(() => {});
        }
      });
    }
  });
};
