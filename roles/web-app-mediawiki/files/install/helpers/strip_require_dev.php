<?php

/**
 * Strip require-dev from a composer.json in place.
 *
 * The extension tarballs ship no composer.lock, so `composer install` degrades
 * to a full solve that still honours require-dev even under --no-dev, and a
 * security advisory against any dev-only linter then blocks the whole
 * resolution. Dropping require-dev before composer sees it keeps the solve on
 * the runtime constraints only.
 *
 * Decodes to objects, not associative arrays: an empty JSON object would
 * otherwise round-trip into an empty array and composer rejects `[]` where its
 * schema wants `{}`.
 *
 * Usage: php strip_require_dev.php <composer.json>
 *
 * Exit codes: 0 rewritten or nothing to do, 1 unusable manifest, 2 bad usage.
 */

declare(strict_types=1);

$path = $argv[1] ?? '';
if ($path === '') {
    fwrite(STDERR, "usage: strip_require_dev.php <composer.json>\n");
    exit(2);
}

$raw = file_get_contents($path);
if ($raw === false) {
    fwrite(STDERR, "cannot read {$path}\n");
    exit(1);
}

$manifest = json_decode($raw);
if (!$manifest instanceof stdClass) {
    fwrite(STDERR, "{$path} is not a JSON object\n");
    exit(1);
}

if (!property_exists($manifest, 'require-dev')) {
    echo "STRIP_REQUIRE_DEV_ABSENT\n";
    exit(0);
}

unset($manifest->{'require-dev'});

$encoded = json_encode(
    $manifest,
    JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
);
if ($encoded === false) {
    fwrite(STDERR, "cannot re-encode {$path}\n");
    exit(1);
}

if (file_put_contents($path, $encoded . "\n") === false) {
    fwrite(STDERR, "cannot write {$path}\n");
    exit(1);
}

echo "STRIP_REQUIRE_DEV_REMOVED\n";
