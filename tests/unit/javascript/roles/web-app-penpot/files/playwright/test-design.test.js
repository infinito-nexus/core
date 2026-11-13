const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "https://penpot.example.test";

const { screenUrl } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-penpot/files/playwright/test-design.js"),
  ["screenUrl"],
  {},
  {},
);

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
