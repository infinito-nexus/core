<?php
// nocheck: mirrored-unit-test - opens a connection to the live SuiteCRM database and rewrites
// the administrator row; running it against that database is the whole behaviour
/**
 * Realign the SuiteCRM administrator password with the value the deployment renders.
 *
 * SuiteCRM 8 ships no console command for an existing user's password, so `users.user_hash`
 * is the handle. public/legacy/modules/Users/User.php fills it with
 * `password_hash(strtolower(md5($plain)), PASSWORD_DEFAULT)` and reads it back with
 * `password_verify(strtolower(md5($plain)), $hash)`: the md5 round is part of the stored
 * value, so hashing the plaintext directly would lock the administrator out. A 32 character
 * hash without a leading `$` is the pre-bcrypt column `checkPasswordMD5()` still compares
 * literally.
 *
 * Every failure is caught and reduced to its message: PHP's uncaught-exception trace carries
 * the call arguments unless `zend.exception_ignore_args` is on, and the official PHP images
 * activate no php.ini, so an uncaught throw would put the DSN credentials on stderr.
 *
 * Env of the container, from templates/env.j2:
 *   SUITECRM_DB_HOST, SUITECRM_DB_PORT, SUITECRM_DB_NAME, SUITECRM_DB_USER,
 *   SUITECRM_DB_PASSWORD
 *
 * Env passed with `container exec -e <name>` so it never reaches the host-side argv:
 *   SUITECRM_REALIGN_USERNAME  administrator login to realign
 *   SUITECRM_REALIGN_PASSWORD  password that login must accept afterwards
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
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

$username = required('SUITECRM_REALIGN_USERNAME');
$password = required('SUITECRM_REALIGN_PASSWORD');
$dsn = sprintf(
    'mysql:host=%s;port=%s;dbname=%s',
    required('SUITECRM_DB_HOST'),
    required('SUITECRM_DB_PORT'),
    required('SUITECRM_DB_NAME')
);
$digest = strtolower(md5($password));

try {
    $pdo = new PDO(
        $dsn,
        required('SUITECRM_DB_USER'),
        required('SUITECRM_DB_PASSWORD'),
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );

    $read = $pdo->prepare('SELECT id, user_hash FROM users WHERE user_name = ? AND deleted = 0');
    $read->execute([$username]);
    $row = $read->fetch(PDO::FETCH_ASSOC);

    if ($row === false) {
        fwrite(STDERR, "[FAIL] no SuiteCRM user named '$username'\n");
        exit(1);
    }

    $stored = (string) $row['user_hash'];
    $legacy = strlen($stored) === 32 && $stored[0] !== '$';
    if ($stored !== '' && ($legacy ? $stored === $digest : password_verify($digest, $stored))) {
        echo "[UNCHANGED] the SuiteCRM administrator already accepts the declared password\n";
        exit(0);
    }

    $write = $pdo->prepare(
        'UPDATE users SET user_hash = ?, pwd_last_changed = UTC_TIMESTAMP() WHERE id = ?'
    );
    $write->execute([password_hash($digest, PASSWORD_DEFAULT), $row['id']]);

    if ($write->rowCount() !== 1) {
        fwrite(STDERR, sprintf("[FAIL] the realign changed %d rows, expected exactly one\n", $write->rowCount()));
        exit(1);
    }
} catch (Throwable $error) {
    fwrite(STDERR, '[FAIL] ' . $error->getMessage() . "\n");
    exit(1);
}

echo "[CHANGED] the SuiteCRM administrator was realigned with the declared password\n";
