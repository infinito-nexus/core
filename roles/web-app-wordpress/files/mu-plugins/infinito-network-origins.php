<?php
/**
 * Plugin Name: Infinito.Nexus Network Origins
 * Description: Serve every site from the origin of the network the request arrived on, so an onion sibling resolves to its own site and links, loads, redirects and keeps its login within its own network.
 */

if (!defined('ABSPATH')) {
    exit;
}

if (defined('INFINITO_NETWORK_ORIGINS_LOADED')) {
    return;
}
define('INFINITO_NETWORK_ORIGINS_LOADED', true);

(static function (): void {
    $host = static fn (string $url): string => strtolower((string) parse_url($url, PHP_URL_HOST));
    $sites = [];
    foreach (preg_split('/;/', (string) getenv('INFINITO_NETWORK_BASE_URLS'), -1, PREG_SPLIT_NO_EMPTY) as $siblings) {
        $sites[] = array_map(
            static fn (string $url): string => rtrim($url, '/'),
            preg_split('/,/', $siblings, -1, PREG_SPLIT_NO_EMPTY)
        );
    }
    $siteOf = [];
    $networkOf = [];
    foreach ($sites as $site => $origins) {
        foreach ($origins as $network => $origin) {
            $siteOf[$host($origin)] = $site;
            $networkOf[$host($origin)] = $network;
        }
    }
    $request = strtolower(explode(':', (string) ($_SERVER['HTTP_HOST'] ?? ''))[0]);
    if (!isset($networkOf[$request])) {
        return;
    }
    $network = $networkOf[$request];
    $rehost = static function (string $url) use ($host, $sites, $siteOf, $network): string {
        $origin = $sites[$siteOf[$host($url)] ?? -1][$network] ?? '';
        return $origin === '' ? $url : (string) preg_replace('#^https?://[^/]+#i', $origin, $url);
    };
    $rehostString = static fn (mixed $value): mixed => is_string($value) ? $rehost($value) : $value;
    foreach (['option_home', 'option_siteurl', 'content_url', 'plugins_url', 'network_home_url', 'network_site_url'] as $hook) {
        add_filter($hook, $rehostString);
    }
    add_filter('upload_dir', static fn (array $dirs): array => array_map($rehostString, $dirs));
    if (!is_multisite()) {
        return;
    }
    if ($network > 0) {
        add_filter(
            'pre_get_site_by_path',
            static fn ($site, string $domain, string $path, $segments) => ($networkOf[strtolower($domain)] ?? 0) > 0
                ? get_site_by_path($host($sites[$siteOf[strtolower($domain)]][0]), $path, $segments)
                : $site,
            10,
            4
        );
    }
    $networkSite = $siteOf[strtolower(defined('DOMAIN_CURRENT_SITE') ? DOMAIN_CURRENT_SITE : '')] ?? null;
    if ($networkSite !== null && isset($sites[$networkSite][$network]) && is_subdomain_install() && !defined('COOKIE_DOMAIN')) {
        $networkDomain = $host($sites[$networkSite][$network]);
        $underNetwork = $request === $networkDomain || str_ends_with($request, '.' . $networkDomain);
        define('COOKIE_DOMAIN', $underNetwork ? '.' . $networkDomain : '');
    }
})();
