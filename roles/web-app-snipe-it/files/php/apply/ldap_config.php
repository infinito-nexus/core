<?php
// nocheck: mirrored-unit-test - boots Snipe-IT's Laravel kernel through bootstrap/app.php and writes the LDAP bind credential through App\Models\Setting with Crypt; the models only exist once the install has booted
require "vendor/autoload.php";
$app = require "bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Models\Setting;
use Illuminate\Contracts\Encryption\DecryptException;
use Illuminate\Support\Facades\Crypt;

$s = Setting::getSettings();

$ldap_server_port       = (int) (getenv("LDAP_SERVER_PORT") ?: 0);
$ldap_bind_password_b64 = getenv("LDAP_BIND_PASSWORD_B64") ?: "";

$decoded = base64_decode($ldap_bind_password_b64, true);
if ($decoded === false) {
    $decoded = "";
}

try {
    $stored = $s->ldap_pword === null ? null : Crypt::decrypt($s->ldap_pword);
} catch (DecryptException $e) {
    $stored = null;
}

$changed = false;
if ((int) $s->ldap_port !== $ldap_server_port) {
    $s->ldap_port = $ldap_server_port;
    $changed = true;
}
if ((int) $s->ldap_version !== 3) {
    $s->ldap_version = 3;
    $changed = true;
}
if (!is_string($stored) || !hash_equals($stored, $decoded)) {
    $s->ldap_pword = Crypt::encrypt($decoded);
    $changed = true;
}

if ($changed) {
    $s->save();
}
echo $changed ? "changed" : "unchanged";
