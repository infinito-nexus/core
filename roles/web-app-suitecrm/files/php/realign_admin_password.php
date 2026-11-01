<?php
/**
 * Ensure the SuiteCRM administrator exists and accepts the password the deployment renders.
 *
 * SuiteCRM 8 ships no console command for an existing user's password, so `users.user_hash`
 * is the handle. public/legacy/modules/Users/User.php fills it with
 * `password_hash(strtolower(md5($plain)), PASSWORD_DEFAULT)` and reads it back with
 * `password_verify(strtolower(md5($plain)), $hash)`: the md5 round is part of the stored
 * value, so hashing the plaintext directly would lock the administrator out. A 32 character
 * hash without a leading `$` is the pre-bcrypt column `checkPasswordMD5()` still compares
 * literally.
 *
 * SuiteCRM 8 has no console command to add a user either, and this script does not boot the
 * legacy bean layer, so a missing administrator is written as the rows `User::save()` and
 * `EmailAddress::addAddress()` produce: one `users` row, the `email_addresses` row of its
 * address (reused when another record already carries it) and the `email_addr_bean_rel` link.
 *
 * Every exception or error thrown inside main()'s try block (env, connection, queries) is
 * caught and reduced to its message: PHP's uncaught-exception trace carries the call
 * arguments unless `zend.exception_ignore_args` is on, and the official PHP images activate
 * no php.ini, so an uncaught throw would put the DSN credentials on stderr. A parse error or
 * a fatal raised outside that block still ends the run with php's own message and exit 255.
 *
 * Env of the container, from templates/env.j2:
 *   SUITECRM_DB_HOST, SUITECRM_DB_PORT, SUITECRM_DB_NAME, SUITECRM_DB_USER,
 *   SUITECRM_DB_PASSWORD
 *
 * Env passed with `container exec -e <name>` so it never reaches the host-side argv:
 *   SUITECRM_REALIGN_USERNAME  administrator login to create or realign
 *   SUITECRM_REALIGN_PASSWORD  password that login must accept afterwards
 *   SUITECRM_REALIGN_EMAIL     primary email a created administrator gets
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 *
 * php reads the script from stdin, so no path tells a direct run from a test's require:
 * main() runs only when debug_backtrace() finds no including frame. For the same reason
 * the CLI defines no STDOUT/STDERR constants (php_cli.c registers them only for a script
 * file), so output goes through php://stdout and php://stderr.
 */

declare(strict_types=1);

namespace Infinito\SuiteCrm\Administrator;

use PDO;
use RuntimeException;
use Throwable;

interface Users
{
    /**
     * @return list<array{id: string, hash: string, admin: bool}> every undeleted account with the login; user_name is not unique
     */
    public function find(string $login): array;

    public function administrators(): int;

    /**
     * @return list<string> logins other than $login of undeleted users linked to $email, case-insensitively
     */
    public function holdersOf(string $email, string $login): array;

    public function insertAdministrator(string $login, string $hash, string $email): void;

    /**
     * @return list<string> addresses linked to the user, empty for an LDAP-created account
     */
    public function emailsOf(string $id): array;

    public function updateHash(string $id, string $hash): void;
}

final class PdoUsers implements Users
{
    public function __construct(private PDO $pdo)
    {
    }

    public function find(string $login): array
    {
        $read = $this->pdo->prepare('SELECT id, user_hash, is_admin FROM users WHERE user_name = ? AND deleted = 0');
        $read->execute([$login]);

        return array_map(
            static fn (array $row): array => ['id' => (string) $row['id'], 'hash' => (string) $row['user_hash'], 'admin' => (int) $row['is_admin'] === 1],
            $read->fetchAll(PDO::FETCH_ASSOC)
        );
    }

    public function administrators(): int
    {
        return (int) $this->pdo->query('SELECT COUNT(*) FROM users WHERE is_admin = 1 AND deleted = 0')->fetchColumn();
    }

    public function holdersOf(string $email, string $login): array
    {
        $read = $this->pdo->prepare(
            'SELECT DISTINCT u.user_name FROM users u'
            . " JOIN email_addr_bean_rel r ON r.bean_id = u.id AND r.bean_module = 'Users' AND r.deleted = 0"
            . ' JOIN email_addresses e ON e.id = r.email_address_id AND e.deleted = 0'
            . ' WHERE u.deleted = 0 AND e.email_address_caps = ? AND u.user_name <> ?'
        );
        $read->execute([strtoupper($email), $login]);

        return array_map('strval', $read->fetchAll(PDO::FETCH_COLUMN));
    }

    public function insertAdministrator(string $login, string $hash, string $email): void
    {
        $userId = guid();
        $this->pdo->beginTransaction();
        try {
            $this->pdo->prepare(
                'INSERT INTO users (id, user_name, user_hash, system_generated_password, pwd_last_changed, sugar_login,'
                . ' first_name, last_name, is_admin, external_auth_only, receive_notifications, date_entered,'
                . ' date_modified, modified_user_id, created_by, status, deleted, portal_only, show_on_employees,'
                . ' employee_status, is_group, factor_auth)'
                . " VALUES (?, ?, ?, 0, UTC_TIMESTAMP(), 1, '', ?, 1, 0, 1, UTC_TIMESTAMP(), UTC_TIMESTAMP(), ?, ?,"
                . " 'Active', 0, 0, 1, 'Active', 0, 0)"
            )->execute([$userId, $login, $hash, $login, $userId, $userId]);

            $find = $this->pdo->prepare('SELECT id FROM email_addresses WHERE email_address_caps = ? AND deleted = 0 LIMIT 1');
            $find->execute([strtoupper($email)]);
            $addressId = $find->fetchColumn();
            if ($addressId === false) {
                $addressId = guid();
                $this->pdo->prepare(
                    'INSERT INTO email_addresses (id, email_address, email_address_caps, invalid_email, opt_out,'
                    . " confirm_opt_in, date_created, date_modified, deleted) VALUES (?, ?, ?, 0, 0, 'not-opt-in',"
                    . ' UTC_TIMESTAMP(), UTC_TIMESTAMP(), 0)'
                )->execute([$addressId, $email, strtoupper($email)]);
            }

            $this->pdo->prepare(
                'INSERT INTO email_addr_bean_rel (id, email_address_id, bean_id, bean_module, primary_address,'
                . " reply_to_address, date_created, date_modified, deleted) VALUES (?, ?, ?, 'Users', 1, 0,"
                . ' UTC_TIMESTAMP(), UTC_TIMESTAMP(), 0)'
            )->execute([guid(), (string) $addressId, $userId]);

            $this->pdo->commit();
        } catch (Throwable $error) {
            $this->pdo->rollBack();
            throw $error;
        }
    }

