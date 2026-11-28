<?php
// nocheck: mirrored-unit-test - registers filters at load that answer option, menu, redirect and request hooks the WordPress core fires
/**
 * Plugin Name: Infinito.Nexus OIDC Client
 * Description: Serves the settings of daggerhart/openid-connect-generic from
 *              the container on every site, keeps every account from storing
 *              or opening them, and sends the sign-in of a site-owner host
 *              through the network's main site.
 */

if (!defined('ABSPATH')) {
    exit;
}

$infinito_oidc_client_sso = getenv('WORDPRESS_SSO_ENABLED');
if (!is_string($infinito_oidc_client_sso) || $infinito_oidc_client_sso === '') {
    throw new RuntimeException('WORDPRESS_SSO_ENABLED is not set in the WordPress container environment');
}
if ($infinito_oidc_client_sso !== 'true') {
    return;
}

const INFINITO_OIDC_CLIENT_OPTION = 'openid_connect_generic_settings';
const INFINITO_OIDC_CLIENT_PAGE = 'openid-connect-generic-settings';
const INFINITO_OIDC_CLIENT_ROUTED_ACTIONS = array('login', 'logout', 'lostpassword', 'rp', 'resetpass');

add_filter('pre_option_' . INFINITO_OIDC_CLIENT_OPTION, 'infinito_oidc_client_settings');
add_filter('pre_update_option_' . INFINITO_OIDC_CLIENT_OPTION, 'infinito_oidc_client_keep_settings', 10, 2);
add_action('admin_menu', 'infinito_oidc_client_hide_settings_page', 99);
add_action('load-settings_page_' . INFINITO_OIDC_CLIENT_PAGE, 'infinito_oidc_client_deny_settings_page');
add_action('init', 'infinito_oidc_client_route_owner_login', 0);
add_filter('allowed_redirect_hosts', 'infinito_oidc_client_allow_owner_hosts', 10, 2);

/**
 * @return array The client settings the deployment renders into WORDPRESS_OIDC_SETTINGS.
 */
function infinito_oidc_client_settings() {
    static $settings = null;
    if ($settings === null) {
        $settings = json_decode(infinito_oidc_env('WORDPRESS_OIDC_SETTINGS'), true, 8, JSON_THROW_ON_ERROR);
        if (!is_array($settings)) {
            throw new RuntimeException('WORDPRESS_OIDC_SETTINGS is not a JSON object');
        }
    }
    return $settings;
}

/**
 * @param mixed $value     The settings an update would store.
 * @param mixed $old_value The settings in force.
 * @return mixed $old_value, because the container is the only source of the settings.
 */
function infinito_oidc_client_keep_settings($value, $old_value) {
    return $old_value;
}

function infinito_oidc_client_hide_settings_page() {
    remove_submenu_page('options-general.php', INFINITO_OIDC_CLIENT_PAGE);
}

function infinito_oidc_client_deny_settings_page() {
    wp_die(
        esc_html__('The single sign-on settings come from the deployment.'),
        '',
        array('response' => 403)
    );
}

/**
 * @param string $host A request or redirect host.
 * @return bool True for a host of an existing site-owner site of a network that serves site-owner sites.
 */
function infinito_oidc_client_is_owner_host($host) {
    if (!is_multisite() || infinito_oidc_env('WORDPRESS_SITE_OWNER_ENABLED') !== 'true') {
        return false;
    }
    $parent = parse_url(infinito_oidc_env('WORDPRESS_SITE_OWNER_BASE_URL'), PHP_URL_HOST);
    if (!is_string($parent) || $parent === '') {
        throw new RuntimeException('WORDPRESS_SITE_OWNER_BASE_URL carries no host');
    }
    $suffix = '.' . strtolower($parent);
    $host = strtolower((string) $host);
    if (!str_ends_with($host, $suffix)) {
        return false;
    }
    $label = substr($host, 0, -strlen($suffix));
    return infinito_rbac_is_member_label($label) && infinito_rbac_find_site($host) !== null;
}

/**
 * Keycloak knows no redirect URI of a site-owner host, so its sign-in runs on
 * the main site, whose auth cookie the network domain shares with it.
 */
function infinito_oidc_client_route_owner_login() {
    if (($GLOBALS['pagenow'] ?? '') !== 'wp-login.php' || isset($_REQUEST['interim-login'])) {
        return;
    }
    $action = isset($_REQUEST['action']) && is_string($_REQUEST['action']) ? $_REQUEST['action'] : 'login';
    if (!in_array($action, INFINITO_OIDC_CLIENT_ROUTED_ACTIONS, true)) {
        return;
    }
    $host = explode(':', (string) ($_SERVER['HTTP_HOST'] ?? ''))[0];
    if (!infinito_oidc_client_is_owner_host($host)) {
        return;
    }
    $query = (string) ($_SERVER['QUERY_STRING'] ?? '');
    wp_redirect(network_site_url('wp-login.php') . ($query === '' ? '' : '?' . $query));
    exit;
}

/**
 * @param string[] $hosts The hosts wp_validate_redirect() lets a redirect reach.
 * @param string   $host  The host of the redirect being validated.
 * @return string[] The hosts, plus $host when it is the host of an existing site-owner site.
 */
function infinito_oidc_client_allow_owner_hosts($hosts, $host) {
    if (infinito_oidc_client_is_owner_host($host)) {
        $hosts[] = strtolower((string) $host);
    }
    return $hosts;
}
