const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..", "..", "..",
  "roles", "web-app-matomo", "files", "javascript", "javascript.js",
);

function loginPage({ search = "", readyState = "complete", withField = true } = {}) {
  const properties = {};
  const form = {
    style: {
      setProperty(name, value, priority) {
        properties[name] = { value, priority };
      },
    },
  };
  const field = { closest: (selector) => (selector === "form" ? form : null) };
  const listeners = [];
  const document = {
    readyState,
    getElementById: (id) => (withField && id === "login_form_login" ? field : null),
    addEventListener(type, handler, options) {
      listeners.push({ type, handler, options });
    },
  };
  const window = { location: { search } };

  vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), {
    document,
    window,
    URLSearchParams,
  });
  return { properties, listeners };
}

test("a loaded login page hides the native login form", () => {
  const { properties, listeners } = loginPage();

  assert.deepEqual(properties.display, { value: "none", priority: "important" });
  assert.equal(listeners.length, 0);
});

test("the local fallback keeps the native login form visible", () => {
  const { properties } = loginPage({ search: "?fallback=local" });

  assert.equal(properties.display, undefined);
});

test("another fallback value still hides the native login form", () => {
  const { properties } = loginPage({ search: "?fallback=sso" });

  assert.deepEqual(properties.display, { value: "none", priority: "important" });
});

test("a page without the login field is left untouched", () => {
  const { properties } = loginPage({ withField: false });

  assert.equal(properties.display, undefined);
});

test("a page still loading hides the form once the DOM is ready", () => {
  const { properties, listeners } = loginPage({ readyState: "loading" });

  assert.equal(properties.display, undefined);
  assert.equal(listeners.length, 1);
  assert.equal(listeners[0].type, "DOMContentLoaded");
  assert.equal(listeners[0].options.once, true);

  listeners[0].handler();

  assert.deepEqual(properties.display, { value: "none", priority: "important" });
});
