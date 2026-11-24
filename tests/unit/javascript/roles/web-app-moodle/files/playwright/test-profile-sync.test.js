const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-moodle/files/playwright/test-profile-sync.js");
const LOCKED_COUNTRY = "#fitem_id_country .felement";

/**
 * Args:
 *   lang: the lang attribute of the Moodle page.
 *   shown: the text Moodle prints for the locked country select.
 *
 * Returns:
 *   The page double and the list of assertions the spec made against it.
 */
function lockedForm(lang, shown) {
  const assertions = [];
  const page = {
    locator: (selector) => ({
      selector,
      text: selector === LOCKED_COUNTRY ? shown : null,
      getAttribute: async (name) => (selector === "html" && name === "lang" ? lang : null),
    }),
  };
  const expect = (target, message) => ({
    toHaveText: async (wanted) => {
      assertions.push({ selector: target.selector, wanted });
      assert.equal(target.text, wanted, message);
    },
  });
  return { page, expect, assertions };
}

function loadExpectLockedCountry(expect) {
  return loadInternals(
    SPEC,
    ["expectLockedCountry"],
    {
      "@playwright/test": { test: () => undefined, expect },
      "./timeouts": { resolveTimeout: (ms) => ms },
    },
    {},
  ).expectLockedCountry;
}

test("the locked country is read from the printed name in an English form", async () => {
  const { page, expect, assertions } = lockedForm("en", "Germany");

  await loadExpectLockedCountry(expect)(page, "DE");

  assert.deepEqual(assertions, [{ selector: LOCKED_COUNTRY, wanted: "Germany" }]);
});

test("the locked country follows the page language of the account", async () => {
  const { page, expect, assertions } = lockedForm("de", "Deutschland");

  await loadExpectLockedCountry(expect)(page, "DE");

  assert.deepEqual(assertions, [{ selector: LOCKED_COUNTRY, wanted: "Deutschland" }]);
});

test("negative control: a locked country other than the claim fails naming the claim", async () => {
  const { page, expect } = lockedForm("en", "Austria");

  await assert.rejects(loadExpectLockedCountry(expect)(page, "DE"), /flat country claim of the moodle scope/);
});

test("negative control: a country the claim never reached fails on the empty selection", async () => {
  const { page, expect } = lockedForm("en", "Select a country...");

  await assert.rejects(loadExpectLockedCountry(expect)(page, "DE"), /prints as Germany/);
});
