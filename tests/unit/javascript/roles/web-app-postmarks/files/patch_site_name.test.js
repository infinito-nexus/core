const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../..");
const PATCHER = path.join(
  PROJECT_ROOT,
  "roles/web-app-postmarks/files/javascript/patch_site_name.js",
);
const ANCHOR = "app.set('site_name', actorInfo.displayName || 'Postmarks');";

const UPSTREAM = [
  "import { domain, account, simpleLogger, actorInfo, replaceEmptyText } from './src/util.js';",
  "",
  "const app = express();",
  "",
  ANCHOR,
  "app.set('bookmarksDb', bookmarksDb);",
  "",
].join("\n");

function patch(source, args) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "postmarks-site-name-"));
  const server = path.join(dir, "server.js");
  fs.writeFileSync(server, source);
  const result = spawnSync(process.execPath, [PATCHER, ...(args || [server])], {
    encoding: "utf8",
  });
  return { ...result, text: fs.readFileSync(server, "utf8") };
}

function siteName(text, env, displayName) {
  const line = text.split("\n").find((row) => row.startsWith("app.set('site_name'"));
  const app = {
    set(key, value) {
      this[key] = value;
    },
  };
  new Function("app", "actorInfo", "process", line)(app, { displayName }, { env });
  return app.site_name;
}

test("the patched server takes the site name from SITE_NAME", () => {
  const result = patch(UPSTREAM);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /reads the site name from SITE_NAME/);
  assert.equal(siteName(result.text, { SITE_NAME: "Bookmarks Hub" }, undefined), "Bookmarks Hub");
});

test("an account display name no longer overrides SITE_NAME", () => {
  const { text } = patch(UPSTREAM);

  assert.equal(siteName(text, { SITE_NAME: "Bookmarks Hub" }, "Fedi Name"), "Bookmarks Hub");
});

test("only the site name line changes", () => {
  const { text } = patch(UPSTREAM);

  assert.deepEqual(
    text.split("\n").filter((row) => !row.startsWith("app.set('site_name'")),
    UPSTREAM.split("\n").filter((row) => row !== ANCHOR),
  );
});

test("a moved anchor aborts instead of shipping a server that ignores SITE_NAME", () => {
  const source = UPSTREAM.replace(ANCHOR, "app.set('site_name', actorInfo.name || 'Postmarks');");
  const result = patch(source);

  assert.equal(result.status, 1);
  assert.match(result.stderr, /site name anchor not found/);
  assert.equal(result.text, source);
});

test("a missing server path aborts with the usage", () => {
  const result = patch(UPSTREAM, []);

  assert.equal(result.status, 1);
  assert.match(result.stderr, /usage: node patch_site_name.js <server.js>/);
  assert.equal(result.text, UPSTREAM);
});
