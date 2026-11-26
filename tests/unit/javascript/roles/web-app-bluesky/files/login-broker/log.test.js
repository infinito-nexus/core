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

test("the strip pattern names \\n literally, the replace CodeQL js/log-injection counts as a sanitizer", () => { // nocheck: test.text-presence -- CodeQL reads the source text, its sanitizer match on this replace shape is the contract
  assert.match(logSafe.toString(), /\.replace\(\/\[[^\]]*\\n[^\]]*\]\/g, ""\)/);
});

/**
 * Returns:
 *   Every broker file server.js loads, itself and its local requires followed transitively.
 */
function loadedModules() {
  const seen = new Set();
  const pending = ["server.js"];
  while (pending.length > 0) {
    const file = pending.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    const source = fs.readFileSync(path.join(BROKER, file), "utf8");
    for (const [, name] of source.matchAll(/require\(\s*["']\.\/([^"']+)["']\s*\)/g)) {
      pending.push(name.endsWith(".js") ? name : `${name}.js`);
    }
  }
  return seen;
}

/**
 * Returns:
 *   The sources and the destination of every COPY instruction of the broker Dockerfile.
 */
function copyInstructions() {
  return fs
    .readFileSync(path.join(BROKER, "Dockerfile"), "utf8")
    .split("\n")
    .filter((line) => /^COPY\s/.test(line))
    .map((line) => {
      const args = line.trim().split(/\s+/).slice(1);
      return { sources: args.slice(0, -1), destination: args.at(-1) };
    });
}

test("the broker image ships every module server.js loads next to it", () => {
  const copy = copyInstructions().find(({ sources }) => sources.includes("server.js"));
  assert.ok(copy, "no COPY instruction ships server.js");
  assert.equal(copy.destination, "./");
  for (const file of loadedModules()) {
    assert.ok(copy.sources.includes(file), `server.js loads ${file}, which the image does not ship`);
  }
});
