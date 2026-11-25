<?php
// nocheck: mirrored-unit-test - boots the live Pixelfed app and writes through its Passport tables; nothing here runs outside the container
// Args (environment):
//   PIXELFED_APP_DIR: Pixelfed's application directory in the container.
//   OPENPOST_CLIENT_ID: Passport client id of OpenPost's pinned Pixelfed app.
//   OPENPOST_CLIENT_OWNER: Pixelfed username that owns the client.
// Prints OWNER_SET when it changed the owner.

require getenv('PIXELFED_APP_DIR') . '/vendor/autoload.php';
$app = require getenv('PIXELFED_APP_DIR') . '/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

$owner = App\Models\User::where('username', getenv('OPENPOST_CLIENT_OWNER'))->firstOrFail();
$client = Laravel\Passport\Client::whereKey(getenv('OPENPOST_CLIENT_ID'))->firstOrFail();
if ((string) $client->user_id !== (string) $owner->id) {
    $client->forceFill(['user_id' => $owner->id])->save();
    echo 'OWNER_SET' . PHP_EOL;
}
