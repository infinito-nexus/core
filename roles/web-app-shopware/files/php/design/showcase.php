<?php
/**
 * Required env, supplied by the calling task via `container exec -e KEY`:
 *   SHOWCASE         JSON object of SHOPWARE_SHOWCASE: manufacturer with id and name,
 *                    customer and address ids, customerEmail, active for the seeded
 *                    products and customer, and products with id, number, name and gross
 *   SHOWCASE_DOMAIN  domain a storefront domain of the sales channel contains
 *
 * Output: "CHANGED <entity> <id>" per written row, then one JSON line
 * {"changed": bool, "channelId": id, "themeId": id, "themeConfig": {<field>: <value>},
 * "customerPassword": password}; the password is an HMAC of the kernel secret.
 */

const FINGERPRINT = 'infinito_showcase_fingerprint';

/**
 * @param array<string, mixed> $payload the row the seed writes, password excluded
 * @param string $secret a value the fingerprint covers without showing it
 * @return string the fingerprint of the payload
 */
function fingerprint(array $payload, string $secret): string
{
    return hash('sha256', json_encode($payload, JSON_THROW_ON_ERROR) . "\n" . hash('sha256', $secret));
}

/**
 * @param string $entity the DAL entity name
 * @param array<string, mixed> $payload the row the seed writes, its id included
 * @param array<string, mixed> $hidden fields written but kept out of the fingerprint, such as a password
 * @return bool whether the row was written
 */
function seed(string $entity, array $payload, array $hidden): bool
{
    $print = fingerprint($payload, json_encode($hidden, JSON_THROW_ON_ERROR));
    $stored = dal('search', $entity, ['id' => $payload['id']])[0] ?? [];

    if (($stored['customFields'][FINGERPRINT] ?? null) === $print) {
        return false;
    }

    dal('upsert', $entity, $payload + $hidden + ['customFields' => [FINGERPRINT => $print]]);
    echo "CHANGED {$entity} {$payload['id']}\n";

    return true;
}

$showcase = json_decode(env('SHOWCASE'), true, 512, JSON_THROW_ON_ERROR);
$domain = env('SHOWCASE_DOMAIN');
$secret = (string) container()->getParameter('kernel.secret');

if ($secret === '') {
    fwrite(STDERR, "kernel.secret is empty, the showcase password would be public\n");
    exit(1);
}

$password = hash_hmac('sha256', 'web-app-shopware:showcase-customer', $secret);

$domains = array_values(array_filter(
    dal('search', 'sales_channel_domain', []),
    static fn (array $row): bool => str_contains((string) ($row['url'] ?? ''), $domain)
));

if ($domains === []) {
    fwrite(STDERR, "no storefront sales channel serves {$domain}\n");
    exit(1);
}

$channel = dal('search', 'sales_channel', ['id' => $domains[0]['salesChannelId']])[0];
$taxes = dal('search', 'tax', []);
usort($taxes, static fn (array $a, array $b): int => ($a['position'] ?? 0) <=> ($b['position'] ?? 0));
$tax = $taxes[0];
$salutation = dal('search', 'salutation', ['salutationKey' => 'not_specified'])[0];
$theme = dal('search', 'theme', ['technicalName' => 'Storefront'])[0];

$changed = false;

foreach ($showcase['products'] as $product) {
    $changed = seed('product', [
        'id' => $product['id'],
        'productNumber' => $product['number'],
        'name' => $product['name'],
        'description' => 'Seeded by the design gallery.',
        'stock' => 25,
        'active' => $showcase['active'],
        'taxId' => $tax['id'],
        'manufacturer' => $showcase['manufacturer'],
        'price' => [[
            'currencyId' => $channel['currencyId'],
            'gross' => $product['gross'],
            'net' => round($product['gross'] / (1 + $tax['taxRate'] / 100), 2),
            'linked' => true,
        ]],
        'categories' => [['id' => $channel['navigationCategoryId']]],
        'visibilities' => [['id' => $product['id'], 'salesChannelId' => $channel['id'], 'visibility' => 30]],
    ], []) || $changed;
}

$changed = seed('customer', [
    'id' => $showcase['customer'],
    'customerNumber' => 'DESIGN-1',
    'firstName' => 'Design',
    'lastName' => 'Showcase',
    'email' => $showcase['customerEmail'],
    'active' => $showcase['active'],
    'guest' => false,
    'salutationId' => $salutation['id'],
    'groupId' => $channel['customerGroupId'],
    'salesChannelId' => $channel['id'],
    'languageId' => $channel['languageId'],
    'defaultBillingAddressId' => $showcase['address'],
    'defaultShippingAddressId' => $showcase['address'],
    'addresses' => [[
        'id' => $showcase['address'],
        'salutationId' => $salutation['id'],
        'firstName' => 'Design',
        'lastName' => 'Showcase',
        'street' => 'Showcase 1',
        'zipcode' => '10115',
        'city' => 'Berlin',
        'countryId' => $channel['countryId'],
    ]],
], ['password' => $password]) || $changed;

echo json_encode([
    'changed' => $changed,
    'channelId' => $channel['id'],
    'themeId' => $theme['id'],
    'themeConfig' => (object) array_map(
        static fn (mixed $field): mixed => is_array($field) ? ($field['value'] ?? null) : null,
        is_array($theme['configValues'] ?? null) ? $theme['configValues'] : []
    ),
    'customerPassword' => $password,
], JSON_THROW_ON_ERROR) . "\n";
