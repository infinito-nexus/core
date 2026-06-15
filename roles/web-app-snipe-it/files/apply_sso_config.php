<?php
// Configure Snipe-IT trusted-reverse-proxy login via the Laravel `Setting`
// model (same path the UI uses). The oauth2-proxy in front of Snipe-IT
// authenticates the user against Keycloak and nginx injects the verified
// identity into the `X-Forwarded-Preferred-Username` request header, which
// PHP exposes as $_SERVER['HTTP_X_FORWARDED_PREFERRED_USERNAME'].
// LoginController::loginViaRemoteUser() then matches users.username and mints
// a native snipeit_session. The password/LDAP form stays available as a
// fallback (login_common_disabled is kept at 0).
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
