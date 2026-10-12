<?php
// nocheck: mirrored-unit-test - rewrites the live Snipe-IT user row through the
// application's own bootstrap; running it is the whole behaviour
/**
 * Realign the Snipe-IT administrator password with the value the deployment renders.
 *
 * Env (from the container):
 *   SNIPE_IT_REALIGN_USERNAME  login to realign
 *   SNIPE_IT_REALIGN_PASSWORD  password it must accept afterwards
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */
function required(string $name): string
{
    $value = getenv($name);
    if ($value === false || $value === '') {
        fwrite(STDERR, "[FAIL] $name is empty\n");
        exit(1);
    }
    return $value;
}

$username = required('SNIPE_IT_REALIGN_USERNAME');
$password = required('SNIPE_IT_REALIGN_PASSWORD');

try {
    require 'vendor/autoload.php';
    $app = require 'bootstrap/app.php';
    $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

    $user = \App\Models\User::where('username', $username)->whereNull('deleted_at')->first();
    if (!$user) {
        fwrite(STDERR, "[FAIL] no Snipe-IT user named '$username'\n");
        exit(1);
    }

    if (\Illuminate\Support\Facades\Hash::check($password, $user->password)) {
        echo "[UNCHANGED] the Snipe-IT administrator already accepts the declared password\n";
        exit(0);
    }

    $user->password = \Illuminate\Support\Facades\Hash::make($password);
    $user->save();
    echo "[CHANGED] the Snipe-IT administrator was realigned with the declared password\n";
} catch (Throwable $error) {
    fwrite(STDERR, '[FAIL] ' . $error->getMessage() . "\n");
    exit(1);
}
