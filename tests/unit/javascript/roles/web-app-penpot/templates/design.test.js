const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(__dirname, "..", "..", "..", "..", "..", "..", "roles", "web-app-penpot", "templates", "design.js");

/**
 * Args:
 *   location: search and hash of the Penpot page the script runs on.
 *   bodyClass: theme class Penpot set on the body.
 *
 * Returns:
 *   The value of data-design-theme on the root element, or undefined when the script left it unset.
 */
function mirroredTheme(location, bodyClass) {
  const attributes = {};
  const document = {
    documentElement: {
      setAttribute: (name, value) => {
        attributes[name] = value;
      },
      removeAttribute: (name) => {
        delete attributes[name];
      },
    },
    body: { classList: { contains: (name) => name === bodyClass } },
    addEventListener() {},
  };
  const window = {
    location: { search: "", hash: "", ...location },
    history: { pushState() {}, replaceState() {} },
    addEventListener() {},
  };
  class MutationObserver {
    observe() {}
  }
  vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), {
    document,
    window,
    MutationObserver,
    INFINITO_DESIGN: { title: "", logo: "" },
  });
  return attributes["data-design-theme"];
}

const FAVICON = "https://cdn.example.test/roles/web-app-penpot/latest/img/design/favicon.ico";

/**
 * Args:
 *   icons: attributes of each icon link in the head of the page.
 *
 * Returns:
 *   The attributes of each icon link after the script ran with a configured logo.
 */
function brandedIcons(icons) {
  const values = icons.map((attributes) => ({ ...attributes }));
  const links = values.map((attributes) => ({
    getAttribute: (name) => (name in attributes ? attributes[name] : null),
    setAttribute: (name, value) => {
      attributes[name] = value;
    },
  }));
  const document = {
    documentElement: { setAttribute() {}, removeAttribute() {} },
    body: { classList: { contains: () => false } },
    head: {},
    querySelectorAll: (selector) => (selector === "link[rel~='icon']" ? links : []),
    addEventListener() {},
  };
  const window = {
    location: { search: "?screen=auth-login", hash: "" },
    history: { pushState() {}, replaceState() {} },
    addEventListener() {},
  };
  class MutationObserver {
    observe() {}
  }
  vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), {
    document,
    window,
    MutationObserver,
    INFINITO_DESIGN: { title: "", logo: "logo.svg", urls: { favicon_ico: FAVICON } },
  });
  return values;
}

test("a configured logo points the SVG and the PNG icon link Penpot ships at the generated favicon", () => {
  const icons = brandedIcons([
    { rel: "icon", href: "images/favicon.svg", type: "image/svg+xml" },
    { rel: "icon", href: "images/favicon.png", type: "image/png" },
  ]);
  assert.deepEqual(icons, [
    { rel: "icon", href: FAVICON, type: "image/x-icon" },
    { rel: "icon", href: FAVICON, type: "image/x-icon" },
  ]);
});

test("a query-routed auth screen of Penpot 2.19 counts as a visitor page and keeps the browser palette", () => {
  assert.equal(mirroredTheme({ search: "?screen=auth-login" }, "default"), undefined);
  assert.equal(mirroredTheme({ search: "?screen=auth-register-validate&token=t" }, "light"), undefined);
  assert.equal(mirroredTheme({ search: "?design-view=sign-in&screen=auth-recovery-request" }, "default"), undefined);
});

test("a legacy hash auth route still counts as a visitor page", () => {
  assert.equal(mirroredTheme({ hash: "#/auth/login" }, "default"), undefined);
});

test("a signed-in screen mirrors the theme Penpot picked", () => {
  assert.equal(mirroredTheme({ search: "?screen=dashboard-recent&team-id=1" }, "default"), "dark");
  assert.equal(mirroredTheme({ search: "?screen=settings-options" }, "light"), "light");
});
