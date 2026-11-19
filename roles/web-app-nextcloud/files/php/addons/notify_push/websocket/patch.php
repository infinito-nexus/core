<?php

[, $capabilities] = $argv;

$storedEndpoint = "\$wsEndpoint = str_replace('https://', 'wss://', \$baseEndpoint);";
$requestEndpoint = "\$wsEndpoint = str_replace('https://', 'wss://', "
    . "\$this->urlGenerator->getAbsoluteURL((string) parse_url(\$baseEndpoint, PHP_URL_PATH)));";

$source = file_get_contents($capabilities);
if ($source === false) {
    fwrite(STDERR, "cannot read {$capabilities}\n");
    exit(1);
}

if (!str_contains($source, $storedEndpoint)) {
    exit(0);
}

if (file_put_contents($capabilities, str_replace($storedEndpoint, $requestEndpoint, $source)) === false) {
    fwrite(STDERR, "cannot write {$capabilities}\n");
    exit(1);
}

echo "PATCHED\n";
