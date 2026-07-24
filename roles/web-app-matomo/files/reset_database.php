<?php
/**
 * Drop and recreate the Matomo database so a bootstrap retry takes the
 * clean-install path. Runs inside the matomo container via stdin.
 *
 * Env (from the container):
 *   MATOMO_DATABASE_HOST      host or host:port
 *   MATOMO_DATABASE_DBNAME    database to reset
 *   MATOMO_DATABASE_USERNAME  app user (holds ALL on the database)
 *   MATOMO_DATABASE_PASSWORD  app password
 */
[$host, $port] = array_pad(explode(':', getenv('MATOMO_DATABASE_HOST')), 2, 3306);
$db = getenv('MATOMO_DATABASE_DBNAME');
$pdo = new PDO("mysql:host=$host;port=$port", getenv('MATOMO_DATABASE_USERNAME'), getenv('MATOMO_DATABASE_PASSWORD'));
$pdo->exec("DROP DATABASE IF EXISTS `$db`");
$pdo->exec("CREATE DATABASE `$db`");
echo "OK: database `$db` reset\n";
