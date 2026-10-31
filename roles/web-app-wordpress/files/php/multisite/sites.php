<?php
/**
 * Environment:
 *   WP_MS_SITE_URLS: comma-separated canonical base URL of every child site of the network.
 *   WP_MS_ADMIN_EMAIL: email of the user who administers every site this run creates.
 *
 * Output:
 *   "CHANGED <url>" once per site this run created, moved from its legacy slug domain "<domain>.<network domain without www.>" onto its domain and path, or whose stored home or siteurl it set to <url>; a site already on its domain and path with both options at <url> is left alone.
 */

$urls = getenv('WP_MS_SITE_URLS');
if ($urls === false) {
    WP_CLI::error('WP_MS_SITE_URLS is not set');
}
$owner = get_user_by('email', (string) getenv('WP_MS_ADMIN_EMAIL'));
if (!$owner) {
    WP_CLI::error('WP_MS_ADMIN_EMAIL names no user');
}
$network = get_network();
$network_domain = preg_replace('|^www\.|', '', strtolower((string) $network->domain));
$domains = array_map(
    static fn (string $url): string => strtolower((string) parse_url($url, PHP_URL_HOST)),
    preg_split('/,/', $urls, -1, PREG_SPLIT_NO_EMPTY)
);
remove_all_filters('option_home');
remove_all_filters('option_siteurl');

foreach (preg_split('/,/', $urls, -1, PREG_SPLIT_NO_EMPTY) as $url) {
    $url = untrailingslashit($url);
    $domain = strtolower((string) parse_url($url, PHP_URL_HOST));
    $path = trailingslashit((string) parse_url($url, PHP_URL_PATH));
    $blog_id = (int) get_blog_id_from_url($domain, $path);
    $changed = false;
    $legacy_domain = $domain . '.' . $network_domain;
    $legacy_id = (int) get_blog_id_from_url($legacy_domain, $network->path);
    if ($legacy_id !== 0) {
        if ($blog_id !== 0) {
            WP_CLI::error("{$domain}: site {$blog_id} already serves it while the legacy slug site {$legacy_id} on {$legacy_domain} still claims it");
        }
        if (in_array($legacy_domain, $domains, true)) {
            WP_CLI::error("{$domain}: the legacy slug domain {$legacy_domain} of site {$legacy_id} is itself a listed site");
        }
        $moved = wp_update_site($legacy_id, array('domain' => $domain, 'path' => $path));
        if (is_wp_error($moved)) {
            WP_CLI::error($domain . ': ' . $moved->get_error_message());
        }
        $blog_id = $legacy_id;
        $changed = true;
    }
    if ($blog_id !== 0) {
        foreach (array('home', 'siteurl') as $option) {
            if (untrailingslashit((string) get_blog_option($blog_id, $option)) === $url) {
                continue;
            }
            if (!update_blog_option($blog_id, $option, $url)) {
                WP_CLI::error("{$domain}: site {$blog_id} keeps its {$option} instead of {$url}");
            }
            $changed = true;
        }
        if ($changed) {
            WP_CLI::log('CHANGED ' . $url);
        }
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
