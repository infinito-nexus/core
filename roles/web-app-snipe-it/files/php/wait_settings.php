<?php
// nocheck: mirrored-unit-test - boots Snipe-IT's Laravel kernel through
// bootstrap/app.php to ask whether the settings table is seeded; the exit code against
// a live install is the entire contract
// Probe whether Snipe-IT's `settings` table exists AND has been seeded.
// Exit 0 when ready; exit 1 otherwise. The Ansible task runs this in a
// retry loop until rc == 0 (or the retry budget is exhausted).
require "vendor/autoload.php";
$app = require "bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

if (
    Illuminate\Support\Facades\Schema::hasTable("settings")
    && \App\Models\Setting::query()->count() > 0
) {
    exit(0);
}
exit(1);
