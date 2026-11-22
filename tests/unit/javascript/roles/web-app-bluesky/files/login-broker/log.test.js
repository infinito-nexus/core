const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const BROKER = path.join(PROJECT_ROOT, "roles/web-app-bluesky/files/login-broker");
const { logSafe } = require(path.join(BROKER, "log.js"));

test("a forged log line stays on the line of the entry that logs it", () => {
  assert.equal(logSafe("biber\r\n[broker] stored app-password of root"), "biber [broker] stored app-password of root");
  assert.equal(logSafe("a\nb\rc\n\n\rd"), "a b c d");
});

test("every other control character is dropped and printable text is kept", () => {
  assert.equal(logSafe("bi\x00b\x1be[31mr\x7f\tx"), "bibe[31mrx");
  assert.equal(logSafe("kevin-veen.example.test"), "kevin-veen.example.test");
  assert.equal(logSafe("Grüße ✓"), "Grüße ✓");
});

test("a non-string value is logged as its string form", () => {
  assert.equal(logSafe(undefined), "undefined");
  assert.equal(logSafe(42), "42");
});

test("the strip pattern names \\n literally, the replace CodeQL js/log-injection counts as a sanitizer", () => {
  assert.match(logSafe.toString(), /\.replace\(\/\[[^\]]*\\n[^\]]*\]\/g, ""\)/);
});

test("the broker image ships log.js next to server.js", () => {
  assert.match(fs.readFileSync(path.join(BROKER, "Dockerfile"), "utf8"), /^COPY .*\bserver\.js\b.*\blog\.js\b.* \.\/$/m);
});
