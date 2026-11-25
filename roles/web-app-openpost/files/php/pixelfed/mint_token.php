<?php
// nocheck: mirrored-unit-test - boots the live Pixelfed app and writes through its Passport tables; nothing here runs outside the container
// Args (environment):
//   PIXELFED_APP_DIR: Pixelfed's application directory in the container.
//   CROSSPOSTER_ACCOUNT: Pixelfed username the token belongs to.
// Prints CROSSPOSTER_TOKEN=<personal access token>.

require getenv('PIXELFED_APP_DIR') . '/vendor/autoload.php';
$app = require getenv('PIXELFED_APP_DIR') . '/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

$user = App\Models\User::where('username', getenv('CROSSPOSTER_ACCOUNT'))->firstOrFail();
$mint = fn () => $user->createToken('crossposter-ci', ['read', 'write'])->accessToken;
try {
    $token = $mint();
} catch (RuntimeException $missing) {
    Illuminate\Support\Facades\Artisan::call('passport:client', [
        '--personal' => true,
        '--provider' => 'users',
        '--name' => 'Crossposter CI',
        '--no-interaction' => true,
    ]);
    $token = $mint();
}
echo 'CROSSPOSTER_TOKEN=' . $token . PHP_EOL;
