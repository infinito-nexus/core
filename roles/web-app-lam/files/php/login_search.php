<?php

if ($argc !== 3) {
    fwrite(STDERR, "usage: login_search.php <served lam.conf> <unix.sample.conf>\n");
    exit(2);
}
[, $servedProfile, $sampleProfile] = $argv;

$patched = 0;
foreach ([$servedProfile, $sampleProfile] as $profile) {
    if (!is_file($profile)) {
        continue;
    }
    $config = json_decode(file_get_contents($profile), false, 512, JSON_THROW_ON_ERROR);
    $config->loginMethod = "search";
    $config->loginSearchSuffix = getenv("LAM_LOGIN_SEARCH_SUFFIX");
    $config->loginSearchFilter = getenv("LAM_LOGIN_SEARCH_FILTER");
    if (file_put_contents($profile, json_encode($config, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR) . "\n") === false) {
        fwrite(STDERR, "cannot write {$profile}\n");
        exit(1);
    }
    $patched++;
}
if ($patched === 0) {
    fwrite(STDERR, "neither the served profile {$servedProfile} nor the sample profile {$sampleProfile} exists\n");
    exit(1);
}
