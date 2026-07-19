<?php
// Configure Snipe-IT LDAP settings via the Laravel `Setting` model
// (same path the UI uses). All values are read from env vars passed
// through `compose exec -e` so credential strings never appear in the
// PHP literal.
require "vendor/autoload.php";
$app = require "bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Models\Setting;
use Illuminate\Support\Facades\Crypt;

$s = Setting::getSettings();

$ldap_server_uri          = getenv("LDAP_SERVER_URI") ?: "";
$ldap_server_port         = (int) (getenv("LDAP_SERVER_PORT") ?: 0);
$ldap_bind_dn             = getenv("LDAP_BIND_DN") ?: "";
$ldap_bind_password_b64   = getenv("LDAP_BIND_PASSWORD_B64") ?: "";
$ldap_basedn              = getenv("LDAP_BASEDN") ?: "";
$ldap_filter_users_all    = getenv("LDAP_FILTER_USERS_ALL") ?: "";
$ldap_user_id_attr        = getenv("LDAP_USER_ID_ATTR") ?: "";
$ldap_user_firstname_attr = getenv("LDAP_USER_FIRSTNAME_ATTR") ?: "";
$ldap_user_surname_attr   = getenv("LDAP_USER_SURNAME_ATTR") ?: "";
$ldap_auth_filter_query   = getenv("LDAP_AUTH_FILTER_QUERY") ?: "";
$ldap_user_mail_attr      = getenv("LDAP_USER_MAIL_ATTR") ?: "";
$oidc_reset_url           = getenv("OIDC_RESET_URL") ?: "";

$s->ldap_enabled           = 1;
$s->ldap_server            = $ldap_server_uri;
$s->ldap_port              = $ldap_server_port;
$s->ldap_uname             = $ldap_bind_dn;
$s->ldap_basedn            = $ldap_basedn;
$s->ldap_filter            = $ldap_filter_users_all;
$s->ldap_username_field    = $ldap_user_id_attr;
$s->ldap_fname_field       = $ldap_user_firstname_attr;
$s->ldap_lname_field       = $ldap_user_surname_attr;
$s->ldap_auth_filter_query = $ldap_auth_filter_query;
$s->ldap_version           = 3;
$s->ldap_pw_sync           = 0;
$s->is_ad                  = 0;
$s->ad_domain              = "";
$s->ldap_default_group     = "";

$decoded = base64_decode($ldap_bind_password_b64, true);
if ($decoded === false) {
    $decoded = "";
}
$s->ldap_pword = Crypt::encrypt($decoded);

$s->ldap_email             = $ldap_user_mail_attr;
$s->custom_forgot_pass_url = $oidc_reset_url;

$s->save();