    public function updateHash(string $id, string $hash): void
    {
        $write = $this->pdo->prepare('UPDATE users SET user_hash = ?, pwd_last_changed = UTC_TIMESTAMP() WHERE id = ?');
        $write->execute([$hash, $id]);
        if ($write->rowCount() !== 1) {
            throw new RuntimeException(sprintf('the realign changed %d rows, expected exactly one', $write->rowCount()));
        }
    }

    public function emailsOf(string $id): array
    {
        $read = $this->pdo->prepare(
            'SELECT e.email_address FROM email_addr_bean_rel r'
            . ' JOIN email_addresses e ON e.id = r.email_address_id AND e.deleted = 0'
            . " WHERE r.bean_id = ? AND r.bean_module = 'Users' AND r.deleted = 0"
        );
        $read->execute([$id]);

        return array_map('strval', $read->fetchAll(PDO::FETCH_COLUMN));
    }
}

function guid(): string
{
    $hex = bin2hex(random_bytes(16));

    return sprintf('%s-%s-%s-%s-%s', substr($hex, 0, 8), substr($hex, 8, 4), substr($hex, 12, 4), substr($hex, 16, 4), substr($hex, 20));
}

/**
 * @return string why the non-administrator holding the login says nothing about who owns it
 */
function emailDetail(Users $users, string $id, string $email): string
{
    $emails = $users->emailsOf($id);
    if ($emails === []) {
        return 'it carries no email address, like every account the LDAP login creates';
    }
    if (!in_array(strtoupper($email), array_map('strtoupper', $emails), true)) {
        return sprintf("its email %s differs from '%s'", implode(', ', $emails), $email);
    }

    return 'every SuiteCRM user may edit their own name and email, so a matching email proves nothing';
}

/**
 * @return array{0: int, 1: string} exit code and the [CHANGED], [UNCHANGED] or [FAIL] line
 */
function ensure(Users $users, string $login, string $password, string $email): array
{
    $digest = strtolower(md5($password));
    $accounts = $users->find($login);

    if (count($accounts) > 1) {
        return [1, sprintf("[FAIL] %d undeleted SuiteCRM users carry the login '%s'; delete or rename all but one, then redeploy", count($accounts), $login)];
    }

    $account = $accounts[0] ?? null;
    if ($account === null) {
        if ($users->administrators() === 0) {
            return [1, "[FAIL] SuiteCRM has no administrator, so its install is unfinished; finish or reset that install instead of adding '$login' to it"];
        }
        $holders = $users->holdersOf($email, $login);
        if ($holders !== []) {
            return [1, sprintf("[FAIL] the email '%s' is held by the SuiteCRM user %s; change that user's email, then redeploy", $email, implode(', ', $holders))];
        }
        $users->insertAdministrator($login, password_hash($digest, PASSWORD_DEFAULT), $email);

        return [0, "[CHANGED] the SuiteCRM administrator '$login' was created with the declared password"];
    }

    if (!$account['admin']) {
        return [1, sprintf(
            "[FAIL] the SuiteCRM user '%s' is no administrator and is not promoted (%s); make it an administrator in SuiteCRM or rename it, then redeploy",
            $login,
            emailDetail($users, $account['id'], $email)
        )];
    }

    $stored = $account['hash'];
    $legacy = strlen($stored) === 32 && $stored[0] !== '$';
    if ($stored !== '' && ($legacy ? $stored === $digest : password_verify($digest, $stored))) {
        return [0, '[UNCHANGED] the SuiteCRM administrator already accepts the declared password'];
    }

    $users->updateHash($account['id'], password_hash($digest, PASSWORD_DEFAULT));

    return [0, '[CHANGED] the SuiteCRM administrator was realigned with the declared password'];
}

function required(string $name): string
{
    $value = getenv($name);
    if ($value === false || $value === '') {
        throw new RuntimeException("$name is empty");
    }

    return $value;
}

function main(): int
{
    try {
        $pdo = new PDO(
            sprintf('mysql:host=%s;port=%s;dbname=%s', required('SUITECRM_DB_HOST'), required('SUITECRM_DB_PORT'), required('SUITECRM_DB_NAME')),
            required('SUITECRM_DB_USER'),
            required('SUITECRM_DB_PASSWORD'),
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );

        [$code, $line] = ensure(
            new PdoUsers($pdo),
            required('SUITECRM_REALIGN_USERNAME'),
            required('SUITECRM_REALIGN_PASSWORD'),
            required('SUITECRM_REALIGN_EMAIL')
        );
    } catch (Throwable $error) {
        [$code, $line] = [1, '[FAIL] ' . $error->getMessage()];
    }

    file_put_contents($code === 0 ? 'php://stdout' : 'php://stderr', $line . "\n");

    return $code;
}

if (!debug_backtrace()) {
    exit(main());
}
