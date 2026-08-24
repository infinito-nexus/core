<?php
// nocheck: mirrored-unit-test - requires /var/www/html/app/etc/env.php as a PHP array
// and writes it back with var_export; the install's own config file is both input and
// output
$file = '/var/www/html/app/etc/env.php';
$config = require $file;

$desired = [
    'driver' => getenv('MAGENTO_REMOTE_STORAGE_DRIVER'),
    'config' => [
        'endpoint' => getenv('MAGENTO_REMOTE_STORAGE_ENDPOINT'),
        'bucket' => getenv('MAGENTO_REMOTE_STORAGE_BUCKET'),
        'region' => getenv('MAGENTO_REMOTE_STORAGE_REGION'),
        'path_style' => (int) getenv('MAGENTO_REMOTE_STORAGE_PATH_STYLE'),
        'credentials' => [
            'key' => getenv('MAGENTO_REMOTE_STORAGE_KEY'),
            'secret' => getenv('MAGENTO_REMOTE_STORAGE_SECRET'),
        ],
    ],
];

if (($config['remote_storage'] ?? null) === $desired) {
    echo "unchanged\n";
    exit(0);
}

$config['remote_storage'] = $desired;
file_put_contents($file, "<?php\nreturn " . var_export($config, true) . ";\n");
echo "updated\n";
