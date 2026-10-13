<?php
// nocheck: mirrored-unit-test - opens a PDO connection to the live Friendica database at the
// top level to compare and rewrite one user row; the whole file is that query
require "/var/www/html/vendor/autoload.php";
$cfgFile  = getenv("FRIENDICA_CONFIG_FILE");
$nickname = getenv("FRIENDICA_ADMIN_NICKNAME");
$password = getenv("FRIENDICA_ADMIN_PASSWORD");
if ($password !== false) {
    $password = trim($password);
}
if ($cfgFile === false || $nickname === false || $nickname === "" || $password === false || $password === "") {
    fwrite(STDERR, "FRIENDICA_CONFIG_FILE, FRIENDICA_ADMIN_NICKNAME and FRIENDICA_ADMIN_PASSWORD are required\n");
    exit(1);
}
$cfg = include $cfgFile;
$db  = $cfg["database"];
$h   = explode(":", $db["hostname"]);
$dsn = "mysql:host=" . $h[0] . ";port=" . ($h[1] ?? 3306) . ";dbname=" . $db["database"];
$pdo = new PDO($dsn, $db["username"], $db["password"], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$select = $pdo->prepare("SELECT `uid`, `password`, `legacy_password` FROM `user` WHERE `nickname` = ?");
$select->execute([$nickname]);
$user = $select->fetch(PDO::FETCH_ASSOC);
if ($user === false) {
    fwrite(STDERR, "no Friendica user with nickname " . $nickname . "\n");
    exit(1);
}
if (!$user["legacy_password"] && password_verify($password, $user["password"])) {
    echo "PASSWORD_KEPT\n";
    exit(0);
}
$update = $pdo->prepare(
    "UPDATE `user` SET `password` = ?, `pwdreset` = NULL, `pwdreset_time` = NULL, `legacy_password` = 0 WHERE `uid` = ?"
);
$update->execute([password_hash($password, PASSWORD_DEFAULT), $user["uid"]]);
echo "PASSWORD_SET\n";
