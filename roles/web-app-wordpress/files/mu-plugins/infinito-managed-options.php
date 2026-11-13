<?php
// nocheck: mirrored-unit-test - registers option filters at load that the WordPress core fires on every option write
/**
 * Plugin Name: Infinito.Nexus Managed Options
 * Description: Keeps every option the deployment manages at its managed value
 *              for every writer, the settings pages, the REST API and WP-CLI
 *              included.
 */

if (!defined('ABSPATH')) {
    exit;
}

$infinito_managed_options_file = getenv('WORDPRESS_MANAGED_OPTIONS_FILE');
if (!is_string($infinito_managed_options_file) || $infinito_managed_options_file === '') {
    throw new RuntimeException('WORDPRESS_MANAGED_OPTIONS_FILE is not set in the WordPress container environment');
}
$infinito_managed_options = is_readable($infinito_managed_options_file) ? include $infinito_managed_options_file : null;
if (!is_array($infinito_managed_options)
    || !is_array($infinito_managed_options['option'] ?? null)
    || !is_array($infinito_managed_options['site_option'] ?? null)) {
    throw new RuntimeException('WORDPRESS_MANAGED_OPTIONS_FILE holds no managed options, so no managed option may change');
}

foreach ($infinito_managed_options['option'] as $infinito_managed_name => $infinito_managed_value) {
    add_filter(
        'pre_update_option_' . $infinito_managed_name,
        static function ($value) use ($infinito_managed_value) {
            return is_main_site() ? $infinito_managed_value : $value;
        },
        PHP_INT_MAX
    );
}

foreach ($infinito_managed_options['site_option'] as $infinito_managed_name => $infinito_managed_value) {
    add_filter(
        'pre_update_site_option_' . $infinito_managed_name,
        static function () use ($infinito_managed_value) {
            return $infinito_managed_value;
        },
        PHP_INT_MAX
    );
}

unset($infinito_managed_options_file, $infinito_managed_options, $infinito_managed_name, $infinito_managed_value);
