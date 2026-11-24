const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { requireDotenvValue } = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dotenv.js"));
const { DOMAIN: PRIMARY_DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-moodle/files/playwright/test-2fa-enrollment.js");
const EMAIL = "#id_email";
const MOODLE_FIELD_MAXLENGTH = { [EMAIL]: 100 };
const ONION_DOMAIN = "academy.4gjse3pnau23a6n4mowi4cljpegakwbrylevgc2ymqqfx7hw3ymw2zad.onion";
const SUFFIX = "mwulxhct139577";
const ROLES = ["fresh", "existing", "administrator", "late"];

process.env.CANONICAL_DOMAIN = ONION_DOMAIN;

function expect(target, message) {
  return {
    toBeEditable: async () => undefined,
    toHaveValue: async (wanted) => assert.equal(target.value(), wanted, message),
    toHaveLength: (length) => assert.equal(target.length, length, message),
  };
}

const { createAccount } = loadInternals(
  SPEC,
  ["createAccount"],
  {
    crypto,
    "@playwright/test": { test: () => undefined, expect },
    "./timeouts": { resolveTimeout: (ms) => ms },
    "./personas": { gotoOnion: async () => undefined, recordVideoOptions: () => ({}), requireDotenvValue },
  },
  {},
);

/**
 * Returns:
 *   The page double of Moodle's new user form, cutting a filled value at the field's maxlength as the browser does,
 *   and the list of email addresses its submit button sent.
 */
function newUserForm() {
  const values = new Map();
  const submitted = [];
  const page = {
    locator: (selector) => ({
      value: () => values.get(selector) ?? "",
      fill: async (value) => values.set(selector, value.slice(0, MOODLE_FIELD_MAXLENGTH[selector] ?? value.length)),
      isVisible: async () => false,
      click: async () => submitted.push(values.get(EMAIL)),
    }),
    waitForURL: async () => undefined,
    evaluate: async () => [{ id: 7 }],
  };
  return { page, submitted };
}

/**
 * Args:
 *   domain: the DOMAIN_PRIMARY the spec reads.
 *   username: login name of the probe account.
 *
 * Returns:
 *   The pending createAccount call and the email addresses the form submitted.
 */
function create(domain, username) {
  process.env.DOMAIN_PRIMARY = domain;
  const { page, submitted } = newUserForm();
  return { created: createAccount(page, "https://academy.example", username, `2FA probe ${SUFFIX}`), submitted };
}

test("every probe account submits its whole address while the pass runs on the onion network", async () => {
  const usernames = ROLES.map((role) => `infinito-2fa-${role}-${SUFFIX}`);
  const submitted = [];
  for (const username of usernames) {
    const attempt = create(PRIMARY_DOMAIN, username);
    await attempt.created;
    submitted.push(...attempt.submitted);
  }

  assert.deepEqual(submitted, usernames.map((username) => `${username}@${PRIMARY_DOMAIN}`));
});

test("negative control: an address longer than Moodle's email field fails before the submit, naming the address", async () => {
  const attempt = create(ONION_DOMAIN, `infinito-2fa-existing-${SUFFIX}`);

  await assert.rejects(attempt.created, /the email field must hold all of infinito-2fa-existing-/);
  assert.deepEqual(attempt.submitted, []);
});
