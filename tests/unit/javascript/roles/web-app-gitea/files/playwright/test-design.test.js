const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-gitea/files/playwright/test-design.js");
const TOGGLE = "#footer-theme-selector";
const THEME = "gitea-auto-tritanopia";
const TO_PASS_ATTEMPTS = 5;
const RETRIED_TOGGLE = /^ {2}await expect\(async \(\) => \{\n[\s\S]*?^ {2}\}\)\.toPass\(\{ timeout: resolveTimeout\(30_000\) \}\);\n/gm;
const SINGLE_TOGGLE_CLICK = '  await page.locator("#footer-theme-selector").click();\n';

/**
 * Args:
 *   actual: the locator under assertion, or the block toPass retries.
 *   message: the failure message.
 *
 * Returns:
 *   The matchers pickTheme calls, failing with the message. toPass gives its block TO_PASS_ATTEMPTS tries, as
 *   Playwright's retries until its timeout, and rethrows the last failure.
 */
function expect(actual, message) {
  return {
    toBeVisible: async () => assert.ok(await actual.isVisible(), message),
    toHaveAttribute: async (name, value) => assert.equal(actual.getAttribute(name), value, message),
    toPass: async () => {
      let failure;
      for (let attempt = 0; attempt < TO_PASS_ATTEMPTS; attempt += 1) {
        try {
          return await actual();
        } catch (error) {
          failure = error;
        }
      }
      throw failure;
    },
  };
}

expect.poll = (poll, { message }) => ({
  toBe: async (expected) => assert.equal(await poll(), expected, message),
});

/**
 * Args:
 *   file: the spec file to load.
 *
 * Returns:
 *   Its pickTheme.
 */
function loadPickTheme(file) {
  return loadInternals(
    file,
    ["pickTheme"],
    {
      "@playwright/test": { test: () => {}, expect },
      "./personas": { decodeDotenvQuotedValue: (value) => value },
      "./timeouts": { resolveTimeout: (ms) => ms },
    },
    {},
  ).pickTheme;
}

/**
 * Args:
 *   unwiredClicks: how many toggle clicks land before Gitea's script wires the toggle; those open nothing.
 *
 * Returns:
 *   { page, footer }: a Gitea page whose footer theme selector opens its menu once wired, and whose item click applies
 *   that theme and its stylesheet. footer counts the toggle clicks and holds the applied theme. A click on a hidden
 *   item fails like Playwright's click once its wait for visibility runs out.
 */
function giteaFooter(unwiredClicks) {
  const footer = { clicks: 0, open: false, theme: "corporate-auto" };
  const toggle = {
    click: async () => {
      footer.clicks += 1;
      if (footer.clicks > unwiredClicks) {
        footer.open = !footer.open;
      }
    },
  };
  const item = (theme) => ({
    isVisible: async () => footer.open,
    click: async () => {
      if (!footer.open) {
        throw new Error(`locator.click: Timeout exceeded waiting for the ${theme} item to be visible`);
      }
      footer.open = false;
      footer.theme = theme;
    },
  });
  const html = { getAttribute: (name) => (name === "data-theme" ? footer.theme : null) };
  const page = {
    locator: (selector) => {
      if (selector === TOGGLE) {
        return toggle;
      }
      if (selector === "html") {
        return html;
      }
      return item(selector.match(/data-value="([^"]+)"/)[1]);
    },
    evaluate: async (_check, file) => file === `/assets/css/theme-${footer.theme}.`,
  };
  return { page, footer };
}

/**
 * Returns:
 *   The path of a planted copy of the spec whose pickTheme clicks the toggle once, for a negative control.
 */
function singleToggleClick() {
  const source = fs.readFileSync(SPEC, "utf8");
  assert.equal((source.match(RETRIED_TOGGLE) || []).length, 1, "the retried toggle click must occur exactly once");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "gitea-design-plant-"));
  const file = path.join(directory, "test-design.js");
  fs.writeFileSync(file, source.replace(RETRIED_TOGGLE, SINGLE_TOGGLE_CLICK));
  return file;
}

const pickTheme = loadPickTheme(SPEC);

test("a pick whose first toggle click lands before Gitea wires the selector clicks again and applies the theme", async () => {
  const { page, footer } = giteaFooter(1);

  await pickTheme(page, THEME);

  assert.equal(footer.theme, THEME);
  assert.equal(footer.clicks, 2);
});

test("a pick on a wired selector clicks the toggle once, so it does not close the menu it opened", async () => {
  const { page, footer } = giteaFooter(0);

  await pickTheme(page, THEME);

  assert.equal(footer.theme, THEME);
  assert.equal(footer.clicks, 1);
});

test("a selector Gitea never wires fails the pick", async () => {
  const { page, footer } = giteaFooter(Number.POSITIVE_INFINITY);

  await assert.rejects(pickTheme(page, THEME), new RegExp(`the theme selector must offer ${THEME}`));
  assert.equal(footer.theme, "corporate-auto");
});

test("negative control: a single toggle click against a not yet wired selector fails the pick", async () => {
  const file = singleToggleClick();
  try {
    const { page, footer } = giteaFooter(1);

    await assert.rejects(loadPickTheme(file)(page, THEME), /locator\.click: Timeout exceeded/);
    assert.equal(footer.theme, "corporate-auto");
  } finally {
    fs.rmSync(path.dirname(file), { recursive: true, force: true });
  }
});
