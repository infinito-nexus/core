const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const STYLESHEET = fs.readFileSync(path.join(PROJECT_ROOT, "roles/web-app-opencloud/templates/style.css.j2"), "utf8");
const FILLED_CONTROLS = ":is(.oc-button-primary-filled, #exitAnchor)";

const noop = () => undefined;
const { ACCESS_DENIED_TEXTS } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-opencloud/files/playwright/test-design.js"),
  ["ACCESS_DENIED_TEXTS"],
  {
    "./onion-test": { test: Object.assign(noop, { use: noop, skip: noop }), expect: noop },
    "./_shared": { baseUrl: "https://opencloud.example.test/" },
  },
  {},
);

/**
 * Args:
 *   css: role stylesheet template.
 *   selector: selector list of a rule that starts a line of the stylesheet.
 *
 * Returns:
 *   The declarations of that rule as a property to value map, or null when no rule has exactly this selector list.
 */
function declarations(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rule = new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`).exec(css);
  if (!rule) return null;
  return Object.fromEntries(
    rule[1]
      .split(";")
      .map((declaration) => declaration.trim())
      .filter(Boolean)
      .map((declaration) => declaration.split(/:\s*/, 2)),
  );
}

test("the sign-in call to action of the access-denied page, secondary-filled since OpenCloud Web 8, takes the primary color and its on-color", () => {
  assert.deepEqual(declarations(STYLESHEET, "#exitAnchor"), {
    "--oc-button-color": "var(--design-primary)",
    "--oc-button-on-color": "var(--design-on-primary)",
  });
});

test("the hovered or pressed call to action takes the hover and active shade of the primary color", () => {
  assert.equal(
    declarations(STYLESHEET, `${FILLED_CONTROLS}:hover:not([disabled], .no-hover)`)?.["background-color"],
    "var(--design-primary-hover)",
  );
  assert.equal(
    declarations(STYLESHEET, `${FILLED_CONTROLS}:active:not([disabled])`)?.["background-color"],
    "var(--design-primary-active)",
  );
});

test("a checked checkbox, which OpenCloud Web 8 fills with the secondary role, takes the primary color", () => {
  assert.deepEqual(declarations(STYLESHEET, ".oc-checkbox:checked:not(:disabled)"), {
    "border-color": "var(--design-primary)",
    "background-color": "var(--design-primary)",
  });
});

test("the check and dash marks of a checkbox take the on-primary color without touching its focus outline", () => {
  assert.equal(
    declarations(STYLESHEET, '.oc-checkbox[type="checkbox"]:is(:checked, :indeterminate):not(:disabled)::before')?.[
      "background-color"
    ],
    "var(--design-on-primary)",
  );
  assert.ok(!/--oc-role-on-secondary\s*:/.test(STYLESHEET));
});

test("the access-denied readability check reads the card title inside the app, past the hidden browser-support card", () => {
  assert.deepEqual(ACCESS_DENIED_TEXTS, ["#exitAnchor", "#opencloud .oc-card h2"]);
  assert.ok(ACCESS_DENIED_TEXTS.every((selector) => !selector.includes(".oc-login")));
});
