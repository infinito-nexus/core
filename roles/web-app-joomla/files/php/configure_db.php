<?php
$f = getenv('J_CONFIG_FILE');
if (!file_exists($f)) { exit(0); }
$c = file_get_contents($f);
$changed = 0;

$map = [
  'dbtype'   => getenv('J_DBTYPE'),
  'host'     => getenv('J_DBHOST'),
  'user'     => getenv('J_DBUSER'),
  'password' => getenv('J_DBPASS'),
  'db'       => getenv('J_DBNAME'),
];

foreach ($map as $k => $v) {
  // Escape single quotes for safe embedding into the PHP source string
  $vEsc = str_replace("'", "\\'", $v);

  // Match current value in config: public $key = '...';
  if (preg_match("/public \\$".$k."\\s*=\\s*'([^']*)';/", $c, $m) && $m[1] !== $v) {
    $c = preg_replace(
      "/public \\$".$k."\\s*=\\s*'[^']*';/",
      "public $".$k." = '".$vEsc."';",
      $c
    );
    $changed = 1;
  }
}

if ($changed) { file_put_contents($f, $c); echo "changed"; } else { echo "ok"; }
