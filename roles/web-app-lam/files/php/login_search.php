<?php
// nocheck: mirrored-unit-test - procedural script the container entrypoint runs on the image's unix.sample.conf at start; it reads argv and the container environment and exits, so there is no unit to load

$file = $argv[1];
$config = json_decode(file_get_contents($file), false, 512, JSON_THROW_ON_ERROR);
$config->loginMethod = "search";
$config->loginSearchSuffix = getenv("LAM_LOGIN_SEARCH_SUFFIX");
$config->loginSearchFilter = getenv("LAM_LOGIN_SEARCH_FILTER");
if (file_put_contents($file, json_encode($config, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR) . "\n") === false) {
    fwrite(STDERR, "cannot write {$file}\n");
    exit(1);
}
