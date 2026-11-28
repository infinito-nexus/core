<?php

declare(strict_types=1);

namespace Infinito\Matomo\Token;

use PDO;
use Throwable;

/**
 * Env (from the container):
 *   MATOMO_CONFIG             path of config.ini.php, for the table prefix and the salt
 *   MATOMO_DATABASE_HOST      host or host:port
 *   MATOMO_DATABASE_DBNAME    database holding the token table
 *   MATOMO_DATABASE_USERNAME  app user
 *   MATOMO_DATABASE_PASSWORD  app password
 *   MATOMO_TOKEN_LOGIN        superuser the token authenticates
 *   MATOMO_TOKEN_DESCRIPTION  description the token carries
 *
 * Exit: 0 with the token as the only stdout line, 1 with [FAIL] on stderr.
 */
interface Tokens
{
    public function isSuperuser(string $login): bool;

    public function insert(string $login, string $hash, string $description): void;
}

final class PdoTokens implements Tokens
{
    public function __construct(private PDO $pdo, private string $prefix)
    {
    }

    public function isSuperuser(string $login): bool
    {
        $read = $this->pdo->prepare("SELECT superuser_access FROM `{$this->prefix}user` WHERE login = ?");
        $read->execute([$login]);

        return (int) $read->fetchColumn() === 1;
    }

    public function insert(string $login, string $hash, string $description): void
    {
        $this->pdo->prepare(
            "INSERT INTO `{$this->prefix}user_token_auth`"
            . ' (login, description, password, date_created, date_expired, system_token, hash_algo, secure_only)'
            . " VALUES (?, ?, ?, UTC_TIMESTAMP(), NULL, 0, 'sha512', 0)"
        )->execute([$login, $description, $hash]);
    }
}

/**
 * @param string $salt [General] salt of config.ini.php, which Matomo appends before hashing a token
 *
 * @return array{0: int, 1: string} exit code and the token or the [FAIL] line
 */
function mint(Tokens $tokens, string $login, string $description, string $salt): array
{
    if (!$tokens->isSuperuser($login)) {
        return [1, "[FAIL] the Matomo user '$login' is no superuser, so a token minted for it would not serve the deploy"];
    }
    $token = bin2hex(random_bytes(16));
    $tokens->insert($login, hash('sha512', $token . $salt), $description);

    return [0, $token];
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
        if ($config === false || !isset($config['database']['tables_prefix'], $config['General']['salt']) || $config['General']['salt'] === '') {
            throw new \RuntimeException("$configPath carries no database.tables_prefix or General.salt");
        }

        [$host, $port] = array_pad(explode(':', required('MATOMO_DATABASE_HOST')), 2, '3306');
        $pdo = new PDO(
            "mysql:host=$host;port=$port;dbname=" . required('MATOMO_DATABASE_DBNAME'),
            required('MATOMO_DATABASE_USERNAME'),
            required('MATOMO_DATABASE_PASSWORD'),
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );

        [$code, $line] = mint(
            new PdoTokens($pdo, $config['database']['tables_prefix']),
            required('MATOMO_TOKEN_LOGIN'),
            required('MATOMO_TOKEN_DESCRIPTION'),
            $config['General']['salt']
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
