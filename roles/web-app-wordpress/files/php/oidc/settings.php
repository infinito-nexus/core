<?php
/**
 * Environment:
 *   WP_OIDC_SETTINGS: base64 of the daggerhart openid_connect_generic_settings map.
 */

$settings = json_decode(base64_decode(getenv('WP_OIDC_SETTINGS')), true);
if (!is_array($settings)) {
    WP_CLI::error('WP_OIDC_SETTINGS did not decode to a settings map');
}

if (!is_multisite()) {
    update_option('openid_connect_generic_settings', $settings);
    return;
}

$missing = array();
foreach (get_sites(array('fields' => 'ids', 'number' => 0)) as $blog_id) {
    switch_to_blog($blog_id);
    update_option('openid_connect_generic_settings', $settings);
    if (!get_option('openid_connect_generic_settings')) {
        $missing[] = $blog_id;
    }
    restore_current_blog();
}

if ($missing) {
    WP_CLI::error('openid_connect_generic_settings did not persist on blog ' . implode(', ', $missing));
}
