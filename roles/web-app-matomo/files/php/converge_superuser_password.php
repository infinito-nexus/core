<?php

declare(strict_types=1);

namespace Infinito\Matomo\Superuser;

use PDO;
use Throwable;

/**
 * Ensure the Matomo superuser exists and accepts the password the deployment renders.
 *
 * Matomo stores `password_hash(md5($plain))`, not a hash of the plaintext
 * (plugins/UsersManager/API.php via core/Auth/Password.php), and PASSWORD_DEFAULT
 * is safe against a differing `password_hash_algorithm` because
 * `password_verify` accepts every algorithm Matomo can be configured with.
 *
 * Env (from the container):
 *   MATOMO_CONFIG             path of config.ini.php, for the table prefix
 *   MATOMO_DATABASE_HOST      host or host:port
 *   MATOMO_DATABASE_DBNAME    database holding the user table
 *   MATOMO_DATABASE_USERNAME  app user
 *   MATOMO_DATABASE_PASSWORD  app password
 *   MATOMO_SUPERUSER_LOGIN    login to create or realign
 *   MATOMO_SUPERUSER_PASSWORD password it must accept afterwards
 *   MATOMO_SUPERUSER_EMAIL    email a created superuser gets
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */
interface Users
{
    /**
     * @return array{password: string, superuser: bool}|null the account, null when the login is absent
     */
    public function find(string $login): ?array;

    public function superusers(): int;

    /**
     * @return list<string> logins other than $login whose email is $email, case-insensitively
     */
    public function holdersOf(string $email, string $login): array;

    public function insertSuperuser(string $login, string $hash, string $email): void;

    public function updatePassword(string $login, string $hash): void;
}

final class PdoUsers implements Users
{
    public function __construct(private PDO $pdo, private string $table)
    {
    }

    public function find(string $login): ?array
    {
        $read = $this->pdo->prepare("SELECT password, superuser_access FROM `{$this->table}` WHERE login = ?");
        $read->execute([$login]);
        $row = $read->fetch(PDO::FETCH_ASSOC);

        return $row === false ? null : ['password' => (string) $row['password'], 'superuser' => (int) $row['superuser_access'] === 1];
    }

    public function superusers(): int
    {
        return (int) $this->pdo->query("SELECT COUNT(*) FROM `{$this->table}` WHERE superuser_access = 1")->fetchColumn();
    }

    public function holdersOf(string $email, string $login): array
    {
        $read = $this->pdo->prepare("SELECT login FROM `{$this->table}` WHERE LOWER(email) = LOWER(?) AND login <> ?");
        $read->execute([$email, $login]);

        return array_map('strval', $read->fetchAll(PDO::FETCH_COLUMN));
    }

    public function insertSuperuser(string $login, string $hash, string $email): void
    {
        $this->pdo->prepare(
            "INSERT INTO `{$this->table}` (login, password, email, twofactor_secret, superuser_access, date_registered, ts_password_modified)"
            . " VALUES (?, ?, ?, '', 1, UTC_TIMESTAMP(), UTC_TIMESTAMP())"
        )->execute([$login, $hash, $email]);
    }

    public function updatePassword(string $login, string $hash): void
    {
        $this->pdo->prepare("UPDATE `{$this->table}` SET password = ?, ts_password_modified = UTC_TIMESTAMP() WHERE login = ?")
            ->execute([$hash, $login]);
    }
}

/**
 * @return array{0: int, 1: string} exit code and the [CHANGED], [UNCHANGED] or [FAIL] line
 */
function ensure(Users $users, string $login, string $password, string $email): array
{
    $account = $users->find($login);

    if ($account === null) {
        if ($users->superusers() === 0) {
            return [1, "[FAIL] Matomo has no superuser, so its install is unfinished; finish or reset that install instead of adding '$login' to it"];
        }
        $holders = $users->holdersOf($email, $login);
        if ($holders !== []) {
            return [1, sprintf("[FAIL] the email '%s' is held by the Matomo user %s; change that account's email, then redeploy", $email, implode(', ', $holders))];
        }
        $users->insertSuperuser($login, password_hash(md5($password), PASSWORD_DEFAULT), $email);

        return [0, "[CHANGED] the Matomo superuser '$login' was created with the declared password"];
    }

    if (!$account['superuser']) {
        return [1, "[FAIL] the Matomo user '$login' has no superuser access and is not promoted; grant it superuser access in Matomo or rename it, then redeploy"];
    }

    if (password_verify(md5($password), $account['password'])) {
        return [0, "[UNCHANGED] the Matomo superuser already accepts the declared password"];
    }

    $users->updatePassword($login, password_hash(md5($password), PASSWORD_DEFAULT));

    return [0, "[CHANGED] the Matomo superuser was realigned with the declared password"];
}

function required(string $name): string
{
    $value = getenv($name);
    if ($value === false || $value === '') {
        throw new \RuntimeException("$name is empty");
    }

    return $value;
}

function main(): int
{
    try {
        $configPath = required('MATOMO_CONFIG');
        $config = parse_ini_file($configPath, true);
        if ($config === false || !isset($config['database']['tables_prefix'])) {
            throw new \RuntimeException("$configPath carries no database.tables_prefix");
        }

        [$host, $port] = array_pad(explode(':', required('MATOMO_DATABASE_HOST')), 2, '3306');
        $pdo = new PDO(
            "mysql:host=$host;port=$port;dbname=" . required('MATOMO_DATABASE_DBNAME'),
            required('MATOMO_DATABASE_USERNAME'),
            required('MATOMO_DATABASE_PASSWORD'),
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );

        [$code, $line] = ensure(
            new PdoUsers($pdo, $config['database']['tables_prefix'] . 'user'),
            required('MATOMO_SUPERUSER_LOGIN'),
            required('MATOMO_SUPERUSER_PASSWORD'),
            required('MATOMO_SUPERUSER_EMAIL')
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
