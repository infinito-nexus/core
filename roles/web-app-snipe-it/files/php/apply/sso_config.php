<?php
// nocheck: mirrored-unit-test - boots Snipe-IT's Laravel kernel through
// bootstrap/app.php and writes the trusted-reverse-proxy login settings through
// App\Models\Setting; the models only exist once the install has booted
require "vendor/autoload.php";
$app = require "bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Models\Setting;

$s = Setting::getSettings();

$remote_user_enabled     = (getenv("SNIPE_IT_SSO_ENABLED") === "1") ? 1 : 0;
$remote_user_header_name = getenv("SNIPE_IT_SSO_HEADER_NAME") ?: "REMOTE_USER";
$remote_user_logout_url  = getenv("SNIPE_IT_SSO_LOGOUT_URL") ?: "";

$s->login_remote_user_enabled          = $remote_user_enabled;
$s->login_remote_user_header_name      = $remote_user_header_name;
$s->login_remote_user_custom_logout_url = $remote_user_logout_url;
$s->login_common_disabled              = 0;

$s->save();
