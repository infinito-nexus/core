<?php

[, $serverRoot, $origin, $location] = $argv;

$scheme = parse_url($origin, PHP_URL_SCHEME);
$host = parse_url($origin, PHP_URL_HOST);
$_SERVER["HTTP_HOST"] = $host;
if ($scheme === "https") {
    $_SERVER["HTTPS"] = "on";
}

define("OC_CONSOLE", 1);

require_once $serverRoot . "/lib/base.php";

\OCP\Server::get(\OCP\App\IAppManager::class)->loadApp("notify_push");
$capabilities = \OCP\Server::get(\OCA\NotifyPush\Capabilities::class);
\OC::$CLI = false;
$announced = $capabilities->getCapabilities()["notify_push"]["endpoints"]["websocket"] ?? "";

$expected = ($scheme === "https" ? "wss" : "ws") . "://{$host}" . rtrim($location, "/") . "/ws";
if ($announced !== $expected) {
    fwrite(STDERR, "{$origin} announces the push websocket '{$announced}' instead of {$expected}\n");
    exit(1);
}

echo "OK {$expected}\n";
