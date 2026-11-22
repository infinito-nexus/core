const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { UNPARSEABLE_COLOUR, browserGlobals, styledElement } = require(
  path.join(PROJECT_ROOT, "tests/unit/javascript/utils/canvas.js"),
);
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const TOKEN = "--design-link";
const expect = () => undefined;
expect.poll = (read, { message }) => ({
  toBe: async (wanted) => assert.equal(await read(), wanted, message),
});

const registers = new Proxy(() => undefined, { get: () => () => undefined });

const globals = {};
const { assertTokenPixel } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-decidim/files/playwright/test-design.js"),
  ["assertTokenPixel"],
  { "@playwright/test": { expect, test: registers } },
  globals,
);
const page = { evaluate: async (callback, argument) => callback(argument) };

function linkRendersAs(color) {
  Object.assign(globals, browserGlobals({ [TOKEN]: "rgb(255, 255, 255)" }, { a: styledElement({ color }, null) }));
  return assertTokenPixel(page, "a", "color", TOKEN, "link");
}

test("assertTokenPixel accepts a colour that renders as the token and refuses another", async () => {
  await linkRendersAs("#fff");
  await assert.rejects(linkRendersAs("rgb(0, 0, 255)"), /link: a color must render as --design-link/);
});

test("assertTokenPixel refuses a colour canvas cannot parse instead of reading it as the token sampled before it", async () => {
  await assert.rejects(linkRendersAs(UNPARSEABLE_COLOUR), { actual: "0,0,0,255 instead of 255,255,255,255" });
});
