<?php
// nocheck: mirrored-unit-test - opens a connection to the live SuiteCRM database and rewrites
// the admin flag of its users; running it against that database is the whole behaviour
/**
 * Give the SuiteCRM admin flag to the members of the administrator group and take it from
 * every other user, the protected accounts excepted.
 *
 * Env of the container, from templates/env.j2:
 *   SUITECRM_DB_HOST, SUITECRM_DB_PORT, SUITECRM_DB_NAME, SUITECRM_DB_USER,
 *   SUITECRM_DB_PASSWORD
 *
 * Env passed with `container exec -e <name>`:
 *   SUITECRM_RBAC_ADMINS     JSON list of the usernames of the administrator group
 *   SUITECRM_RBAC_PROTECTED  JSON list of the usernames whose flag stays untouched
 *
 * Exit: 0 with one `CHANGED <username> is_admin=0|1` line per changed user or `UNCHANGED` on
 * stdout, 1 with [FAIL] on stderr.
 */

declare(strict_types=1);

function required(string $name): string
{
    $value = getenv($name);
    if ($value === false || $value === '') {
        fwrite(STDERR, "[FAIL] $name is empty\n");
        exit(1);
    }

    return $value;
}

function usernames(string $name): array
{
    $list = json_decode(required($name), true);
    if (!is_array($list)) {
        fwrite(STDERR, "[FAIL] $name is not a JSON list\n");
        exit(1);
    }

    return array_values(array_unique(array_map(static fn ($value): string => strtolower((string) $value), $list)));
}

$admins = usernames('SUITECRM_RBAC_ADMINS');
$protected = usernames('SUITECRM_RBAC_PROTECTED');
$keep = array_values(array_unique([...$admins, ...$protected]));

if ($protected === []) {
    fwrite(STDERR, "[FAIL] SUITECRM_RBAC_PROTECTED must name the platform administrator\n");
    exit(1);
}

$dsn = sprintf(
    'mysql:host=%s;port=%s;dbname=%s',
    required('SUITECRM_DB_HOST'),
    required('SUITECRM_DB_PORT'),
    required('SUITECRM_DB_NAME')
);

$lines = [];

try {
    $pdo = new PDO(
        $dsn,
        required('SUITECRM_DB_USER'),
        required('SUITECRM_DB_PASSWORD'),
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );

    $users = $pdo->query('SELECT id, user_name, is_admin FROM users WHERE deleted = 0 ORDER BY user_name')
        ->fetchAll(PDO::FETCH_ASSOC);
    $update = $pdo->prepare('UPDATE users SET is_admin = ? WHERE id = ?');

    foreach ($users as $user) {
        $username = strtolower((string) $user['user_name']);
        $admin = (int) $user['is_admin'] === 1;
        if (!$admin && in_array($username, $admins, true)) {
            $update->execute([1, $user['id']]);
            $lines[] = "CHANGED {$user['user_name']} is_admin=1";
        } elseif ($admin && !in_array($username, $keep, true)) {
            $update->execute([0, $user['id']]);
            $lines[] = "CHANGED {$user['user_name']} is_admin=0";
        }
    }
} catch (Throwable $error) {
    fwrite(STDERR, '[FAIL] ' . $error->getMessage() . "\n");
    exit(1);
}

echo ($lines === [] ? 'UNCHANGED' : implode("\n", $lines)) . "\n";
