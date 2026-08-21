<?php
// nocheck: mirrored-unit-test - reads and rewrites the admin role privilege set
// straight from Shopware's database connection; top-level procedural code
/**
 * Required env:
 *   DATABASE_URL  connection string of the Shopware database
 *   ADMIN_USER    username whose admin flag is enforced
 */

declare(strict_types=1);

$url = parse_url(getenv('DATABASE_URL') ?: '');
$dsn = sprintf(
    'mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4',
    $url['host'] ?? 'localhost',
    $url['port'] ?? 3306,
    ltrim($url['path'] ?? '', '/')
);

$admin = getenv('ADMIN_USER');

$pdo = new PDO($dsn, $url['user'] ?? '', $url['pass'] ?? '', [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$statement = $pdo->prepare('UPDATE `user` SET admin = 1 WHERE username = ?');
$statement->execute([$admin]);

$present = $pdo->prepare('SELECT COUNT(*) FROM `user` WHERE username = ?');
$present->execute([$admin]);

if ((int) $present->fetchColumn() === 0) {
    fwrite(STDERR, "no Shopware user named {$admin}\n");
    exit(1);
}

printf("admin flag asserted for %s (%d row(s))\n", $admin, $statement->rowCount());
