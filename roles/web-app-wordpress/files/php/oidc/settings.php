<?php
/**
 * Deletes the stored openid_connect_generic_settings of every site, because the
 * infinito-oidc-client mu-plugin serves them from the container.
 *
 * Output:
 *   "CHANGED <blog id>" once per site whose stored copy this run deleted.
 */

$multisite = is_multisite();
$blogs = $multisite ? get_sites(array('fields' => 'ids', 'number' => 0)) : array(get_current_blog_id());

foreach ($blogs as $blog_id) {
    if ($multisite) {
        switch_to_blog($blog_id);
    }
    if (delete_option('openid_connect_generic_settings')) {
        WP_CLI::log('CHANGED ' . $blog_id);
    }
    if ($multisite) {
        restore_current_blog();
    }
}
