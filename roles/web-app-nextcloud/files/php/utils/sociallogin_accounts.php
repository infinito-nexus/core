<?php
// nocheck: mirrored-unit-test - needs a booted Nextcloud, which only exists inside the container

define("OC_CONSOLE", 1);

[, $serverRoot] = $argv;

require_once $serverRoot . "/lib/base.php";

$db = \OCP\Server::get(\OCP\IDBConnection::class);

$marked = $db->getQueryBuilder();
$marked->select("userid")
    ->from("preferences")
    ->where($marked->expr()->eq("appid", $marked->createNamedParameter("sociallogin")))
    ->andWhere($marked->expr()->eq("configkey", $marked->createNamedParameter("disable_password_confirmation")));

$connected = [];
if ($db->tableExists("sociallogin_connect")) {
    $connections = $db->getQueryBuilder();
    $connections->select("uid", "identifier")->from("sociallogin_connect");
    $connected = $connections->executeQuery()->fetchAll();
}

echo "SOCIALLOGIN_ACCOUNTS " . json_encode([
    "created" => array_column($marked->executeQuery()->fetchAll(), "userid"),
    "connected" => $connected,
]) . "\n";
