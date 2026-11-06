/**
 * Upstream reads the site name only from account.json, whose presence switches
 * Postmarks into fediverse mode, so this patch hands the site name to SITE_NAME,
 * which the role renders on every deploy.
 *
 * Args:
 *   argv[2]: path of the Postmarks server.js that is patched in place.
 */

const { readFileSync, writeFileSync } = require("node:fs");

const ANCHOR = "app.set('site_name', actorInfo.displayName || 'Postmarks');";
const PATCHED = "app.set('site_name', process.env.SITE_NAME);";

function fail(message) {
  process.stderr.write(`patch_site_name.js: ${message}\n`);
  process.exit(1);
}

const server = process.argv[2];
if (!server) {
  fail("usage: node patch_site_name.js <server.js>");
}

const original = readFileSync(server, "utf8");
if (!original.includes(ANCHOR)) {
  fail(`site name anchor not found: ${ANCHOR}`);
}

writeFileSync(server, original.replace(ANCHOR, PATCHED));
process.stdout.write("patch_site_name.js: server.js reads the site name from SITE_NAME\n");
