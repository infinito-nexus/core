const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..",
  "roles", "sys-front-inj-logout", "files", "javascript", "logout.js",
);

/**
 * Args:
 *   tagName: upper-case tag name.
 *   attributes: attribute name to value.
 *   text: the element's innerText.
 *
 * Returns:
 *   The fake element.
 */
function element(tagName, attributes, text) {
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

/**
 * Args:
 *   elements: every element of the page, as document.querySelectorAll('*') returns them.
 *   logoutUrl: the URL the patch points every logout control at.
 *
 * Returns:
 *   The sandbox the patch ran in; a patched click handler sets its window.location.href.
 */
function patch(elements, logoutUrl) {
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
  sandbox.initLogoutPatch(logoutUrl, false);
  return sandbox;
}

module.exports = { element, patch };
