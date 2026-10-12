<?php
// nocheck: mirrored-unit-test - evaluated by `wp eval-file -` inside a booted
// WordPress; every call it makes is a global that only the CLI runtime defines
/**
 * Realign the WordPress administrator password with the declared one.
 *
 * `wp core install` writes the password once and skips an installed site, so a
 * rotated secret never reaches the account without this.
 *
 * Env (from the container):
 *   WP_REALIGN_LOGIN     user_login of the administrator account
 *   WP_REALIGN_PASSWORD  password it must accept afterwards
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */
$login = getenv('WP_REALIGN_LOGIN');
$password = getenv('WP_REALIGN_PASSWORD');

if (!is_string($login) || $login === '' || !is_string($password) || $password === '') {
    fwrite(STDERR, "[FAIL] WP_REALIGN_LOGIN or WP_REALIGN_PASSWORD is empty\n");
    exit(1);
}

$user = get_user_by('login', $login);
if (!$user) {
    fwrite(STDERR, "[FAIL] no WordPress user named '$login'\n");
    exit(1);
}

if (wp_check_password($password, $user->user_pass, $user->ID)) {
    echo "[UNCHANGED] the WordPress administrator already accepts the declared password\n";
    exit(0);
}

wp_set_password($password, $user->ID);
echo "[CHANGED] the WordPress administrator was realigned with the declared password\n";
