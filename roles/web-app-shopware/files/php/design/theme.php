<?php
// nocheck: mirrored-unit-test - reads and rewrites the Storefront theme record
// straight from Shopware's database connection and shells out to bin/console;
// top-level procedural code with nothing callable in isolation
/**
 * Prints `changed` or `unchanged` as its last line.
 *
 * Required env:
 *   DATABASE_URL      connection string of the Shopware database
 *   SHOPWARE_ROOT     directory that holds bin/console
 *   DESIGN_ENABLED    "true" applies the values, anything else withdraws what an earlier run applied
 *   DESIGN_VALUES     JSON object {"<theme field>": "<hex color or absolute image URL>"}
 *   DESIGN_SHOP_NAME  shop name to set; empty leaves the shop name alone
 */

declare(strict_types=1);

const THEME = 'Storefront';
const MARK = 'InfinitoDesign.config.applied';
const SHOP_NAME = 'core.basicInformation.shopName';
const VENDOR_SHOP_NAME = 'Demostore';

function fail(string $message): never
{
    file_put_contents('php://stderr', $message . "\n");
    exit(1);
}

function console(string ...$arguments): void
{
    passthru('php bin/console --no-interaction ' . implode(' ', array_map('escapeshellarg', $arguments)), $status);
    if ($status !== 0) {
        fail('bin/console ' . $arguments[0] . ' exited with ' . $status);
    }
}

function setting(PDO $pdo, string $key): mixed
{
    $statement = $pdo->prepare(
        'SELECT configuration_value FROM system_config WHERE configuration_key = ? AND sales_channel_id IS NULL'
    );
    $statement->execute([$key]);
    $raw = $statement->fetchColumn();

    return $raw === false ? null : (json_decode((string) $raw, true)['_value'] ?? null);
}

function mark(?array $state): void
{
    console('system:config:set', MARK, json_encode($state, JSON_THROW_ON_ERROR), '--json', '--silent');
}

$url = parse_url((string) getenv('DATABASE_URL'));
foreach (['host', 'port', 'path', 'user', 'pass'] as $part) {
    isset($url[$part]) || fail('DATABASE_URL carries no ' . $part);
}
$pdo = new PDO(
    sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', $url['host'], $url['port'], ltrim($url['path'], '/')),
    $url['user'],
    $url['pass'],
    [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
);
chdir((string) getenv('SHOPWARE_ROOT')) || fail('SHOPWARE_ROOT is not a directory');

$enabled = getenv('DESIGN_ENABLED') === 'true';
$wanted = $enabled ? json_decode((string) getenv('DESIGN_VALUES'), true, 8, JSON_THROW_ON_ERROR) : [];
$wantedName = $enabled ? (string) getenv('DESIGN_SHOP_NAME') : '';

$applied = setting($pdo, MARK);
if ($applied === null && !$enabled) {
    echo "unchanged\n";
    exit(0);
}
$applied ??= ['theme' => [], 'shopName' => null, 'compiled' => null];

$theme = $pdo->prepare('SELECT id, config_values FROM theme WHERE technical_name = ?');
$theme->execute([THEME]);
$row = $theme->fetch(PDO::FETCH_ASSOC);
if ($row === false) {
    fail('no theme named ' . THEME);
}

$current = json_decode($row['config_values'] ?? 'null', true) ?? [];
$next = $current;
$owned = [];
foreach (array_keys($applied['theme'] + $wanted) as $field) {
    $present = $current[$field]['value'] ?? null;
    if ($present !== null && $present !== ($applied['theme'][$field] ?? null)) {
        continue;
    }
    if (array_key_exists($field, $wanted)) {
        $next[$field] = ['value' => $wanted[$field]];
        $owned[$field] = $wanted[$field];
    } else {
        unset($next[$field]);
    }
}

ksort($owned);

$name = setting($pdo, SHOP_NAME);
$nameMark = $applied['shopName'];
$nameIsOurs = in_array($name, $nameMark === null ? [null, VENDOR_SHOP_NAME] : array_values($nameMark), true);
$nextName = $name;
if ($nameIsOurs && $wantedName !== '') {
    $nextName = $wantedName;
    $nameMark = ['applied' => $wantedName, 'previous' => $nameMark === null ? $name : $nameMark['previous']];
} elseif ($nameMark !== null) {
    $nextName = $nameIsOurs ? $nameMark['previous'] : $name;
    $nameMark = null;
}

$fingerprint = sha1(json_encode($next, JSON_THROW_ON_ERROR));
$state = ['theme' => $owned, 'shopName' => $nameMark, 'compiled' => $applied['compiled']];
if ($state === $applied && $next === $current && $nextName === $name && $applied['compiled'] === $fingerprint) {
    echo "unchanged\n";
    exit(0);
}

mark($state);
if ($next !== $current) {
    $pdo->prepare('UPDATE theme SET config_values = ?, updated_at = NOW(3) WHERE id = ?')
        ->execute([$next === [] ? null : json_encode($next, JSON_THROW_ON_ERROR), $row['id']]);
}
if ($nextName !== $name) {
    console('system:config:set', SHOP_NAME, json_encode($nextName, JSON_THROW_ON_ERROR), '--json');
}
if ($applied['compiled'] !== $fingerprint) {
    console('theme:compile', '--sync', '--keep-assets');
}
mark($enabled ? array_replace($state, ['compiled' => $fingerprint]) : null);

echo "changed\n";
