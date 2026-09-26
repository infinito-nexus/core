const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..", "..", "..",
  "roles", "web-app-docs", "files", "javascript", "languages.js",
);

const LANGUAGES = [
  { code: "en", native: "English" },
  { code: "de", native: "Deutsch" },
  { code: "ar", native: "العربية" },
];

function select(dataset) {
  return {
    dataset,
    children: [],
    value: "",
    listeners: {},
    replaceChildren(...nodes) {
      this.children = nodes;
    },
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    },
  };
}

async function load(dataset, answer = { ok: true, body: { languages: LANGUAGES } }) {
  let ready = null;
  const requested = [];
  const switcher = select(dataset);
  const window = { location: { href: "" } };
  const document = {
    addEventListener: (type, handler) => {
      if (type === "DOMContentLoaded") {
        ready = handler;
      }
    },
    createElement: () => ({}),
    querySelectorAll: (selector) => (selector === ".docs-language-switcher" ? [switcher] : []),
  };
  const fetch = async (url) => {
    requested.push(url);
    return { ok: answer.ok, json: async () => answer.body };
  };
  vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), { document, window, fetch });
  ready();
  await new Promise((resolve) => setImmediate(resolve));
  return { switcher, window, requested };
}

test("the switcher lists every built language and keeps the page", async () => {
  const { switcher, requested } = await load({ version: "deployed", language: "de", page: "docs/index" });

  assert.deepEqual(requested, ["/api/languages/deployed"]);
  assert.deepEqual(
    switcher.children.map((option) => [option.textContent, option.value, option.selected]),
    [
      ["English", "/deployed/docs/index.html", false],
      ["Deutsch", "/deployed/de/docs/index.html", true],
      ["العربية", "/deployed/ar/docs/index.html", false],
    ],
  );
});

test("choosing a language navigates to the same page in it", async () => {
  const { switcher, window } = await load({ version: "v14.1.0", language: "en", page: "index" });

  switcher.value = switcher.children[1].value;
  switcher.listeners.change();

  assert.equal(window.location.href, "/v14.1.0/de/index.html");
});

test("a failed request leaves the rendered placeholder in place", async () => {
  const { switcher } = await load({ version: "latest", language: "en", page: "index" }, { ok: false, body: null });

  assert.deepEqual(switcher.children, []);
  assert.equal(switcher.listeners.change, undefined);
});
