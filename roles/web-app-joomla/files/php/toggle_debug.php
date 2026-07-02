<?php
$f = getenv('J_CONFIG_FILE');
if (!file_exists($f)) { fwrite(STDERR, "configuration.php missing\n"); exit(1); }
$c = file_get_contents($f);
$changed = 0;

$debug = getenv('J_MODE_DEBUG') === '1';
$err   = getenv('J_ERR_LEVEL') ?: 'default';

// Clean up previously broken lines
$c = preg_replace('/^\s*public\s+1\s*=.*?;$/m', '', $c, -1, $nBad1); $changed += $nBad1;
$c = preg_replace('/^\s*public\s*=\s*maximum;$/m', '', $c, -1, $nBad2); $changed += $nBad2;

// Ensure: public $debug = true|false;
$lineDebug = "public \$debug = " . ($debug ? 'true' : 'false') . ";";
if (preg_match('/public\s*\$debug\s*=\s*[^;]*;/', $c)) {
  $c = preg_replace('/public\s*\$debug\s*=\s*[^;]*;/', $lineDebug, $c, 1, $n); $changed += $n;
} else {
  $c = preg_replace("/\n\}\s*$/", "\n\t".$lineDebug."\n}\n", $c, 1, $n); $changed += $n;
}

// Ensure: public $error_reporting = 'maximum'|'default';
$lineErr = "public \$error_reporting = '" . str_replace("'", "\\'", $err) . "';";
if (preg_match('/public\s*\$error_reporting\s*=\s*[^;]*;/', $c)) {
  $c = preg_replace('/public\s*\$error_reporting\s*=\s*[^;]*;/', $lineErr, $c, 1, $n); $changed += $n;
} else {
  $c = preg_replace("/\n\}\s*$/", "\n\t".$lineErr."\n}\n", $c, 1, $n); $changed += $n;
}

if ($changed) { file_put_contents($f, $c); echo "changed"; } else { echo "ok"; }
