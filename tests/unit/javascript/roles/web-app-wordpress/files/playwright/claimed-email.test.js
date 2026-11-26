const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const PLAYWRIGHT_DIR = path.join(PROJECT_ROOT, "roles/web-app-wordpress/files/playwright");
const { claimedEmail } = require(path.join(PLAYWRIGHT_DIR, "claimed-email.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));

const MAILBOX = `biber@${DOMAIN}`;
const MAILBOX_LAYOUT_USER = {
  username: "biber",
  emailVerified: true,
  attributes: { mailbox: [MAILBOX], LDAP_ID: ["biber"] },
};
const SECONDARY = "harry.beaver@example.org";

test("the mailbox policy claims the mailbox for a user whose Keycloak email is unset", () => {
  assert.equal(claimedEmail(MAILBOX_LAYOUT_USER, true, MAILBOX), MAILBOX);
});

test("the mailbox policy claims the mailbox, never the secondary address Keycloak keeps as email", () => {
  assert.equal(claimedEmail({ ...MAILBOX_LAYOUT_USER, email: SECONDARY }, true, MAILBOX), MAILBOX);
});

test("the external policy claims the Keycloak email", () => {
  assert.equal(claimedEmail({ ...MAILBOX_LAYOUT_USER, email: SECONDARY }, false, MAILBOX), SECONDARY);
});

test("negative control: a policy-blind Keycloak email read fails on the mailbox layout user", () => {
  assert.throws(
    () => claimedEmail(MAILBOX_LAYOUT_USER, false, MAILBOX),
    /Keycloak user "biber" carries no email claim under the external policy/,
  );
});

test("an empty mailbox under the mailbox policy fails loudly", () => {
  assert.throws(
    () => claimedEmail(MAILBOX_LAYOUT_USER, true, ""),
    /Keycloak user "biber" carries no email claim under the mailbox policy/,
  );
});
