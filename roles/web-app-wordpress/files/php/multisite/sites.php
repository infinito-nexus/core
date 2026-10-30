<?php
/**
 * Environment:
 *   WP_MS_SITE_URLS: comma-separated canonical base URL of every child site of the network.
 *   WP_MS_ADMIN_EMAIL: email of the user who administers every site this run creates.
 *
 * Output:
 *   "CHANGED <url>" once per site this run created; a site that already exists on its domain and path is left alone.
 */

$urls = getenv('WP_MS_SITE_URLS');
if ($urls === false) {
    WP_CLI::error('WP_MS_SITE_URLS is not set');
}
$owner = get_user_by('email', (string) getenv('WP_MS_ADMIN_EMAIL'));
if (!$owner) {
    WP_CLI::error('WP_MS_ADMIN_EMAIL names no user');
}

foreach (preg_split('/,/', $urls, -1, PREG_SPLIT_NO_EMPTY) as $url) {
    $url = untrailingslashit($url);
    $domain = strtolower((string) parse_url($url, PHP_URL_HOST));
    $path = trailingslashit((string) parse_url($url, PHP_URL_PATH));
    if ((int) get_blog_id_from_url($domain, $path) !== 0) {
        continue;
    }
    $created = wp_insert_site(array(
        'domain' => $domain,
        'path' => $path,
        'title' => $domain,
        'user_id' => $owner->ID,
        'options' => array('home' => $url, 'siteurl' => $url),
    ));
    if (is_wp_error($created)) {
        WP_CLI::error($domain . ': ' . $created->get_error_message());
    }
    WP_CLI::log('CHANGED ' . $url);
}
