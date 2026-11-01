<?php
/**
 * Ensure the WordPress administrator exists and accepts the declared password.
 *
 * `wp core install` writes the password once and skips an installed site, so a
 * rotated secret never reaches the account without this.
 *
 * Env (from the container):
 *   WP_REALIGN_LOGIN     user_login of the administrator account
 *   WP_REALIGN_PASSWORD  password it must accept afterwards
 *   WP_REALIGN_EMAIL     user_email a created administrator gets
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */
$login = getenv('WP_REALIGN_LOGIN');
$password = getenv('WP_REALIGN_PASSWORD');
$email = getenv('WP_REALIGN_EMAIL');

foreach (['WP_REALIGN_LOGIN' => $login, 'WP_REALIGN_PASSWORD' => $password, 'WP_REALIGN_EMAIL' => $email] as $name => $value) {
    if (!is_string($value) || $value === '') {
        file_put_contents('php://stderr', "[FAIL] $name is empty\n");
        exit(1);
    }
}

$is_administrator = static function ($account): bool {
    return in_array('administrator', (array) $account->roles, true)
        || (is_multisite() && is_super_admin($account->ID));
};

$user = get_user_by('login', $login);

if (!$user) {
    $administrators = get_users(['role' => 'administrator', 'fields' => 'ID', 'number' => 1]);
    if ($administrators === [] && (!is_multisite() || get_super_admins() === [])) {
        file_put_contents('php://stderr', "[FAIL] WordPress has no administrator, so its install is unfinished; finish or reset that install instead of adding '$login' to it\n");
        exit(1);
    }

    $holder = get_user_by('email', $email);
    if ($holder) {
        file_put_contents('php://stderr', "[FAIL] the email '$email' is held by the WordPress user {$holder->user_login}; change that user's email, then redeploy\n");
        exit(1);
    }

    $id = wp_insert_user([
        'user_login' => $login,
        'user_email' => $email,
        'user_pass' => $password,
        'role' => 'administrator',
    ]);
    if (is_wp_error($id)) {
        file_put_contents('php://stderr', "[FAIL] WordPress refused to create '$login': " . $id->get_error_message() . "\n");
        exit(1);
    }
    if (is_multisite()) {
        grant_super_admin($id);
    }

    echo "[CHANGED] the WordPress administrator '$login' was created with the declared password\n";
    exit(0);
}

if (!$is_administrator($user)) {
    file_put_contents('php://stderr', "[FAIL] the WordPress user '$login' is no administrator and is not promoted; give it the administrator role or rename it, then redeploy\n");
    exit(1);
}

if (wp_check_password($password, $user->user_pass, $user->ID)) {
    echo "[UNCHANGED] the WordPress administrator already accepts the declared password\n";
    exit(0);
}

wp_set_password($password, $user->ID);
echo "[CHANGED] the WordPress administrator was realigned with the declared password\n";
