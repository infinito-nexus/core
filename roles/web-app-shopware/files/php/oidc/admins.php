<?php
/**
 * Withdraw the admin flag from every Keycloak-linked Shopware user that is
 * not a member of the administrator group, and the Editor ACL role from every
 * Keycloak-linked user that is not a member of the editor group.
 *
 * Required env:
 *   DATABASE_URL             connection string of the Shopware database (container env)
 *   RBAC_ADMINISTRATORS      JSON list of {username, email, name} of the administrator group
 *   RBAC_EDITORS             JSON list of {username, email, name} of the editor group
 *   SHOPWARE_RBAC_PROTECTED  JSON list of usernames and emails that keep the admin flag and the Editor role
 *   ACL_EDITOR_ROLE_NAME     name of the Editor ACL role
 *
 * Output: one "CHANGED <grant> withdrawn from <n> account(s)" line per withdrawn grant, else UNCHANGED.
 * Exit 1 with the reason on stderr when an input is missing.
 */

declare(strict_types=1);

function fail(string $message): never
{
    fwrite(STDERR, "{$message}\n");
    exit(1);
}

function json_list(string $key): array
{
    $raw = getenv($key);

    if ($raw === false || $raw === '') {
        fail("{$key} must be set");
    }

    $value = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);

    if (!is_array($value) || !array_is_list($value)) {
        fail("{$key} must be a JSON list");
    }

    return $value;
}

function keep_list(array $protected, array $members): array
{
    $keep = [
        ...$protected,
        ...array_column($members, 'username'),
        ...array_filter(array_column($members, 'email'), static fn ($email): bool => $email !== ''),
    ];

    return array_values(array_unique(array_map(static fn ($value): string => strtolower((string) $value), $keep)));
}

function withdraw(PDO $pdo, string $sql, array $keep, array $leading = []): int
{
    $placeholders = implode(', ', array_fill(0, count($keep), '?'));
    $statement = $pdo->prepare(str_replace('{keep}', $placeholders, $sql));
    $statement->execute([...$leading, ...$keep, ...$keep]);

    return $statement->rowCount();
}

$protected = json_list('SHOPWARE_RBAC_PROTECTED');

if ($protected === []) {
    fail('SHOPWARE_RBAC_PROTECTED must be a non-empty JSON list');
}

$keepAdmins = keep_list($protected, json_list('RBAC_ADMINISTRATORS'));
$keepEditors = keep_list($protected, json_list('RBAC_EDITORS'));
$editorRole = (string) getenv('ACL_EDITOR_ROLE_NAME');

if ($editorRole === '') {
    fail('ACL_EDITOR_ROLE_NAME must be set');
}

$url = parse_url((string) getenv('DATABASE_URL'));

if (!is_array($url) || !isset($url['host'], $url['path'], $url['user'], $url['pass'])) {
    fail('DATABASE_URL must name a user, a password, a host and a database');
}

$dsn = sprintf(
    'mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4',
    $url['host'],
    $url['port'] ?? 3306,
    ltrim($url['path'], '/')
);

$pdo = new PDO($dsn, rawurldecode($url['user']), rawurldecode($url['pass']), [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);

$admins = withdraw(
    $pdo,
    'UPDATE `user` SET admin = 0 WHERE admin = 1'
    . ' AND id IN (SELECT user_id FROM `heptacom_admin_open_auth_user_key`)'
    . ' AND LOWER(username) NOT IN ({keep})'
    . ' AND LOWER(email) NOT IN ({keep})',
    $keepAdmins
);

$editors = withdraw(
    $pdo,
    'DELETE aur FROM `acl_user_role` aur'
    . ' JOIN `acl_role` ar ON ar.id = aur.acl_role_id'
    . ' JOIN `user` u ON u.id = aur.user_id'
    . ' WHERE ar.name = ?'
    . ' AND u.id IN (SELECT user_id FROM `heptacom_admin_open_auth_user_key`)'
    . ' AND LOWER(u.username) NOT IN ({keep})'
    . ' AND LOWER(u.email) NOT IN ({keep})',
    $keepEditors,
    [$editorRole]
);

if ($admins > 0) {
    echo "CHANGED admin flag withdrawn from {$admins} account(s)\n";
}

if ($editors > 0) {
    echo "CHANGED {$editorRole} role withdrawn from {$editors} account(s)\n";
}

if ($admins + $editors === 0) {
    echo "UNCHANGED\n";
}
