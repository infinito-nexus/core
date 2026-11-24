const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const STYLESHEET = fs.readFileSync(path.join(PROJECT_ROOT, "roles/web-app-n8n/templates/style.css.j2"), "utf8");
const AGENTS_TAB = { "data-test-id": "tab-AgentsListView" };
const N8N_3_PREVIEW_BADGE = {
  class: "n8n-badge _badge_9ccb0_3 _outline_9ccb0_115 _xxsmall_9ccb0_52 _badge_1nupv_1 _badge_1xd39_84",
};
const N8N_3_PREVIEW_BADGE_PAINT = { "border-top-color": "--border-color", color: "--text-color--subtle" };
const N8N_2_SELECTOR = "[class*='_badge_'][class*='_secondary_']";
const N8N_2_TOKENS = [
  ["background-color", "--design-info-subtle"],
  ["color", "--design-info"],
];

const { PREVIEW_BADGE, PREVIEW_BADGE_TOKENS } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-n8n/files/playwright/test-design.js"),
  ["PREVIEW_BADGE", "PREVIEW_BADGE_TOKENS"],
  {},
  {},
);

/**
 * Args:
 *   compound: one compound selector made of `.class`, `[name='value']` and `[name*='value']` parts.
 *   element: attributes of one element by name.
 *
 * Returns:
 *   Whether the element carries every part of the compound.
 */
function compoundMatches(compound, element) {
  const parts = compound.match(/\.[\w-]+|\[[\w-]+\*?='[^']*'\]/g) || [];
  assert.equal(parts.join(""), compound, `unsupported selector ${compound}`);
  const classes = (element.class || "").split(/\s+/).filter(Boolean);
  return parts.every((part) => {
    if (part.startsWith(".")) return classes.includes(part.slice(1));
    const [, name, contains, value] = /^\[([\w-]+)(\*?)='([^']*)'\]$/.exec(part);
    const actual = element[name];
    if (actual === undefined) return false;
    return contains ? actual.includes(value) : actual === value;
  });
}

/**
 * Args:
 *   selector: compound selectors joined by the descendant combinator.
 *   chain: attributes of each element from the outermost ancestor down to the element the selector must reach.
 *
 * Returns:
 *   Whether the selector reaches the last element of the chain.
 */
function reaches(selector, chain) {
  const compounds = selector.split(" ");
  if (!compoundMatches(compounds.pop(), chain[chain.length - 1])) return false;
  let ancestor = chain.length - 2;
  for (const compound of compounds.reverse()) {
    while (ancestor >= 0 && !compoundMatches(compound, chain[ancestor])) ancestor -= 1;
    if (ancestor < 0) return false;
    ancestor -= 1;
  }
  return true;
}

/**
 * Args:
 *   variable: n8n variable the role stylesheet redefines in its root block.
 *
 * Returns:
 *   The design token the role stylesheet routes the variable to, or null when it leaves the variable alone.
 */
function routedToken(variable) {
  const match = new RegExp(`^\\s*${variable}: var\\((--design-[\\w-]+)\\);`, "m").exec(STYLESHEET);
  return match ? match[1] : null;
}

/**
 * Args:
 *   tokens: pairs of a CSS property of the preview badge and the design token it must show.
 *
 * Returns:
 *   Whether n8n 3 paints each property from a variable the role stylesheet routes to that token.
 */
function paintedFromPalette(tokens) {
  return tokens.every(
    ([property, token]) => property in N8N_3_PREVIEW_BADGE_PAINT && routedToken(N8N_3_PREVIEW_BADGE_PAINT[property]) === token,
  );
}

test("the preview badge selector reaches the n8n 3 preview badge of the Agents tab", () => {
  assert.equal(reaches(PREVIEW_BADGE, [AGENTS_TAB, N8N_3_PREVIEW_BADGE]), true);
});

test("the n8n 2 secondary badge selector misses the n8n 3 preview badge", () => {
  assert.equal(reaches(N8N_2_SELECTOR, [AGENTS_TAB, N8N_3_PREVIEW_BADGE]), false);
});

test("the preview badge selector does not reach a badge outside the Agents tab", () => {
  assert.equal(reaches(PREVIEW_BADGE, [{ "data-test-id": "tab-WorkflowsView" }, N8N_3_PREVIEW_BADGE]), false);
});

test("every token the spec expects on the preview badge is the one the role stylesheet routes its n8n 3 variable to", () => {
  assert.ok(PREVIEW_BADGE_TOKENS.length > 0);
  assert.equal(paintedFromPalette(PREVIEW_BADGE_TOKENS), true);
});

test("the n8n 2 info tokens are not what the n8n 3 preview badge is painted from", () => {
  assert.equal(paintedFromPalette(N8N_2_TOKENS), false);
});
