<?php
/*
 * Usage: php upgrade_database.php YOURLS_ROOT
 *   YOURLS_ROOT  directory holding includes/load-yourls.php
 * Stdout: "upgraded <old> -> <new>" or "current <db_version>", exit 0.
 * Failure: diagnostics on stderr, exit 1. Usage error: exit 2.
 */

if ($argc !== 2) {
    fwrite(STDERR, "usage: php upgrade_database.php YOURLS_ROOT\n");
    exit(2);
}

define('YOURLS_UPGRADING', true);

$infinito_upgrade_done = false;

register_shutdown_function(static function (): void {
    if ($GLOBALS['infinito_upgrade_done']) {
        return;
    }
    $chatter = '';
    while (ob_get_level() > 0) {
        $chatter = ob_get_clean() . $chatter;
    }
    fwrite(STDERR, "YOURLS stopped before the database upgrade completed\n" . trim(strip_tags($chatter)) . "\n");
    exit(1);
});

function infinito_upgrade_report(string $line): void
{
    $GLOBALS['infinito_upgrade_done'] = true;
    while (ob_get_level() > 0) {
        ob_end_clean();
    }
    echo $line, "\n";
    exit(0);
}

function infinito_upgrade_fail(string $reason): void
{
    $GLOBALS['infinito_upgrade_done'] = true;
    $chatter = '';
    while (ob_get_level() > 0) {
        $chatter = ob_get_clean() . $chatter;
    }
    fwrite(STDERR, $reason . "\n" . trim(strip_tags($chatter)) . "\n");
    exit(1);
}

ob_start();
require rtrim($argv[1], '/') . '/includes/load-yourls.php';

list($infinito_old_version, $infinito_old_sql) = yourls_get_current_version_from_sql();

if (!yourls_upgrade_is_needed()) {
    infinito_upgrade_report('current ' . $infinito_old_sql);
}

if ((int) $infinito_old_sql < 200) {
    infinito_upgrade_fail('db_version ' . $infinito_old_sql . ' predates YOURLS 1.4; its multi-request row conversion needs admin/upgrade.php');
}

yourls_upgrade(1, $infinito_old_version, YOURLS_VERSION, $infinito_old_sql, YOURLS_DB_VERSION);
yourls_upgrade(3, $infinito_old_version, YOURLS_VERSION, $infinito_old_sql, YOURLS_DB_VERSION);

if (yourls_upgrade_is_needed()) {
    infinito_upgrade_fail('YOURLS still needs a database upgrade after running it');
}

infinito_upgrade_report('upgraded ' . $infinito_old_sql . ' -> ' . YOURLS_DB_VERSION);
