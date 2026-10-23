<?php
// nocheck: mirrored-unit-test - boots the Pixelfed Laravel runtime (vendor/autoload.php, bootstrap/app.php) that exists only inside the app container to compare and rewrite one user row; files/playwright/test-native-login-administrator.js asserts its effect on the live app

/**
 * Converge the Pixelfed administrator's password, so a rotated secret reaches an account that already exists.
 *
 * Environment:
 *   PIXELFED_APP_DIR:         application root inside the container
 *   PIXELFED_ADMIN_USERNAME:  username of the account to converge
 *   PIXELFED_ADMIN_PASSWORD:  password the account must accept
 *
 * Prints PASSWORD_KEPT or PASSWORD_SET as its last line.
 */

$appDir = getenv("PIXELFED_APP_DIR");
$username = getenv("PIXELFED_ADMIN_USERNAME");
$password = getenv("PIXELFED_ADMIN_PASSWORD");
if ($appDir === false || $appDir === "" || $username === false || $username === "" || $password === false || $password === "") {
    fwrite(STDERR, "PIXELFED_APP_DIR, PIXELFED_ADMIN_USERNAME and PIXELFED_ADMIN_PASSWORD are required\n");
    exit(1);
}

require $appDir . '/vendor/autoload.php';
$app = require $appDir . '/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

$user = App\Models\User::where('username', $username)->first();
if ($user === null) {
    fwrite(STDERR, "no Pixelfed user with username " . $username . "\n");
    exit(1);
}

if (Illuminate\Support\Facades\Hash::check($password, $user->password)) {
    echo "PASSWORD_KEPT\n";
    exit(0);
}

$user->password = Illuminate\Support\Facades\Hash::make($password);
$user->save();
echo "PASSWORD_SET\n";
