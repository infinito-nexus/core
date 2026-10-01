const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..", "..", "..",
  "roles", "web-app-docs", "files", "javascript", "mermaid-init.js",
);

function run({ mermaid, dark }) {
  const context = {
    window: {
      mermaid,
      matchMedia: (query) => ({ matches: dark && query.includes("dark") }),
    },
  };
  context.window.window = context.window;
  vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), context);
  return context;
}

function recorder() {
  const calls = [];
  return { initialize: (options) => calls.push(options), calls };
}

test("it initializes mermaid once the runtime is present", () => {
  const mermaid = recorder();

  run({ mermaid, dark: false });

  assert.equal(mermaid.calls.length, 1);
  assert.equal(mermaid.calls[0].startOnLoad, true);
  assert.equal(mermaid.calls[0].securityLevel, "strict");
});

test("it follows the reader's colour scheme", () => {
  const light = recorder();
  const dark = recorder();

  run({ mermaid: light, dark: false });
  run({ mermaid: dark, dark: true });

  assert.equal(light.calls[0].theme, "default");
  assert.equal(dark.calls[0].theme, "dark");
});

test("it stays silent when the runtime failed to load", () => {
  assert.doesNotThrow(() => run({ mermaid: undefined, dark: false }));
});
