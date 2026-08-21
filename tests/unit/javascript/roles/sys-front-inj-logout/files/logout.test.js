const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..", "..", "..",
  "roles", "sys-front-inj-logout", "files", "javascript", "logout.js",
);

const LOGOUT_URL = "https://logout.example.org/";

function element(tagName, attributes = {}, text = "") {
  const el = {
    tagName,
    dataset: {},
    style: {},
    listeners: [],
    innerText: text,
    attributes: [],
    getAttribute(name) {
      const found = el.attributes.find((a) => a.name === name);
      return found ? found.value : null;
    },
    setAttribute(name, value) {
      const found = el.attributes.find((a) => a.name === name);
      if (found) {
        found.value = value;
        return;
      }
      el.attributes.push({ name, value });
    },
    hasAttribute(name) {
      return el.attributes.some((a) => a.name === name);
    },
    addEventListener(type, handler, options) {
      el.listeners.push({ type, handler, options });
    },
    querySelectorAll() {
      return [];
    },
  };

  for (const [name, value] of Object.entries(attributes)) {
    el.setAttribute(name, value);
  }
  el.id = el.getAttribute("id") || "";
  el.className = el.getAttribute("class") || "";
  return el;
}

function patch(elements) {
  const sandbox = {
    console: { debug() {} },
    location: { href: "" },
    Element: class Element {},
    MutationObserver: class MutationObserver {
      observe() {}
    },
    document: {
      body: {},
      querySelectorAll: () => elements,
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox);
  sandbox.initLogoutPatch(LOGOUT_URL, false);
  return sandbox;
}

test("an anchor whose text reads 'Log out' is redirected", () => {
  const link = element("A", { href: "/account/exit" }, "Log out");
  patch([link]);

  assert.equal(link.getAttribute("href"), LOGOUT_URL);
  assert.equal(link.dataset._logoutHandled, "true");
  assert.equal(link.listeners.length, 1);
  assert.equal(link.listeners[0].options.capture, true);
});

test("a click on a patched element is intercepted, not followed", () => {
  const link = element("A", { id: "logout-link" }, "Bye");
  const sandbox = patch([link]);

  let prevented = false;
  link.listeners[0].handler({ preventDefault: () => { prevented = true; } });

  assert.equal(prevented, true);
  assert.equal(sandbox.window.location.href, LOGOUT_URL);
});

test("an href pointing at /logout is NOT enough to match", () => {
  const link = element("A", { href: "/logout" }, "My profile");
  patch([link]);

  assert.equal(link.getAttribute("href"), "/logout");
  assert.equal(link.dataset._logoutHandled, undefined);
});

test("a non-interactive tag is never patched, whatever it says", () => {
  const div = element("DIV", { id: "logout" }, "Log out");
  patch([div]);

  assert.equal(div.dataset._logoutHandled, undefined);
  assert.equal(div.listeners.length, 0);
});

test("a button carrying formaction has that formaction rewritten", () => {
  const button = element("BUTTON", { formaction: "/session/end", title: "Logout" });
  patch([button]);

  assert.equal(button.getAttribute("formaction"), LOGOUT_URL);
});

test("a data-* attribute value only counts on data-/aria- names", () => {
  const matched = element("BUTTON", { "data-action": "logout" }, "");
  const ignored = element("BUTTON", { "value": "logout" }, "");
  patch([matched, ignored]);

  assert.equal(matched.dataset._logoutHandled, "true");
  assert.equal(ignored.dataset._logoutHandled, undefined);
});

test("an element already handled is not bound a second time", () => {
  const link = element("A", { id: "logout" }, "");
  const sandbox = patch([link]);
  sandbox.initLogoutPatch(LOGOUT_URL, false);

  assert.equal(link.listeners.length, 1);
});

test("a text block over 1000 characters is ignored as a match source", () => {
  const link = element("A", {}, `${"x".repeat(1000)} log out`);
  patch([link]);

  assert.equal(link.dataset._logoutHandled, undefined);
});
