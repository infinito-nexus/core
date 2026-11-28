const test = require("node:test");
const assert = require("node:assert/strict");

const { element, patch: patchPage } = require("../../../utils/logout-patch.js");

const LOGOUT_URL = "https://logout.example.org/";

function patch(elements, logoutUrl = LOGOUT_URL) {
  return patchPage(elements, logoutUrl);
}

const KEYCLOAK_LOGOUT_URL = "https://auth.example.org/realms/example.org/protocol/openid-connect/logout";

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

test("the dashboard's Log out on this device stays on the Keycloak confirmation page", () => {
  const item = element("A", { href: KEYCLOAK_LOGOUT_URL, target: "_top" }, "Log out on this device");
  const sandbox = patch([item], KEYCLOAK_LOGOUT_URL);

  assert.equal(item.getAttribute("href"), KEYCLOAK_LOGOUT_URL);
  item.listeners[0].handler({ preventDefault() {} });
  assert.equal(sandbox.window.location.href, KEYCLOAK_LOGOUT_URL);
  assert.doesNotMatch(sandbox.window.location.href, /id_token_hint/);
});

test("on another network the item reaches the confirmation page through that network's conductor", () => {
  const aligned = `${KEYCLOAK_LOGOUT_URL}?client_id=example.org&post_logout_redirect_uri=http%3A%2F%2Flogout.onion%2F`;
  const item = element("A", { href: KEYCLOAK_LOGOUT_URL, target: "_top" }, "Log out on this device");
  const sandbox = patch([item], aligned);

  item.listeners[0].handler({ preventDefault() {} });
  const landed = new URL(sandbox.window.location.href);
  assert.equal(`${landed.origin}${landed.pathname}`, KEYCLOAK_LOGOUT_URL);
  assert.equal(landed.searchParams.has("id_token_hint"), false, "without a hint Keycloak asks for confirmation");
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
  const button = element("BUTTON", { formaction: "/session/end", title: "Logout" }, "");
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

test("a role-injected logout control keeps its own target and click handler", () => {
  const button = element("A", { "data-injected-logout": "true", href: "/oauth2/sign_out?rd=x", "aria-label": "Logout" }, "");
  patch([button]);

  assert.equal(button.getAttribute("href"), "/oauth2/sign_out?rd=x");
  assert.equal(button.dataset._logoutHandled, undefined);
  assert.equal(button.listeners.length, 0);
});

test("a text block over 1000 characters is ignored as a match source", () => {
  const link = element("A", {}, `${"x".repeat(1000)} log out`);
  patch([link]);

  assert.equal(link.dataset._logoutHandled, undefined);
});

test("debug mode hands the console one line of text, never the node or an object", () => {
  const sandbox = patch([]);
  const lines = [];
  sandbox.console.debug = (...args) => lines.push(args);
  const link = element("A", { id: "logout-link" }, "Log out");
  link.__reactFiber = { stateNode: link };
  sandbox.document.querySelectorAll = () => [link];
  sandbox.initLogoutPatch(LOGOUT_URL, true);

  assert.ok(lines.some((args) => args.join(" ").includes("<a#logout-link>")), "the patched node is named in the log");
  for (const args of lines) {
    assert.deepEqual(args.map((arg) => typeof arg), ["string"], `console.debug(${args.map(String).join(", ")})`);
  }
});
