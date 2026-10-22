/**
 * Usage: node pds_migrations.js DATA_DIR VOLUME IMAGE
 *
 * CWD       app root of the pinned PDS image, so `@atproto/pds` resolves to the PDS that starts next
 * DATA_DIR  mount point of the PDS data volume (PDS_DATA_DIRECTORY)
 * VOLUME    name of that volume, quoted in the report
 * IMAGE     image repository of the pinned PDS, quoted in the report
 *
 * Exit 0: every applied migration is known; the pinned version is recorded.
 * Exit 3: the data carries migrations the pinned PDS does not ship; the
 *         report naming both versions goes to stdout.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");

const DOWNGRADE_EXIT = 3;
const VERSION_MARKER = "infinito-pds-version";
const ACTORS_DIR = "actors";
const ACTOR_DATABASE = "store.sqlite";
const SERVICE_DATABASES = [
  { file: "account.sqlite", migrations: "account-manager/db/migrations" },
  { file: "sequencer.sqlite", migrations: "sequencer/db/migrations" },
  { file: "did_cache.sqlite", migrations: "did-cache/db/migrations" },
];
const ACTOR_MIGRATIONS = "actor-store/db/migrations";

function unknownMigrations(applied, shipped) {
  const known = new Set(shipped);
  return [...new Set(applied)].filter((name) => !known.has(name)).sort();
}

function actorDatabases(dataDir) {
  const root = path.join(dataDir, ACTORS_DIR);
  if (!fs.existsSync(root)) {
    return [];
  }
  const found = [];
  for (const shard of fs.readdirSync(root, { withFileTypes: true })) {
    if (!shard.isDirectory()) {
      continue;
    }
    const shardDir = path.join(root, shard.name);
    for (const actor of fs.readdirSync(shardDir, { withFileTypes: true })) {
      const file = path.join(shardDir, actor.name, ACTOR_DATABASE);
      if (actor.isDirectory() && fs.existsSync(file)) {
        found.push(path.relative(dataDir, file));
      }
    }
  }
  return found.sort();
}

function databaseGroups(dataDir) {
  const groups = SERVICE_DATABASES.filter(({ file }) =>
    fs.existsSync(path.join(dataDir, file)),
  ).map(({ file, migrations }) => ({ label: file, migrations, files: [file] }));
  const actors = actorDatabases(dataDir);
  if (actors.length > 0) {
    groups.push({
      label: `${ACTORS_DIR}/*/*/${ACTOR_DATABASE} (${actors.length})`,
      migrations: ACTOR_MIGRATIONS,
      files: actors,
    });
  }
  return groups;
}

function downgradeReport({ volume, image, pinned, recorded, findings }) {
  const known = recorded && recorded !== pinned;
  const writer = known
    ? `PDS ${recorded}`
    : `a PDS newer than ${pinned}`;
  const target = known ? recorded : "the version that wrote it";
  return [
    `web-app-bluesky: the PDS data in volume ${volume} was written by ${writer}, ` +
      `but the pinned image is ${image}:${pinned}.`,
    ...findings.map(
      ({ database, unknown, shipped }) =>
        `  ${database}: migrations ${unknown.join(", ")} are unknown to PDS ${pinned}, ` +
        `which ships ${shipped.join(", ") || "none"}.`,
    ),
    `PDS ${pinned} would refuse to start with "corrupted migrations". ` +
      `Set applications.web-app-bluesky.services.pds.version to ${target} or newer, ` +
      `or restore ${volume} from the backup taken before that version ` +
      `(roles/web-app-bluesky/Administration.md).`,
  ].join("\n");
}

function readRecorded(dataDir) {
  const marker = path.join(dataDir, VERSION_MARKER);
  return fs.existsSync(marker) ? fs.readFileSync(marker, "utf8").trim() : "";
}

function appliedMigrations(Database, file) {
  const db = new Database(file, { fileMustExist: true });
  try {
    const table = db
      .prepare(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'kysely_migration'",
      )
      .get();
    if (!table) {
      return [];
    }
    return db
      .prepare("SELECT name FROM kysely_migration")
      .all()
      .map((row) => row.name);
  } finally {
    db.close();
  }
}

function main(argv) {
  const [dataDir, volume, image] = argv;
  if (!dataDir || !volume || !image) {
    process.stderr.write("usage: pds_migrations.js DATA_DIR VOLUME IMAGE\n");
    return 2;
  }
  const pdsPackage = require.resolve("@atproto/pds/package.json", {
    paths: [process.cwd()],
  });
  const pdsRequire = createRequire(pdsPackage);
  const pinned = pdsRequire(pdsPackage).version;
  const Database = pdsRequire("better-sqlite3");
  const dist = path.join(path.dirname(pdsPackage), "dist");
  const recorded = readRecorded(dataDir);

  const findings = [];
  for (const group of databaseGroups(dataDir)) {
    const shipped = Object.keys(
      pdsRequire(path.join(dist, group.migrations)).default,
    ).sort();
    const applied = group.files.flatMap((file) =>
      appliedMigrations(Database, path.join(dataDir, file)),
    );
    const unknown = unknownMigrations(applied, shipped);
    if (unknown.length > 0) {
      findings.push({ database: group.label, unknown, shipped });
    }
  }

  if (findings.length > 0) {
    process.stdout.write(
      `${downgradeReport({ volume, image, pinned, recorded, findings })}\n`,
    );
    return DOWNGRADE_EXIT;
  }

  if (recorded !== pinned) {
    fs.writeFileSync(path.join(dataDir, VERSION_MARKER), `${pinned}\n`);
    process.stdout.write(`RECORDED: ${volume} ${recorded || "-"} -> ${pinned}\n`);
  } else {
    process.stdout.write(`CURRENT: ${volume} ${pinned}\n`);
  }
  return 0;
}

module.exports = {
  DOWNGRADE_EXIT,
  VERSION_MARKER,
  actorDatabases,
  databaseGroups,
  downgradeReport,
  main,
  unknownMigrations,
};

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}
