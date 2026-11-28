const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-lam/files/playwright/test-directory-login.js");

/**
 * Args:
 *   tag: element name.
 *   className: the one class the element carries.
 *   children: the elements nested in it.
 *
 * Returns:
 *   A visible element of the fake document.
 */
function element(tag, className, children = []) {
  return { tag, className, children, visible: true };
}

/**
 * Args:
 *   roots: the elements to search, themselves included.
 *   selector: a `tag.class` selector.
 *
 * Returns:
 *   Every element under the roots the selector matches.
 */
function matching(roots, selector) {
  const [tag, className] = selector.split(".");
  return roots.flatMap((root) => [
    ...(root.tag === tag && root.className === className ? [root] : []),
    ...matching(root.children, selector),
  ]);
}

/**
 * Args:
 *   resolve: returns the elements the locator stands for at the moment it is read.
 *
 * Returns:
 *   A lazy locator with the Playwright calls the spec makes on it.
 */
function locator(resolve) {
  return {
    resolve,
    locator: (selector) => locator(() => matching(resolve().flatMap((found) => found.children), selector)),
    first: () => locator(() => resolve().slice(0, 1)),
    click: async () => {
      const [target] = resolve();
      if (!target) throw new Error("nothing to click");
      target.onClick();
    },
  };
}

/**
 * Args:
 *   target: the locator under assertion.
 *   message: the spec's assertion message.
 *
 * Returns:
 *   The Playwright matchers the spec calls, each throwing the message when it does not hold.
 */
function expect(target, message) {
  const fail = (detail) => {
    throw new Error(`${message}: ${detail}`);
  };
  return {
    toBeVisible: async () => {
      if (!target.resolve().some((found) => found.visible)) fail("not visible");
    },
    toBeHidden: async () => {
      if (target.resolve().some((found) => found.visible)) fail("still visible");
    },
    toHaveCount: async (count) => {
      const found = target.resolve().length;
      if (found !== count) fail(`found ${found}`);
    },
  };
}

/**
 * Args:
 *   replyStatus: class of the status block LAM puts in its password reply popup, or null for no popup.
 *   withBanner: whether the account page carries the Unix module's statusError banner outside the popup.
 *
 * Returns:
 *   A fake page whose popup closes when its confirm button is clicked, and that popup.
 */
function accountPage(replyStatus, withBanner) {
  const document = element("html", "", withBanner ? [element("div", "statusError")] : []);
  const confirm = element("button", "swal2-confirm");
  const popup = element("div", "swal2-popup", [element("div", replyStatus), confirm]);
  confirm.onClick = () => {
    document.children = document.children.filter((child) => child !== popup);
  };
  if (replyStatus) document.children.push(popup);
  return { page: { locator: (selector) => locator(() => matching([document], selector)) }, popup, document };
}

const { acceptPasswordReply } = loadInternals(
  SPEC,
  ["acceptPasswordReply"],
  { "@playwright/test": { test: () => undefined, expect }, "./timeouts": { resolveTimeout: (ms) => ms } },
  {},
);

test("a reply holding statusInfo is accepted and closed before the save", async () => {
  const { page, popup, document } = accountPage("statusInfo", false);

  await acceptPasswordReply(page);

  assert.equal(document.children.includes(popup), false);
});

test("a reply holding statusError fails as a refused password", async () => {
  const { page } = accountPage("statusError", false);

  await assert.rejects(acceptPasswordReply(page), /LAM must not refuse the password/);
});

test("the Unix module's statusError banner outside the reply does not fail an accepted password", async () => {
  const { page, popup, document } = accountPage("statusInfo", true);

  await acceptPasswordReply(page);

  assert.equal(document.children.includes(popup), false);
  assert.equal(matching([document], "div.statusError").length, 1);
});

test("no reply at all fails as an unanswered password change", async () => {
  const { page } = accountPage(null, true);

  await assert.rejects(acceptPasswordReply(page), /LAM must answer the password change/);
});
