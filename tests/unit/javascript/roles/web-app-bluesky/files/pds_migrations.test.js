const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../..");
const GUARD = path.join(
  PROJECT_ROOT,
  "roles/web-app-bluesky/files/javascript/pds_migrations.js",
);
const guard = require(GUARD);

const FAKE_SQLITE = `
const fs = require("node:fs");
class Database {
  constructor(file) {
    this.applied = JSON.parse(fs.readFileSync(file, "utf8"));
  }
  prepare(sql) {
    const applied = this.applied;
    return {
      get: () => (applied === null ? undefined : { name: "kysely_migration" }),
      all: () => applied.map((name) => ({ name })),
    };
  }
  close() {}
}
module.exports = Database;
`;

const roots = [];

test.after(() => {
  for (const root of roots) {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

function writeFile(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
}

function shipping(names) {
  const entries = names.map((name) => `${JSON.stringify(name)}: {}`).join(", ");
  return `exports.default = { ${entries} };\n`;
}

function fakePds({ version, account, actor }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "pds-guard-"));
  roots.push(root);
  const app = path.join(root, "app");
  const pds = path.join(app, "node_modules/@atproto/pds");
  writeFile(
    path.join(pds, "package.json"),
    JSON.stringify({ name: "@atproto/pds", version }),
  );
  writeFile(path.join(pds, "node_modules/better-sqlite3/index.js"), FAKE_SQLITE);
  writeFile(
    path.join(pds, "dist/account-manager/db/migrations/index.js"),
    shipping(account),
  );
  writeFile(path.join(pds, "dist/sequencer/db/migrations/index.js"), shipping(["001"]));
  writeFile(path.join(pds, "dist/did-cache/db/migrations.js"), shipping(["001"]));
  writeFile(
    path.join(pds, "dist/actor-store/db/migrations/index.js"),
    shipping(actor),
  );
  const data = path.join(root, "data");
  fs.mkdirSync(data);
  return { app, data };
}

function applied(data, relative, names) {
  writeFile(path.join(data, relative), JSON.stringify(names));
}

function runGuard({ app, data }) {
  return spawnSync(
    process.execPath,
    [GUARD, data, "bluesky_pds_data", "ghcr.io/bluesky-social/pds"],
    { cwd: app, encoding: "utf8" },
  );
}

test("unknownMigrations lists applied names the image does not ship, sorted once", () => {
  assert.deepEqual(
    guard.unknownMigrations(["007", "001", "005", "007"], ["001", "002"]),
    ["005", "007"],
  );
});

test("unknownMigrations is empty when the image ships every applied migration", () => {
  assert.deepEqual(guard.unknownMigrations(["001", "002"], ["001", "002", "003"]), []);
});

test("actorDatabases finds every per-actor store below the shard directories", () => {
  const { data } = fakePds({ version: "0.4.66", account: [], actor: [] });
  applied(data, "actors/ab/did:plc:one/store.sqlite", []);
  applied(data, "actors/cd/did:plc:two/store.sqlite", []);
  writeFile(path.join(data, "actors/cd/stray.txt"), "");
  fs.mkdirSync(path.join(data, "actors/ef/did:plc:empty"), { recursive: true });

  assert.deepEqual(guard.actorDatabases(data), [
    "actors/ab/did:plc:one/store.sqlite",
    "actors/cd/did:plc:two/store.sqlite",
  ]);
});

test("actorDatabases is empty for a data directory without actors", () => {
  const { data } = fakePds({ version: "0.4.66", account: [], actor: [] });
  assert.deepEqual(guard.actorDatabases(data), []);
});

test("downgradeReport names the recorded and the pinned version", () => {
  const report = guard.downgradeReport({
    volume: "bluesky_pds_data",
    image: "ghcr.io/bluesky-social/pds",
    pinned: "0.4.66",
    recorded: "0.4.193",
    findings: [
      { database: "account.sqlite", unknown: ["005", "006"], shipped: ["001", "004"] },
    ],
  });

  assert.match(report, /written by PDS 0\.4\.193/);
  assert.match(report, /pinned image is ghcr\.io\/bluesky-social\/pds:0\.4\.66/);
  assert.match(report, /account\.sqlite: migrations 005, 006 are unknown to PDS 0\.4\.66/);
  assert.match(report, /services\.pds\.version to 0\.4\.193 or newer/);
});

test("downgradeReport without a record names the pin as the floor of the writer", () => {
  const report = guard.downgradeReport({
    volume: "bluesky_pds_data",
    image: "ghcr.io/bluesky-social/pds",
    pinned: "0.4.66",
    recorded: "",
    findings: [{ database: "account.sqlite", unknown: ["005"], shipped: [] }],
  });

  assert.match(report, /written by a PDS newer than 0\.4\.66, but/);
  assert.match(report, /which ships none/);
  assert.match(report, /to the version that wrote it or newer/);
});

test("downgradeReport ignores a record that equals the pin it contradicts", () => {
  const report = guard.downgradeReport({
    volume: "bluesky_pds_data",
    image: "ghcr.io/bluesky-social/pds",
    pinned: "0.4.66",
    recorded: "0.4.66",
    findings: [{ database: "account.sqlite", unknown: ["005"], shipped: ["001"] }],
  });

  assert.match(report, /written by a PDS newer than 0\.4\.66, but/);
  assert.doesNotMatch(report, /written by PDS 0\.4\.66/);
});

test("the guard stops with exit 3 on account migrations the pinned PDS lacks", () => {
  const layout = fakePds({
    version: "0.4.66",
    account: ["001", "002", "003", "004"],
    actor: ["001"],
  });
  applied(layout.data, "account.sqlite", ["001", "002", "003", "004", "005", "006", "007"]);

  const result = runGuard(layout);

  assert.equal(result.status, guard.DOWNGRADE_EXIT, result.stderr);
  assert.match(result.stdout, /pinned image is ghcr\.io\/bluesky-social\/pds:0\.4\.66/);
  assert.match(result.stdout, /migrations 005, 006, 007 are unknown to PDS 0\.4\.66/);
  assert.equal(fs.existsSync(path.join(layout.data, guard.VERSION_MARKER)), false);
});

test("the guard groups actor stores and reports their unknown migrations once", () => {
  const layout = fakePds({ version: "0.4.66", account: ["001"], actor: ["001"] });
  applied(layout.data, "account.sqlite", ["001"]);
  applied(layout.data, "actors/ab/did:plc:one/store.sqlite", ["001", "002"]);
  applied(layout.data, "actors/cd/did:plc:two/store.sqlite", ["001", "002"]);

  const result = runGuard(layout);

  assert.equal(result.status, guard.DOWNGRADE_EXIT, result.stderr);
  assert.match(result.stdout, /actors\/\*\/\*\/store\.sqlite \(2\): migrations 002 are unknown/);
});

test("the guard passes and records the pinned version when every migration is known", () => {
  const layout = fakePds({ version: "0.4.193", account: ["001", "002"], actor: ["001"] });
  applied(layout.data, "account.sqlite", ["001", "002"]);
  applied(layout.data, "sequencer.sqlite", ["001"]);

  const result = runGuard(layout);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /RECORDED: bluesky_pds_data - -> 0\.4\.193/);
  assert.equal(
    fs.readFileSync(path.join(layout.data, guard.VERSION_MARKER), "utf8"),
    "0.4.193\n",
  );
});

