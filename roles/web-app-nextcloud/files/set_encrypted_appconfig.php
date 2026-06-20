<?php

define("OC_CONSOLE", 1);

require_once "/var/www/html/lib/base.php";

$appId = getenv("NC_APP_ID");
$payload = getenv("NC_ENC_B64");

if ($appId === false || $appId === "" || $payload === false || $payload === "") {
    fwrite(STDERR, "NC_APP_ID and NC_ENC_B64 are required\n");
    exit(1);
}

$entries = json_decode(base64_decode($payload), true);
if (!is_array($entries)) {
    fwrite(STDERR, "NC_ENC_JSON must decode to a JSON object\n");
    exit(1);
}

$crypto = \OC::$server->get(\OCP\Security\ICrypto::class);
$appConfig = \OC::$server->get(\OCP\IAppConfig::class);

foreach ($entries as $key => $value) {
    $stored = ($value === "") ? "" : $crypto->encrypt((string) $value);
    $appConfig->setValueString($appId, (string) $key, $stored, lazy: true);
}

echo "OK\n";
