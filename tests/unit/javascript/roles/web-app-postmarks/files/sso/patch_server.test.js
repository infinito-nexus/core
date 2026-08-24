const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const PATCHER = path.join(
  PROJECT_ROOT,
  "roles/web-app-postmarks/files/sso/patch_server.js",
);
const IMPORT_ANCHOR = "import routes from './src/routes/index.js';";
const MOUNT_ANCHOR = "app.use(session());";
const IMPORT_LINE = "import proxyHeaderSso from './src/sso-header-auth.js';";
const MOUNT_LINE = "app.use(proxyHeaderSso);";
const ADMIN_GATE = "app.use('/admin', isAuthenticated, routes.admin);";

const UPSTREAM = [
  "import express from 'express';",
  "import session from 'express-session';",
  IMPORT_ANCHOR,
  "",
  "const app = express();",
  "",
  MOUNT_ANCHOR,
  "",
  "app.use((req, res, next) => {",
  "  res.locals.loggedIn = req.session.loggedIn;",
  "  next();",
  "});",
  "",
  ADMIN_GATE,
  "",
].join("\n");

function patch(source) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "postmarks-patch-"));
  const server = path.join(dir, "server.js");
  fs.writeFileSync(server, source);
  return () => {
    const result = spawnSync(process.execPath, [PATCHER, server], {
      encoding: "utf8",
    });
    const text = fs.readFileSync(server, "utf8");
    return { ...result, text, rows: text.split("\n") };
  };
}

test("the bridge import lands directly under the upstream import block", () => {
  const run = patch(UPSTREAM);
  const result = run();

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /patched for trusted-header SSO/);
  assert.equal(
    result.rows.indexOf(IMPORT_LINE),
    result.rows.indexOf(IMPORT_ANCHOR) + 1,
  );
});

test("the middleware mounts between the session and the admin gate", () => {
  const { rows } = patch(UPSTREAM)();

  assert.equal(rows.indexOf(MOUNT_LINE), rows.indexOf(MOUNT_ANCHOR) + 1);
  assert.ok(
    rows.indexOf(MOUNT_LINE) < rows.indexOf(ADMIN_GATE),
    "the gate must see a session the middleware already touched",
  );
});

test("a second run changes nothing and says so", () => {
  const run = patch(UPSTREAM);
  const once = run().text;
  const twice = run();

  assert.equal(twice.status, 0, twice.stderr);
  assert.match(twice.stdout, /already patched, skipping/);
  assert.equal(twice.text, once);
});

test("a moved import anchor aborts instead of shipping an un-bridged server", () => {
  const source = UPSTREAM.replace(IMPORT_ANCHOR, "import routes from './r.js';");
  const result = patch(source)();

  assert.equal(result.status, 1);
  assert.match(result.stderr, /import anchor not found/);
  assert.equal(result.text, source);
});

test("a moved mount anchor aborts instead of shipping an un-bridged server", () => {
  const source = UPSTREAM.replace(MOUNT_ANCHOR, "app.use(session(options));");
  const result = patch(source)();

  assert.equal(result.status, 1);
  assert.match(result.stderr, /mount anchor not found/);
  assert.equal(result.text, source);
});