test("the guard passes unrecorded data whose migrations equal those of the pin", () => {
  const all = ["001", "002", "003", "004", "005", "006", "007"];
  const layout = fakePds({ version: "0.4.193", account: all, actor: ["001"] });
  applied(layout.data, "account.sqlite", all);
  applied(layout.data, "sequencer.sqlite", ["001"]);
  applied(layout.data, "did_cache.sqlite", ["001"]);
  applied(layout.data, "actors/ab/did:plc:one/store.sqlite", ["001"]);

  const result = runGuard(layout);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /RECORDED: bluesky_pds_data - -> 0\.4\.193/);
});

test("the guard names the recorded version when a lower pin meets newer data", () => {
  const layout = fakePds({ version: "0.4.66", account: ["001"], actor: ["001"] });
  applied(layout.data, "account.sqlite", ["001", "002"]);
  writeFile(path.join(layout.data, guard.VERSION_MARKER), "0.4.193\n");

  const result = runGuard(layout);

  assert.equal(result.status, guard.DOWNGRADE_EXIT, result.stderr);
  assert.match(result.stdout, /written by PDS 0\.4\.193/);
});

test("the guard reports the data as current when the record matches the pin", () => {
  const layout = fakePds({ version: "0.4.66", account: ["001"], actor: ["001"] });
  applied(layout.data, "account.sqlite", ["001"]);
  writeFile(path.join(layout.data, guard.VERSION_MARKER), "0.4.66\n");

  const result = runGuard(layout);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /CURRENT: bluesky_pds_data 0\.4\.66/);
});

test("the guard accepts a database that has no migration table yet", () => {
  const layout = fakePds({ version: "0.4.66", account: ["001"], actor: ["001"] });
  writeFile(path.join(layout.data, "account.sqlite"), "null");

  const result = runGuard(layout);

  assert.equal(result.status, 0, result.stderr);
});

test("the guard refuses to run without its three arguments", () => {
  const result = spawnSync(process.execPath, [GUARD], { encoding: "utf8" });

  assert.equal(result.status, 2);
  assert.match(result.stderr, /usage: pds_migrations\.js DATA_DIR VOLUME IMAGE/);
});
