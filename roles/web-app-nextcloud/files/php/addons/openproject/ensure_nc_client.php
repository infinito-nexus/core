<?php
// nocheck: mirrored-unit-test - needs a booted Nextcloud with integration_openproject enabled, which only exists inside the container

define("OC_CONSOLE", 1);

[, $serverRoot, $openProjectUrl, $clientName, $storedId] = $argv;

require_once $serverRoot . "/lib/base.php";

$apps = \OCP\Server::get(\OCP\App\IAppManager::class);
$apps->loadApp("oauth2");
$apps->loadApp("integration_openproject");

$oauth =\OCP\Server::get(\OCA\OpenProject\Service\OauthService::class);
$clients = \OCP\Server::get(\OCA\OAuth2\Service\ClientService::class);
$mapper = \OCP\Server::get(\OCA\OAuth2\Db\ClientMapper::class);

$openProjectUrl = rtrim($openProjectUrl, "/");
$current = ctype_digit($storedId) ? $oauth->getClientInfo((int) $storedId) : null;

if ($current === null) {
    $created = $oauth->createNcOauthClient($clientName, $openProjectUrl . "/oauth_clients/%s/callback");
    $state = [
        "action" => "created",
        "id" => (int) $created["id"],
        "client_id" => $created["nextcloud_client_id"],
        "client_secret" => $created["nextcloud_client_secret"],
    ];
} else {
    $expected = $openProjectUrl . "/oauth_clients/" . $current["nextcloud_client_id"] . "/callback";
    $state = [
        "action" => $current["openproject_redirect_uri"] === $expected ? "unchanged" : "redirect_fixed",
        "id" => (int) $current["id"],
        "client_id" => $current["nextcloud_client_id"],
    ];
    if ($state["action"] === "redirect_fixed") {
        $oauth->setClientRedirectUri($state["id"], $openProjectUrl);
    }
}

$removed = 0;
foreach ($mapper->getClients() as $client) {
    if ($client->getName() === $clientName && (int) $client->getId() !== $state["id"]) {
        $clients->deleteClient((int) $client->getId());
        $removed++;
    }
}
$state["removed"] = $removed;

echo "NC_OAUTH_CLIENT " . json_encode($state) . "\n";
