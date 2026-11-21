<?php
// nocheck: mirrored-unit-test - needs a booted Nextcloud, which only exists inside the container

define("OC_CONSOLE", 1);

[, $serverRoot] = $argv;

require_once $serverRoot . "/lib/base.php";

$query = \OCP\Server::get(\OCP\IDBConnection::class)->getQueryBuilder();
$query->select("directory_uuid", "owncloud_name")->from("ldap_user_mapping");
$rows = $query->executeQuery()->fetchAll();
echo "LDAP_MAPPING " . json_encode((object) array_column($rows, "owncloud_name", "directory_uuid")) . "\n";
