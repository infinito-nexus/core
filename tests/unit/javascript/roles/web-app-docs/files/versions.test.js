const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..", "..", "..",
  "roles", "web-app-docs", "files", "javascript", "versions.js",
);

const VERSIONS = [
  { name: "latest", built: true, state: "building", progress: 42, phase: "sphinx", log: [] },
  { name: "v14.0.0", built: true, state: "ready", progress: 100, phase: "", log: [] },
  { name: "v13.0.0", built: false, state: "failed", progress: 12, phase: "sphinx", log: ["a", "b"] },
  { name: "v11.6.0", built: false, state: "missing", progress: 0, phase: "", log: [] },
];

function element(tag, fields = {}) {
  return {
    tag,
    children: [],
    dataset: {},
    value: "",
    textContent: "",
    listeners: {},
    ...fields,
    append(...nodes) {
      this.children.push(...nodes);
    },
    replaceChildren(...nodes) {
      this.children = nodes;
    },
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    },
  };
}

function load(selectors = {}) {
  let ready = null;
  const window = {
    reloaded: 0,
    intervals: [],
    location: {
      href: "",
      reload() {
        window.reloaded += 1;
      },
    },
    setInterval(handler, ms) {
      window.intervals.push(ms);
    },
  };
  const document = {
    addEventListener: (type, handler) => {
      if (type === "DOMContentLoaded") {
        ready = handler;
      }
    },
    createElement: (tag) => element(tag),
    createTextNode: (text) => ({ text }),
    querySelectorAll: (selector) => selectors[selector] || [],
    querySelector: (selector) =>
      selector
        .split(",")
        .map((part) => (selectors[part.trim()] || [])[0])
        .find(Boolean) || null,
  };
  const fetch = async (url) => ({ json: async () => (url === "/api/versions" ? VERSIONS : null) });
  vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), { document, window, fetch });
  return { api: window.docsVersions, window, start: () => ready() };
}

test("urls keep the page when switching versions", () => {
  const { api } = load();
  assert.equal(api.versionUrl("v14.0.0", "docs/index"), "/v14.0.0/docs/index.html");
  assert.equal(api.versionUrl("latest"), "/latest/");
});

test("labels tell built, building and failed versions apart", () => {
  const { api } = load();
  assert.equal(api.optionLabel(VERSIONS[1]), "v14.0.0");
  assert.equal(api.optionLabel(VERSIONS[3]), "v11.6.0 (not built yet)");
  assert.equal(api.describe(VERSIONS[0]), "building: sphinx");
  assert.equal(api.describe(VERSIONS[2]), "failed: sphinx");
  assert.equal(api.describe(VERSIONS[1]), "ready");
});

test("switcher lists every version and selects the current one", () => {
  const { api } = load();
  const select = element("select", { dataset: { current: "v14.0.0", page: "roles/index" } });

  api.fillSwitcher(select, VERSIONS);

  assert.deepEqual(
    select.children.map((option) => [option.value, option.selected]),
    [
      ["/latest/roles/index.html", false],
      ["/v14.0.0/roles/index.html", true],
      ["/v13.0.0/roles/index.html", false],
      ["/v11.6.0/roles/index.html", false],
    ],
  );
});

test("overview renders one row with link, status and bar per version", () => {
  const { api } = load();
  const tbody = element("tbody");

  api.fillOverview(tbody, VERSIONS);

  const cells = tbody.children[0].children.map((cell) => cell.children[0]);
  assert.equal(tbody.children.length, 4);
  assert.equal(cells[0].href, "/latest/");
  assert.equal(cells[1].text, "building: sphinx");
  assert.equal(cells[2].value, 42);
});

test("build page shows progress and the failure log, reloads once built", () => {
  const { api, window } = load();
  const bar = element("progress");
  const phase = element("p");
  const log = element("pre");
  const parts = { progress: bar, "[data-phase]": phase, pre: log };
  const section = element("section", { dataset: { build: "v13.0.0" }, querySelector: (s) => parts[s] });

  api.followBuild(section, VERSIONS);
  assert.deepEqual([bar.value, phase.textContent, log.textContent], [12, "failed: sphinx", "a\nb"]);
  assert.equal(window.reloaded, 0);

  section.dataset.build = "v14.0.0";
  api.followBuild(section, VERSIONS);
  assert.equal(window.reloaded, 1);
});

test("start wires the switcher and polls only on overview and build pages", async () => {
  const select = element("select", { dataset: { current: "latest", page: "index" } });
  const sidebarOnly = load({ "select.docs-version-switcher": [select] });
  sidebarOnly.start();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(select.children.length, 4);
  assert.deepEqual(sidebarOnly.window.intervals, []);
  select.value = "/v14.0.0/index.html";
  select.listeners.change();
  assert.equal(sidebarOnly.window.location.href, "/v14.0.0/index.html");

  const overview = load({ "tbody[data-versions]": [element("tbody")] });
  overview.start();
  assert.deepEqual(overview.window.intervals, [2000]);
});
