<?php
// nocheck: mirrored-unit-test - runs through the container's php CLI without booting WordPress, so the guard it feeds cannot refuse it
/**
 * Arguments:
 *   $argv[1]  path of the PHP file the infinito-managed-options mu-plugin includes
 *
 * Required env:
 *   INFINITO_MANAGED_OPTIONS  base64 of a JSON object {"option": {<name>: <value>}, "site_option": {<name>: <value>}}
 *
 * Stdout, last line: changed | unchanged
 */

$fail = static function (string $message): void {
    fwrite(STDERR, $message . "\n");
    exit(1);
};

$path = $argv[1] ?? '';
if ($path === '') {
    $fail('the path of the managed options file is missing');
}

$managed = json_decode((string) base64_decode((string) getenv('INFINITO_MANAGED_OPTIONS'), true), true, 32, JSON_THROW_ON_ERROR);
if (!is_array($managed) || !is_array($managed['option'] ?? null) || !is_array($managed['site_option'] ?? null)) {
    $fail('INFINITO_MANAGED_OPTIONS holds no option and site_option object');
}

$code = "<?php\nreturn " . var_export(['option' => $managed['option'], 'site_option' => $managed['site_option']], true) . ";\n";
if (is_file($path) && (fileperms($path) & 0777) === 0600 && file_get_contents($path) === $code) {
    echo "unchanged\n";
    exit(0);
}

umask(0077);
$staged = $path . '.new';
if (file_put_contents($staged, $code) === false || !chmod($staged, 0600) || !rename($staged, $path)) {
    $fail("cannot write {$path}");
}

echo "changed\n";
