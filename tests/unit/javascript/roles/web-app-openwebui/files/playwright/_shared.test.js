const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SHARED = path.join(PROJECT_ROOT, "roles/web-app-openwebui/files/playwright/_shared.js");
const PRE_FIX_CONTROLS = "a, button, [role='menuitem']";
const SIGN_OUT_TEXT = /^\s*(sign\s*out|log\s*out|abmelden)\s*$/i;
const POLL_LIMIT = 50;
const identity = (value) => value;
const tick = () => new Promise((resolve) => setImmediate(resolve));

/**
 * Args:
 *   readValue: async or sync callback whose result is compared.
 *   matches: predicate the result must satisfy.
 *   message: failure text.
 */
async function pollUntil(readValue, matches, message) {
  for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
    if (matches(await readValue())) return;
    await tick();
  }
  throw new Error(message);
}

function fakeExpect(target, message) {
  return {
    toBeVisible: () => pollUntil(() => target.isVisible(), Boolean, message),
  };
}

/**
 * Args:
 *   selector: the CSS selector a locator was built from.
 *
 * Returns:
 *   Whether the selector leaves out every element inside an `[inert]` subtree, as `:not([inert] *)` does.
 */
function excludesInertSubtrees(selector) {
  return /:not\([^)]*\[inert\] \*[^)]*\)/.test(selector);
}

/**
 * Args:
 *   menuState: "closing" for a user menu that Escape just closed (Svelte keeps it in the DOM as `inert` until its
 *     exit transition ends), "open" for an open menu, null for no menu.
 *
 * Returns:
 *   An Open WebUI stand-in whose menus each hold one Sign Out item. A closing menu leaves the DOM once its exit
 *   transition ends, which the first scroll into view of a Sign Out item stands for; a Sign Out locator whose element
 *   is gone by then fails the way `locator.evaluate` timed out in CI.
 */
function openwebuiApp(menuState) {
  const app = { menus: [], triggerClicks: 0, signOutClicks: [] };
  if (menuState) app.menus.push({ text: "Sign Out", inert: menuState === "closing", attached: true });

  const finishExitTransitions = () => {
    for (const menu of app.menus) {
      if (menu.inert) menu.attached = false;
    }
  };

  const signOutLocator = (selector, hasText) => {
    const matching = () =>
      app.menus.filter(
        (menu) =>
          menu.attached &&
          !(menu.inert && excludesInertSubtrees(selector)) &&
          (!hasText || hasText.test(menu.text)),
      );
    const locator = {
      first: () => locator,
      filter: (options) => signOutLocator(selector, options.hasText),
      isVisible: async () => matching().length > 0,
      scrollIntoViewIfNeeded: async () => finishExitTransitions(),
      evaluate: async () => {
        const [menu] = matching();
        if (!menu) throw new Error(`locator.evaluate: Timeout exceeded waiting for ${selector}`);
        app.signOutClicks.push(menu);
      },
    };
    return locator;
  };

  const trigger = {
    first: () => trigger,
    or: () => trigger,
    waitFor: async () => undefined,
    scrollIntoViewIfNeeded: async () => undefined,
    evaluate: async () => {
      app.triggerClicks += 1;
      app.menus.push({ text: "Sign Out", inert: false, attached: true });
    },
  };
  const noModal = { first: () => noModal, isVisible: async () => false };

  app.page = {
    locator: (selector) => (selector.includes("[role='dialog']") ? noModal : signOutLocator(selector, null)),
    getByRole: () => trigger,
    keyboard: { press: async () => undefined },
    waitForTimeout: async () => undefined,
  };
  return app;
}

function loadLogout() {
  return loadInternals(
    SHARED,
    ["openwebuiLogout"],
    {
      "@playwright/test": { expect: fakeExpect, test: {} },
      "./timeouts": { resolveTimeout: identity },
    },
    {},
  ).openwebuiLogout;
}

test("a Sign Out left in a user menu that is still closing is not clicked; the menu is reopened and its live Sign Out clicked", async () => {
  const app = openwebuiApp("closing");
  await loadLogout()(app.page, "https://chat.example.org");
  assert.equal(app.triggerClicks, 1, "the helper must reopen the user menu instead of chasing the closing one");
  assert.equal(app.signOutClicks.length, 1);
  assert.equal(app.signOutClicks[0].inert, false, "the clicked Sign Out must belong to the reopened menu");
});

test("a Sign Out in a user menu that is open is clicked without touching the menu trigger", async () => {
  const app = openwebuiApp("open");
  await loadLogout()(app.page, "https://chat.example.org");
  assert.equal(app.triggerClicks, 0);
  assert.equal(app.signOutClicks.length, 1);
});

test("without a menu the helper opens the user menu and clicks its Sign Out", async () => {
  const app = openwebuiApp(null);
  await loadLogout()(app.page, "https://chat.example.org");
  assert.equal(app.triggerClicks, 1);
  assert.equal(app.signOutClicks.length, 1);
});

test("negative control: a locator that keeps inert subtrees sees the closing menu's Sign Out, then loses it", async () => {
  const app = openwebuiApp("closing");
  const signOut = app.page.locator(PRE_FIX_CONTROLS).filter({ hasText: SIGN_OUT_TEXT }).first();
  assert.equal(await signOut.isVisible(), true, "the pre-fix locator must report the closing menu's Sign Out visible");
  await signOut.scrollIntoViewIfNeeded();
  await assert.rejects(signOut.evaluate(() => undefined), /locator\.evaluate: Timeout/);
});
