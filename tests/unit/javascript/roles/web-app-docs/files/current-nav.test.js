const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..", "..", "..",
  "roles", "web-app-docs", "files", "javascript", "current-nav.js",
);

function node(tag, parent = null, href = null) {
  const classes = new Set();
  const el = {
    tag,
    parentElement: parent,
    style: { display: "" },
    children: [],
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
    getAttribute: (name) => (name === "href" ? href : null),
    closest(selector) {
      let current = el;
      while (current && current.tag !== selector) {
        current = current.parentElement;
      }
      return current;
    },
    querySelectorAll: () => el.children,
  };
  return el;
}

function page(hash, hrefs, alreadyCurrent = []) {
  const outer = node("li", node("ul"));
  const submenu = node("div", outer);
  outer.children.push(submenu);
  const inner = node("li", node("ul", outer));
  const links = hrefs.map((href) => node("a", inner, href));
  alreadyCurrent.forEach((index) => links[index].classList.add("current"));
  const items = [outer, inner];

  let ready = null;
  const document = {
    addEventListener: (type, handler) => {
      if (type === "DOMContentLoaded") {
        ready = handler;
      }
    },
    querySelectorAll(selector) {
      if (selector === ".current-index a.reference.internal") {
        return links;
      }
      if (selector === ".current-index a.reference.internal.current") {
        return links.filter((link) => link.classList.contains("current"));
      }
      if (selector === ".current-index li.current") {
        return items.filter((item) => item.classList.contains("current"));
      }
      return [];
    },
  };
  const window = { location: { hash }, addEventListener() {} };

  vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), { document, window });
  ready();
  window.initCurrentNav();
  return { outer, inner, submenu, links };
}

test("a hash-only link matching the location hash becomes the only current link", () => {
  const { outer, inner, submenu, links } = page("#setup", ["#other", "#setup"], [0]);

  assert.equal(links[1].classList.contains("current"), true);
  assert.equal(links[0].classList.contains("current"), false);
  assert.equal(inner.classList.contains("current"), true);
  assert.equal(outer.classList.contains("current"), true);
  assert.equal(submenu.style.display, "block");
});

test("a page link carrying the location hash marks its list items current", () => {
  const { outer, inner, links } = page("#setup", ["guide.html#setup"]);

  assert.equal(inner.classList.contains("current"), true);
  assert.equal(outer.classList.contains("current"), true);
  assert.equal(links[0].classList.contains("current"), false);
});

test("without a location hash nothing is marked", () => {
  const { outer, inner, submenu } = page("", ["#setup"]);

  assert.equal(inner.classList.contains("current"), false);
  assert.equal(outer.classList.contains("current"), false);
  assert.equal(submenu.style.display, "");
});
