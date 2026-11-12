<?php

declare(strict_types=1);

namespace Infinito\Matomo\TwoFactor;

use PDO;
use Throwable;

/**
 * Env (from the container):
 *   MATOMO_CONFIG             path of config.ini.php, for the table prefix
 *   MATOMO_DATABASE_HOST      host or host:port
 *   MATOMO_DATABASE_DBNAME    database holding the settings
 *   MATOMO_DATABASE_USERNAME  app user
 *   MATOMO_DATABASE_PASSWORD  app password
 *   MATOMO_TWO_FACTOR_MODE    enforced, offered or off
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */
interface Settings
{
    public function required(): bool;

    public function setRequired(bool $required): void;

    public function owned(): bool;

    public function setOwned(bool $owned): void;
}

final class PdoSettings implements Settings
{
    private const PLUGIN = 'TwoFactorAuth';

    private const SETTING = 'twoFactorAuthRequired';

    private const MARKER = 'InfinitoTwoFactorAuthRequiredByDeploy';

    public function __construct(private PDO $pdo, private string $prefix)
    {
    }

    public function required(): bool
    {
        $read = $this->pdo->prepare(
            "SELECT setting_value FROM `{$this->prefix}plugin_setting` WHERE plugin_name = ? AND setting_name = ? AND user_login = ''"
        );
        $read->execute([self::PLUGIN, self::SETTING]);

        return in_array('1', array_map('strval', $read->fetchAll(PDO::FETCH_COLUMN)), true);
    }

    public function setRequired(bool $required): void
    {
        $this->pdo->prepare(
            "DELETE FROM `{$this->prefix}plugin_setting` WHERE plugin_name = ? AND setting_name = ? AND user_login = ''"
        )->execute([self::PLUGIN, self::SETTING]);
        if ($required) {
            $this->pdo->prepare(
                "INSERT INTO `{$this->prefix}plugin_setting` (plugin_name, setting_name, setting_value, json_encoded, user_login)"
                . " VALUES (?, ?, '1', 0, '')"
            )->execute([self::PLUGIN, self::SETTING]);
        }
    }

    public function owned(): bool
    {
        $read = $this->pdo->prepare("SELECT option_value FROM `{$this->prefix}option` WHERE option_name = ?");
        $read->execute([self::MARKER]);

        return $read->fetchColumn() === '1';
    }

    public function setOwned(bool $owned): void
    {
        $this->pdo->prepare(
            $owned
                ? "REPLACE INTO `{$this->prefix}option` (option_name, option_value, autoload) VALUES (?, '1', 0)"
                : "DELETE FROM `{$this->prefix}option` WHERE option_name = ?"
        )->execute([self::MARKER]);
    }
}

/**
 * @param string $mode enforced, offered or off
 *
 * @return array{0: int, 1: string} exit code and the [CHANGED], [UNCHANGED] or [FAIL] line
 */
function converge(Settings $settings, string $mode): array
{
    if (!in_array($mode, ['enforced', 'offered', 'off'], true)) {
        return [1, "[FAIL] MATOMO_TWO_FACTOR_MODE must be enforced, offered or off, not '$mode'"];
    }
    $required = $settings->required();
    $owned = $settings->owned();

    if ($mode === 'enforced') {
        if ($required) {
            return [0, '[UNCHANGED] Matomo already requires a second factor of every user'];
        }
        $settings->setRequired(true);
        $settings->setOwned(true);

        return [0, '[CHANGED] Matomo now requires a second factor of every user'];
    }

    if ($mode === 'offered' && !$owned) {
        return [0, $required
            ? '[UNCHANGED] the second-factor requirement an admin set stays'
            : '[UNCHANGED] Matomo requires no second factor'];
    }

    if (!$required && !$owned) {
        return [0, '[UNCHANGED] Matomo requires no second factor'];
    }
    $settings->setRequired(false);
    $settings->setOwned(false);

    return [0, '[CHANGED] Matomo no longer requires a second factor'];
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

        [$code, $line] = converge(
            new PdoSettings($pdo, (string) $config['database']['tables_prefix']),
            required('MATOMO_TWO_FACTOR_MODE')
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
