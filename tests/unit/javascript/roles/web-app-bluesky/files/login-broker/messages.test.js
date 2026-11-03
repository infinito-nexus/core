const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { MESSAGES, t } = require(
  path.join(PROJECT_ROOT, "roles/web-app-bluesky/files/login-broker/messages.js"),
);

test("a message without placeholders comes back verbatim, with or without vars", () => {
  assert.equal(t("handle_label"), "Handle");
  assert.equal(t("handle_submit"), "Create my account");
  assert.equal(t("handle_refused", { site: "ignored" }), "Cross-origin handle submission refused.");
});

test("every placeholder is filled and numbers are inserted as text", () => {
  assert.equal(t("label_length", { min: 3, max: 18 }), "Use 3 to 18 characters.");
  assert.equal(t("handle_title", { site: "Bluesky" }), "Choose your Bluesky handle");
  assert.equal(
    t("handle_hint", { min: 3, max: 18, prefix: "i8-" }),
    "3 to 18 lowercase letters, digits and hyphens, with at least one hyphen and none at the start or end. It must not contain i8-.",
  );
});

test("a falsy value is inserted rather than reported as missing", () => {
  assert.equal(t("label_length", { min: 0, max: "" }), "Use 0 to  characters.");
});

test("a placeholder used twice is filled at every occurrence", () => {
  MESSAGES.probe_twice = "{site} and {site}";
  try {
    assert.equal(t("probe_twice", { site: "x" }), "x and x");
  } finally {
    delete MESSAGES.probe_twice;
  }
});

test("a substituted value is not expanded a second time", () => {
  assert.equal(t("handle_title", { site: "{max}" }), "Choose your {max} handle");
});

test("an unknown key throws instead of rendering an empty text", () => {
  assert.throws(() => t("handle_missing"), { message: "Unknown message: handle_missing" });
});

test("a missing placeholder value throws and names the placeholder", () => {
  assert.throws(() => t("handle_title"), { message: "Message handle_title needs {site}" });
  assert.throws(() => t("handle_title", {}), { message: "Message handle_title needs {site}" });
  assert.throws(
    () => t("handle_hint", { min: 3, max: 18 }),
    { message: "Message handle_hint needs {prefix}" },
  );
});

test("every message renders completely once its placeholders are given", () => {
  for (const [key, text] of Object.entries(MESSAGES)) {
    const vars = Object.fromEntries([...text.matchAll(/\{(\w+)\}/g)].map(([, name]) => [name, name.toUpperCase()]));
    const rendered = t(key, vars);
    assert.ok(rendered.length > 0, key);
    assert.doesNotMatch(rendered, /\{\w+\}/, key);
  }
});
