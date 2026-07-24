<?php

/*
 * Verify a Friendica addon's _install() hooks are present in the
 * `hook` DB table. `bin/console addon enable` only ever writes the
 * `config[addons.<X>]` entry; the `_install()` function runs in the
 * same PHP process but its Hook::register() calls have empirically
 * been observed to leave the `hook` table empty on the first deploy
 * of a fresh stack. A disable+enable cycle from a clean shell at any
 * later point recovers it. Run this verifier after the addon-sync
 * loop so the broken state fails the role instead of surfacing as a
 * silent login regression at the Playwright stage.
 *
 * Run inside the friendica container, as the www-data user, with
 * /var/www/html as the working directory:
 *   php verify_addon_hooks.php ADDON MIN_HOOKS
 *     ADDON       addon name (e.g. ldapauth)
 *     MIN_HOOKS   minimum number of rows expected in `hook` for this
 *                 addon (e.g. 2 for ldapauth's load_config +
 *                 authenticate)
 *
 * On mismatch, runs one `bin/console addon disable` + `enable` cycle
 * and re-checks. Exits non-zero if hooks are still missing.
 */

if ($argc !== 3) {
    fwrite(STDERR, "usage: php verify_addon_hooks.php ADDON MIN_HOOKS\n");
    exit(2);
}

$addon     = $argv[1];
$minHooks  = (int) $argv[2];

require '/var/www/html/vendor/autoload.php';
$cfgFile = getenv('FRIENDICA_CONFIG_FILE');
if ($cfgFile === false) {
    fwrite(STDERR, "FRIENDICA_CONFIG_FILE env missing\n");
    exit(1);
}
$cfg = include $cfgFile;
$db  = $cfg['database'];
$h   = explode(':', $db['hostname']);
$dsn = 'mysql:host=' . $h[0] . ';port=' . ($h[1] ?? 3306) . ';dbname=' . $db['database'];
$pdo = new PDO($dsn, $db['username'], $db['password']);

function count_hooks(PDO $pdo, string $addon): int {
    $s = $pdo->prepare('SELECT COUNT(*) FROM hook WHERE file LIKE :p');
    $s->execute([':p' => '%addon/' . $addon . '/' . $addon . '.php']);
    return (int) $s->fetchColumn();
}

$count = count_hooks($pdo, $addon);
if ($count >= $minHooks) {
    echo "[verify_addon_hooks] $addon hooks=$count (>= $minHooks, OK)\n";
    exit(0);
}

echo "[verify_addon_hooks] $addon hooks=$count (< $minHooks); re-cycling disable+enable\n";
passthru('/var/www/html/bin/console addon disable ' . escapeshellarg($addon));
passthru('/var/www/html/bin/console addon enable '  . escapeshellarg($addon));

$count = count_hooks($pdo, $addon);
if ($count >= $minHooks) {
    echo "[verify_addon_hooks] $addon hooks=$count after re-cycle (>= $minHooks, OK)\n";
    exit(0);
}

fwrite(STDERR, "[verify_addon_hooks] $addon hooks=$count after re-cycle (still < $minHooks)\n");
exit(1);
