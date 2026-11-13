<?php
// nocheck: mirrored-unit-test - boots Snipe-IT's Laravel kernel through bootstrap/app.php and reads or writes App\Models\Setting, which only exists once the install has booted
require "vendor/autoload.php";
$app = require "bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Models\Setting;

$mode = (string) getenv("SNIPE_IT_SETTINGS_MODE");
$wanted = json_decode(base64_decode((string) getenv("SNIPE_IT_SETTINGS"), true) ?: "null", true);
if (!in_array($mode, ["read", "write"], true)) {
    fwrite(STDERR, "SNIPE_IT_SETTINGS_MODE must be read or write\n");
    exit(2);
}
if (!is_array($wanted) || ($wanted !== [] && array_is_list($wanted))) {
    fwrite(STDERR, "SNIPE_IT_SETTINGS must be a base64 JSON object of Setting column to value\n");
    exit(2);
}

$settings = Setting::getSettings();
$columns = $settings->getAttributes();
$unknown = array_diff(array_keys($wanted), array_keys($columns));
if ($unknown !== []) {
    fwrite(STDERR, "the settings row has no column " . implode(", ", $unknown) . "\n");
    exit(3);
}

$drifted = [];
foreach ($wanted as $column => $value) {
    $stored = $settings->getRawOriginal($column);
    if (!is_scalar($value) && $value !== null) {
        fwrite(STDERR, "the value of {$column} must be a scalar\n");
        exit(2);
    }
    if ((string) $stored !== (string) $value) {
        $drifted[$column] = $stored;
    }
}

if ($mode === "read") {
    echo json_encode((object) $drifted, JSON_THROW_ON_ERROR);
    exit(0);
}

foreach (array_keys($drifted) as $column) {
    $settings->{$column} = $wanted[$column];
}
if ($drifted !== [] && !$settings->save()) {
    fwrite(STDERR, "the settings row was rejected: " . json_encode($settings->getErrors()) . "\n");
    exit(1);
}
echo $drifted === [] ? "unchanged" : "changed";
