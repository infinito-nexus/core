const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { openStore } = require(
  path.join(PROJECT_ROOT, "roles/web-app-bluesky/files/login-broker/store.js"),
);

function tempFile() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "broker-store-")), "accounts.json");
}

test("an entry survives a reopen, as after a broker restart", () => {
  const file = tempFile();
  openStore(file).set("biber", { handle: "biber.example", did: "did:plc:b", appPasswordEnc: "x" });
  const reopened = openStore(file);
  assert.deepEqual(reopened.get("biber"), {
    handle: "biber.example",
    did: "did:plc:b",
    appPasswordEnc: "x",
  });
  assert.equal(reopened.get("mapache"), null);
});

test("ownerOf names the username that holds a handle", () => {
  const store = openStore(tempFile());
  store.set("kevinveenbirkenbach", { handle: "kevin-veen.example", did: "did:plc:k", appPasswordEnc: "y" });
  assert.equal(store.ownerOf("kevin-veen.example"), "kevinveenbirkenbach");
  assert.equal(store.ownerOf("other.example"), null);
});

test("a deleted entry stays gone after a reopen", () => {
  const file = tempFile();
  const store = openStore(file);
  store.set("biber", { handle: "biber.example", did: "did:plc:b", appPasswordEnc: "x" });
  store.delete("biber");
  assert.equal(openStore(file).get("biber"), null);
  assert.equal(openStore(file).ownerOf("biber.example"), null);
});

test("the file is written owner-only", () => {
  const file = tempFile();
  openStore(file).set("biber", { handle: "biber.example", did: "did:plc:b", appPasswordEnc: "x" });
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});

test("a username named like an object key stays a plain entry", () => {
  const file = tempFile();
  openStore(file).set("__proto__", { handle: "p.example", did: "did:plc:p", appPasswordEnc: "z" });
  assert.equal(openStore(file).get("__proto__").handle, "p.example");
  assert.equal({}.handle, undefined);
});
