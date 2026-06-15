/**
 * Build-time patcher that wires the trusted-header SSO middleware into
 * Postmarks' server.js (analogous to bookwyrm's settings_patch.py append).
 *
 * Postmarks is ESM with a fixed import block and a single `app.use(session())`
 * call followed by the res.locals block and the `/admin` gate. This script
 * inserts `import proxyHeaderSso from './src/sso-header-auth.js';` after the
 * upstream imports and mounts `app.use(proxyHeaderSso);` immediately after
 * `app.use(session());` so the middleware runs once req.session exists and
 * before `app.use('/admin', isAuthenticated, ...)` evaluates the gate.
 *
 * The patch is anchor-based and idempotent: a second run is a no-op, and a
 * missing anchor (e.g. after an upstream refactor) aborts the build loudly
 * rather than producing a silently un-bridged image.
 */

import { readFileSync, writeFileSync } from 'node:fs';

const SERVER_PATH = process.argv[2] || '/app/server.js';
const IMPORT_LINE = "import proxyHeaderSso from './src/sso-header-auth.js';";
const MOUNT_LINE = 'app.use(proxyHeaderSso);';
const IMPORT_ANCHOR = "import routes from './src/routes/index.js';";
const MOUNT_ANCHOR = 'app.use(session());';

function fail(message) {
  process.stderr.write(`patch_server.js: ${message}\n`);
  process.exit(1);
}

const original = readFileSync(SERVER_PATH, 'utf8');

if (original.includes(IMPORT_LINE) && original.includes(MOUNT_LINE)) {
  process.stdout.write('patch_server.js: already patched, skipping\n');
  process.exit(0);
}

if (!original.includes(IMPORT_ANCHOR)) {
  fail(`import anchor not found: ${IMPORT_ANCHOR}`);
}
if (!original.includes(MOUNT_ANCHOR)) {
  fail(`mount anchor not found: ${MOUNT_ANCHOR}`);
}

let patched = original.replace(IMPORT_ANCHOR, `${IMPORT_ANCHOR}\n${IMPORT_LINE}`);
patched = patched.replace(MOUNT_ANCHOR, `${MOUNT_ANCHOR}\n${MOUNT_LINE}`);

writeFileSync(SERVER_PATH, patched);
process.stdout.write('patch_server.js: server.js patched for trusted-header SSO\n');
