<?php
// nocheck: mirrored-unit-test - boots Snipe-IT's Laravel kernel through bootstrap/app.php and writes the settings row
// of the live install; top-level procedural code with nothing to load without that install
require "vendor/autoload.php";
$app = require "bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

if (\App\Models\Setting::query()->exists()) {
    echo "unchanged\n";
    exit(0);
}

$settings = new \App\Models\Setting;
$settings->forceFill(json_decode(getenv('SNIPE_IT_INITIAL_SETTINGS'), true, 512, JSON_THROW_ON_ERROR));
if (! $settings->save()) {
    fwrite(STDERR, json_encode($settings->getErrors()) . "\n");
    exit(1);
}
echo "changed\n";
