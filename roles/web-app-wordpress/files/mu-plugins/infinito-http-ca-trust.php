<?php
// nocheck: mirrored-unit-test - registers add_filter('http_request_args') at load; the body only runs inside a booted WordPress request
/**
 * Plugin Name: Infinito.Nexus HTTP CA Trust
 * Description: Point the WP HTTP API at the injected internal CA bundle so server-side wp_remote_* TLS (OIDC token exchange) verifies.
 */

if (!defined('ABSPATH')) {
    exit;
}

add_filter('http_request_args', static function (array $args): array {
    $candidates = [
        getenv('CURL_CA_BUNDLE') ?: '',
        getenv('CA_TRUST_CERT') ?: '',
        getenv('SSL_CERT_FILE') ?: '',
    ];
    foreach ($candidates as $bundle) {
        if ($bundle !== '' && is_readable($bundle)) {
            $args['sslcertificates'] = $bundle;
            break;
        }
    }
    return $args;
}, 10, 1);
