const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "https://penpot.example.test";
const ICON = "link[rel~='icon']";
const FAVICON = "https://cdn.example.test/roles/web-app-penpot/latest/img/design/favicon.ico";
const PENPOT_SVG = "images/favicon.svg";
const PENPOT_PNG = "images/favicon.png";
const STYLESHEET = fs.readFileSync(path.join(PROJECT_ROOT, "roles/web-app-penpot/templates/style.css.j2"), "utf8");
const PERSONAL_TEAM_SLOTS = [
  "main_ui_dashboard_organization_team_switch__personal-projects-icon",
  "main_ui_dashboard_organization_team_switch__team-item-personal-icon",
];

const { screenUrl, assertEveryIcon, SIDEBAR_LOGO } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-penpot/files/playwright/test-design.js"),
  ["screenUrl", "assertEveryIcon", "SIDEBAR_LOGO"],
  {},
  {},
);

/**
 * Args:
 *   css: role stylesheet template.
 *   slot: class Penpot renders on the element whose icon the logo replaces.
 *
 * Returns:
 *   Whether a rule names the slot in its selector list, paints the generated logo onto it and hides the icon inside.
 */
function brandsSlot(css, slot) {
  const selector = `\\[class\\*="${slot}"\\]`;
  return (
    new RegExp(`${selector}[^{]*\\{\\s*background: url\\("\\{\\{ design\\.urls\\.logo\\.svg \\}\\}"\\)`).test(css) &&
    new RegExp(`${selector} > svg[^{]*\\{\\s*visibility: hidden;`).test(css)
  );
}

/**
 * Args:
 *   hrefs: href of each icon link in the head of the page.
 *
 * Returns:
 *   A page whose icon locator, like Playwright's, narrows to its first link and hands out one locator per link.
 */
function pageWithIcons(hrefs) {
  const locator = (links) => ({
    links,
    first: () => locator(links.slice(0, 1)),
    all: async () => links.map((link) => locator([link])),
  });
  return {
    locator: (selector) => {
      assert.equal(selector, ICON);
      return locator(hrefs);
    },
  };
}

/**
 * Args:
 *   target: locator under assertion.
 *
 * Returns:
 *   The matchers assertEveryIcon calls; like Playwright's strict mode they refuse a locator that does not resolve to exactly one link.
 */
function strictExpect(target) {
  const single = () => {
    if (target.links.length !== 1) throw new Error(`strict mode violation: resolved to ${target.links.length} elements`);
    return target.links[0];
  };
  return {
    toBeAttached: async () => {
      single();
    },
    toHaveAttribute: async (name, value) => {
      const href = single();
      if (href !== value) throw new Error(`expected ${name}="${value}", received "${href}"`);
    },
  };
}

test("the SVG and the PNG icon link Penpot ships pass once both point at the generated favicon", async () => {
  await assertEveryIcon(pageWithIcons([FAVICON, FAVICON]), strictExpect, FAVICON);
});

test("an icon link that keeps Penpot's own image fails, also behind a branded first link", async () => {
  await assert.rejects(assertEveryIcon(pageWithIcons([PENPOT_SVG, PENPOT_PNG]), strictExpect, FAVICON), /received "images\/favicon\.svg"/);
  await assert.rejects(assertEveryIcon(pageWithIcons([FAVICON, PENPOT_PNG]), strictExpect, FAVICON), /received "images\/favicon\.png"/);
});

test("a page without an icon link fails", async () => {
  await assert.rejects(assertEveryIcon(pageWithIcons([]), strictExpect, FAVICON), /resolved to 0 elements/);
});

test("a design view opens its screen through the query string Penpot 2.19 routes by, not a legacy hash", () => {
  const signIn = new URL(screenUrl(BASE, "sign-in", "auth-login"));
  assert.equal(signIn.hash, "");
  assert.equal(signIn.searchParams.get("screen"), "auth-login");
  assert.equal(signIn.searchParams.get("design-view"), "sign-in");
});

test("the screen's own parameters travel next to the screen key", () => {
  const files = new URL(screenUrl(BASE, "project-files", "dashboard-files?team-id=7b12&project-id=9c3d"));
  assert.equal(files.hash, "");
  assert.equal(files.searchParams.get("screen"), "dashboard-files");
  assert.equal(files.searchParams.get("team-id"), "7b12");
  assert.equal(files.searchParams.get("project-id"), "9c3d");
  assert.equal(files.searchParams.get("design-view"), "project-files");
});

test("the app root carries no screen key", () => {
  assert.equal(screenUrl(BASE, "session", ""), `${BASE}/?design-view=session`);
});

test("two views of one screen get documents of their own", () => {
  assert.notEqual(screenUrl(BASE, "sign-in", "auth-login"), screenUrl(BASE, "sign-in-focus", "auth-login"));
});

test("the spec looks for the dashboard logo in the personal-team slot of the Penpot 2.19 team switch", () => {
  assert.ok(SIDEBAR_LOGO.startsWith("[data-testid='dashboard-sidebar'] "));
  assert.ok(SIDEBAR_LOGO.endsWith(`[class*='${PERSONAL_TEAM_SLOTS[0]}']`));
});

test("the stylesheet puts the generated logo into every personal-team slot of the Penpot 2.19 team switch", () => {
  for (const slot of PERSONAL_TEAM_SLOTS) {
    assert.ok(brandsSlot(STYLESHEET, slot), `style.css.j2 must brand ${slot}`);
  }
});
