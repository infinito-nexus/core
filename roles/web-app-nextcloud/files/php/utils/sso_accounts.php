<?php
// nocheck: mirrored-unit-test - needs a booted Nextcloud, which only exists inside the container

define("OC_CONSOLE", 1);

[, $serverRoot] = $argv;

require_once $serverRoot . "/lib/base.php";

$db = \OCP\Server::get(\OCP\IDBConnection::class);

$rows = static function (string $table, array $columns) use ($db): array {
    if (!$db->tableExists($table)) {
        return [];
    }
    $query = $db->getQueryBuilder();
    $query->select(...$columns)->from($table);
    return $query->executeQuery()->fetchAll();
};

$marked = $db->getQueryBuilder();
$marked->select("userid")
    ->from("preferences")
    ->where($marked->expr()->eq("appid", $marked->createNamedParameter("sociallogin")))
    ->andWhere($marked->expr()->eq("configkey", $marked->createNamedParameter("disable_password_confirmation")));

$config = $db->getQueryBuilder();
$config->select("configvalue")
    ->from("appconfig")
    ->where($config->expr()->eq("appid", $config->createNamedParameter("sociallogin")))
    ->andWhere($config->expr()->eq("configkey", $config->createNamedParameter("custom_providers")));
$customProviders = json_decode((string) $config->executeQuery()->fetchOne(), true);

$providers = [];
foreach ((is_array($customProviders) ? $customProviders : []) as $entries) {
    foreach ((is_array($entries) ? $entries : []) as $entry) {
        if (is_array($entry) && isset($entry["name"])) {
            $providers[] = (string) $entry["name"];
        }
    }
}

echo "SSO_ACCOUNTS " . json_encode([
    "sociallogin" => [
        "providers" => $providers,
        "created" => array_column($marked->executeQuery()->fetchAll(), "userid"),
        "connected" => $rows("sociallogin_connect", ["uid", "identifier"]),
    ],
    "user_oidc" => array_column($rows("user_oidc", ["user_id"]), "user_id"),
    "ldap" => array_column($rows("ldap_user_mapping", ["owncloud_name"]), "owncloud_name"),
]) . "\n";
