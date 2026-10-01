<?php
// nocheck: mirrored-unit-test - defines constants and registers add_filter('s3_uploads_s3_client_params') at load; the body only runs inside a booted WordPress request
/**
 * Plugin Name: Infinito.Nexus S3 Uploads Endpoint
 * Description: Point the S3-Uploads plugin at the SeaweedFS object store: constants for bucket, credentials and region, plus the endpoint and path-style addressing the plugin exposes no constant for.
 */

if (!defined('ABSPATH')) {
    exit;
}

$infinito_s3_settings = [
    'bucket' => getenv('WORDPRESS_S3_BUCKET') ?: '',
    'endpoint' => getenv('WORDPRESS_S3_ENDPOINT') ?: '',
    'key' => getenv('WORDPRESS_S3_KEY') ?: '',
    'secret' => getenv('WORDPRESS_S3_SECRET') ?: '',
    'region' => getenv('WORDPRESS_S3_REGION') ?: '',
];
if (in_array('', $infinito_s3_settings, true)) {
    return;
}

$infinito_s3_endpoint = $infinito_s3_settings['endpoint'];

define('S3_UPLOADS_BUCKET', $infinito_s3_settings['bucket']);
define('S3_UPLOADS_KEY', $infinito_s3_settings['key']);
define('S3_UPLOADS_SECRET', $infinito_s3_settings['secret']);
define('S3_UPLOADS_REGION', $infinito_s3_settings['region']);

$infinito_s3_public_url = getenv('WORDPRESS_S3_PUBLIC_URL') ?: '';
if ($infinito_s3_public_url !== '') {
    define('S3_UPLOADS_BUCKET_URL', rtrim($infinito_s3_public_url, '/'));
}

add_filter('s3_uploads_s3_client_params', static function (array $params) use ($infinito_s3_endpoint): array {
    $params['endpoint'] = $infinito_s3_endpoint;
    $params['use_path_style_endpoint'] = true;

    return $params;
});
