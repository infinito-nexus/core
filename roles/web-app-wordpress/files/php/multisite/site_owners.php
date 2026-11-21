<?php
// nocheck: mirrored-unit-test - drives the own-site functions of the mapper mu-plugin, which exist only inside a booted network
/**
 * Environment:
 *   WP_SITE_OWNER_LOGINS: comma-separated logins of the inventory site-owner members whose own site the deploy reserves.
 *   WP_SITE_OWNER_MEMBERS: comma-separated logins of every inventory site-owner member; a reserved site of anyone else is archived.
 *   WP_MS_ADMIN_EMAIL: email of the user who administers every site this run creates until its member claims it.
 *
 * Output:
 *   "CHANGED <login>" once per own site this run created or archived.
 */

$logins = getenv('WP_SITE_OWNER_LOGINS');
$members = getenv('WP_SITE_OWNER_MEMBERS');
if ($logins === false || $members === false) {
    WP_CLI::error('WP_SITE_OWNER_LOGINS and WP_SITE_OWNER_MEMBERS must be set');
}
$owner = get_user_by('email', (string) getenv('WP_MS_ADMIN_EMAIL'));
if (!$owner) {
    WP_CLI::error('WP_MS_ADMIN_EMAIL names no user');
}

try {
    foreach (preg_split('/,/', $logins, -1, PREG_SPLIT_NO_EMPTY) as $login) {
        if (infinito_rbac_reserve_own_site($login, (int) $owner->ID)) {
            WP_CLI::log('CHANGED ' . $login);
        }
    }
    $archived = infinito_rbac_archive_reserved_sites_of_former_members(
        preg_split('/,/', $members, -1, PREG_SPLIT_NO_EMPTY)
    );
} catch (RuntimeException $error) {
    WP_CLI::error($error->getMessage());
}
foreach ($archived as $login) {
    WP_CLI::log('CHANGED ' . $login);
}
