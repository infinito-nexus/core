const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { MESSAGES, t } = require(path.join(PROJECT_ROOT, "roles/web-app-bluesky/files/login-broker/messages.js"));

test("t fills every placeholder of a message", () => {
  assert.equal(t("label_length", { min: 3, max: 18 }), "Use 3 to 18 characters.");
});

test("t returns a message without placeholders unchanged", () => {
  assert.equal(t("handle_label"), MESSAGES.handle_label);
});

test("t refuses an unknown key", () => {
  assert.throws(() => t("no_such_message"), /Unknown message: no_such_message/);
});

test("t refuses a message whose placeholder has no value", () => {
  assert.throws(() => t("handle_title", {}), /handle_title needs \{site\}/);
});

test("every message is a non-empty string", () => {
  for (const [key, text] of Object.entries(MESSAGES)) {
    assert.equal(typeof text, "string", key);
    assert.ok(text.length > 0, key);
  }
});
