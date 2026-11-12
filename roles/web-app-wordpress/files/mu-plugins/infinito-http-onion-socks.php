<?php
// nocheck: mirrored-unit-test - registers add_action('http_api_curl') at load and mutates a live cURL handle passed in by WordPress
/**
 * Plugin Name: Infinito.Nexus HTTP Onion SOCKS
 * Description: Route server-side wp_remote_* calls to .onion hosts (OIDC discovery and token exchange) through the Tor SOCKS proxy, which libcurl otherwise refuses to resolve.
 *
 * Hooks http_api_curl rather than http_request_args: WP core's WP_HTTP_Proxy
 * hardcodes CURLPROXY_HTTP, so SOCKS5 is only reachable on the raw handle.
 */

if (!defined('ABSPATH')) {
    exit;
}

add_action('http_api_curl', static function ($handle, array $args, string $url): void {
    $proxy  = getenv('WORDPRESS_OIDC_SOCKS_PROXY') ?: '';
    $suffix = strtolower(getenv('WORDPRESS_OIDC_SOCKS_SUFFIX') ?: '');
    if ($proxy === '' || $suffix === '') {
        return;
    }
    $host = strtolower((string) parse_url($url, PHP_URL_HOST));
    if ($host !== '' && str_ends_with($host, $suffix)) {
        curl_setopt($handle, CURLOPT_PROXY, $proxy);
    }
}, 10, 3);
