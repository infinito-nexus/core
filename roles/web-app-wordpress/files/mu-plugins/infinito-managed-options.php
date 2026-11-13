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
    || !is_array($infinito_managed_options['site_option'] ?? null)
    || !is_array($infinito_managed_options['merge'] ?? null)) {
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

foreach ($infinito_managed_options['merge'] as $infinito_managed_name => $infinito_managed_value) {
    add_filter(
        'pre_update_option_' . $infinito_managed_name,
        static function ($value) use ($infinito_managed_value) {
            return is_main_site() ? infinito_managed_options_merge($value, $infinito_managed_value) : $value;
        },
        PHP_INT_MAX
    );
}

unset($infinito_managed_options_file, $infinito_managed_options, $infinito_managed_name, $infinito_managed_value);

/**
 * @param mixed $value   The array option a write would store.
 * @param array $managed {"keys": {<key>: <value>}, "records": {<list key>: <record with id>}}.
 * @return array $value with every managed key set and every managed record in place of the stored record of its id,
 *               appended when no stored record carries that id; every other key and record stays as written.
 */
function infinito_managed_options_merge($value, array $managed) {
    $value = is_array($value) ? $value : array();
    foreach ($managed['keys'] ?? array() as $key => $wanted) {
        $value[$key] = $wanted;
    }
    foreach ($managed['records'] ?? array() as $list => $record) {
        $kept = array();
        foreach (is_array($value[$list] ?? null) ? $value[$list] : array() as $entry) {
            if (!is_array($entry) || ($entry['id'] ?? null) !== $record['id']) {
                $kept[] = $entry;
            }
        }
        $kept[] = $record;
        $value[$list] = $kept;
    }
    return $value;
}
