<?php
// nocheck: mirrored-unit-test - boots the Pixelfed Laravel runtime (vendor/autoload.php, bootstrap/app.php, ConfigCacheService) that exists only inside the app container; files/playwright/test-design.js asserts its effects on the live app

/**
 * Converge the role's block inside Pixelfed's custom CSS setting, keeping an administrator's own CSS around it, and the site name. Fed to `php` on stdin behind one line that defines $DESIGN_PAYLOAD (Base64 of JSON).
 *
 * Payload keys:
 *   mode:    "read" prints the stored site name and whether "converge" would write anything, as one JSON line, and writes nothing; "converge" writes
 *   app_dir: application root inside the container
 *   css:     the role's block without markers; empty removes the block an earlier run wrote
 *   begin:   marker line that opens the role's block
 *   end:     marker line that closes the role's block
 *   title:   site name stored as app.name; empty leaves the stored one alone
 *
 * In "converge" mode it prints DESIGN_CHANGED or DESIGN_UNCHANGED as its last line.
 */

$payload = json_decode(base64_decode($DESIGN_PAYLOAD), true);
if (!is_array($payload) || !in_array($payload['mode'] ?? null, ['read', 'converge'], true)) {
    fwrite(STDERR, "design payload is not valid JSON with a read or converge mode\n");
    exit(2);
}

require $payload['app_dir'] . '/vendor/autoload.php';
$app = require $payload['app_dir'] . '/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

$cssKey = 'uikit.custom.css';
$showKey = 'uikit.show_custom.css';
$titleKey = 'app.name';
$begin = (string) $payload['begin'];
$end = (string) $payload['end'];
$block = trim((string) $payload['css']);
$title = (string) $payload['title'];

$current = (string) App\Services\ConfigCacheService::get($cssKey);
$shown = (bool) App\Services\ConfigCacheService::get($showKey);
$storedTitle = (string) App\Services\ConfigCacheService::get($titleKey);
$pattern = '/\s*' . preg_quote($begin, '/') . '.*?' . preg_quote($end, '/') . '\s*/s';
$own = trim((string) preg_replace($pattern, "\n", $current));
$wanted = $block === '' ? $own : trim($own . "\n" . $begin . "\n" . $block . "\n" . $end);
$wantShown = $block === '' ? ($own !== '' && $shown) : ($own === '' || $shown);

$writes = [];
if ($wanted !== $current) {
    $writes[$cssKey] = $wanted;
}
if ($wantShown !== $shown) {
    $writes[$showKey] = $wantShown;
}
if ($title !== '' && $storedTitle !== $title) {
    $writes[$titleKey] = $title;
}

if ($payload['mode'] === 'read') {
    echo json_encode(['site_name' => $storedTitle, 'pending' => $writes !== []]) . "\n";
    exit(0);
}

foreach ($writes as $key => $value) {
    App\Services\ConfigCacheService::put($key, $value);
}

echo $writes === [] ? "DESIGN_UNCHANGED\n" : "DESIGN_CHANGED\n";
