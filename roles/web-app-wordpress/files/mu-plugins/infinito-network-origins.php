<?php
// nocheck: mirrored-unit-test - registers option filters at load from the live request host WordPress serves
/**
 * Plugin Name: Infinito.Nexus Network Origins
 * Description: Serve home and siteurl from the origin of the network the request arrived on, so an onion sibling links, loads and redirects within its own network.
 */

if (!defined('ABSPATH')) {
    exit;
}

(static function (): void {
    if (is_multisite()) {
        return;
    }
    $origins = [];
    foreach (preg_split('/\s+/', (string) getenv('INFINITO_NETWORK_BASE_URLS'), -1, PREG_SPLIT_NO_EMPTY) as $url) {
        $origins[strtolower((string) parse_url($url, PHP_URL_HOST))] = rtrim($url, '/');
    }
    $host = strtolower(explode(':', (string) ($_SERVER['HTTP_HOST'] ?? ''))[0]);
    $origin = $origins[$host] ?? '';
    if ($origin === '') {
        return;
    }
    foreach (['option_home', 'option_siteurl'] as $hook) {
        add_filter($hook, static fn (): string => $origin);
    }
})();
