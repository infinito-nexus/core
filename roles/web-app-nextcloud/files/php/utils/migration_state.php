<?php
// nocheck: mirrored-unit-test - needs a booted Nextcloud, which only exists inside the container

define("OC_CONSOLE", 1);

[, $serverRoot, $appId] = $argv;

require_once $serverRoot . "/lib/base.php";

$migrations = new \OC\DB\MigrationService($appId, \OCP\Server::get(\OC\DB\Connection::class));

echo "MIGRATION_STATE " . json_encode([
    "migrated" => $migrations->getMigratedVersions(),
    "available" => $migrations->getAvailableVersions(),
]) . "\n";
