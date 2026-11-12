const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { UNPARSEABLE_COLOUR, browserGlobals, styledElement } = require(
  path.join(PROJECT_ROOT, "tests/unit/javascript/utils/canvas.js"),
);
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const globals = browserGlobals({}, {});
const { contrast } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-bluesky/files/playwright/test-design.js"),
  ["contrast"],
  {},
  globals,
);

function contrastOf(css) {
  const element = styledElement(css, null);
  return contrast({ evaluate: async (callback) => callback(element) });
}

test("contrast rates black text on white at 21 and white on white at 1", async () => {
  assert.equal(await contrastOf({ color: "rgb(0, 0, 0)", "background-color": "rgb(255, 255, 255)" }), 21);
  assert.equal(await contrastOf({ color: "rgb(255, 255, 255)", "background-color": "rgb(255, 255, 255)" }), 1);
});

test("contrast samples a text colour canvas cannot parse as black, not as the background sampled before it", async () => {
  assert.equal(await contrastOf({ color: UNPARSEABLE_COLOUR, "background-color": "rgb(255, 255, 255)" }), 21);
});
