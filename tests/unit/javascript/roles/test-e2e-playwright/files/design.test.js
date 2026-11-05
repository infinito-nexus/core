const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../..");
const { UNPARSEABLE_COLOUR, browserGlobals, styledElement } = require(
  path.join(PROJECT_ROOT, "tests/unit/javascript/utils/canvas.js"),
);
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const globals = {};
const { measure } = loadInternals(
  path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/design.js"),
  ["measure"],
  {},
  globals,
);
const page = { evaluate: async (callback, argument) => callback(argument) };

function sample(css, parentCss) {
  const parent = parentCss ? styledElement(parentCss, null) : null;
  Object.assign(globals, browserGlobals({}, { "#target": styledElement(css, parent) }));
  return measure(page, "#target").then(structuredClone);
}

test("measure reads the text colour against the first opaque background up the tree", async () => {
  assert.deepEqual(
    await sample({ color: "rgb(10, 20, 30)", "background-color": "rgba(0, 0, 0, 0)" }, { "background-color": "#ffffff" }),
    { background: [255, 255, 255], color: [10, 20, 30] },
  );
});

test("measure samples a colour canvas cannot parse as black, not as the background sampled before it", async () => {
  assert.deepEqual(await sample({ color: UNPARSEABLE_COLOUR, "background-color": "rgb(255, 255, 255)" }), {
    background: [255, 255, 255],
    color: [0, 0, 0],
  });
});
