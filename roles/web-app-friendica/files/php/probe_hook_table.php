<?php
require "/var/www/html/vendor/autoload.php";
$cfg = include "/var/www/html/config/local.config.php";
$db  = $cfg["database"];
$h   = explode(":", $db["hostname"]);
$dsn = "mysql:host=" . $h[0] . ";port=" . ($h[1] ?? 3306) . ";dbname=" . $db["database"];
$pdo = new PDO($dsn, $db["username"], $db["password"]);
$pdo->query("SELECT 1 FROM hook LIMIT 1");
