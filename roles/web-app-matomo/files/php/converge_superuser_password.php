<?php
// nocheck: mirrored-unit-test - rewrites the live Matomo user table over a
// connection it opens itself; running it is the whole behaviour
/**
 * Realign the Matomo superuser password with the value the deployment renders.
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
 *   MATOMO_SUPERUSER_LOGIN    login to realign
 *   MATOMO_SUPERUSER_PASSWORD password it must accept afterwards
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */
function required(string $name): string
{
    $value = getenv($name);
    if ($value === false || $value === '') {
        fwrite(STDERR, "[FAIL] $name is empty\n");
        exit(1);
    }
    return $value;
}

$configPath = required('MATOMO_CONFIG');
$login = required('MATOMO_SUPERUSER_LOGIN');
$password = required('MATOMO_SUPERUSER_PASSWORD');

$config = parse_ini_file($configPath, true);
if ($config === false || !isset($config['database']['tables_prefix'])) {
    fwrite(STDERR, "[FAIL] $configPath carries no database.tables_prefix\n");
    exit(1);
}
$prefix = $config['database']['tables_prefix'];

[$host, $port] = array_pad(explode(':', required('MATOMO_DATABASE_HOST')), 2, 3306);
$pdo = new PDO(
    "mysql:host=$host;port=$port;dbname=" . required('MATOMO_DATABASE_DBNAME'),
    required('MATOMO_DATABASE_USERNAME'),
    required('MATOMO_DATABASE_PASSWORD'),
    [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
);

$read = $pdo->prepare("SELECT password FROM `{$prefix}user` WHERE login = ?");
$read->execute([$login]);
$stored = $read->fetchColumn();

if ($stored === false) {
    fwrite(STDERR, "[FAIL] no Matomo user named '$login'\n");
    exit(1);
}

if (password_verify(md5($password), $stored)) {
    echo "[UNCHANGED] the Matomo superuser already accepts the declared password\n";
    exit(0);
}

$write = $pdo->prepare(
    "UPDATE `{$prefix}user` SET password = ?, ts_password_modified = UTC_TIMESTAMP() WHERE login = ?"
);
$write->execute([password_hash(md5($password), PASSWORD_DEFAULT), $login]);
echo "[CHANGED] the Matomo superuser was realigned with the declared password\n";
