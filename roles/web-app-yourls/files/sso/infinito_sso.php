<?php
/**
 * Trusted-header SSO bridge for YOURLS.
 *
 * YOURLS has no native OIDC/SSO login. In Infinito.Nexus it sits behind an
 * oauth2-proxy that authenticates the visitor against Keycloak and forwards the
 * resolved identity as request headers. This drop-in registers a
 * `shunt_is_valid_user` filter (the extension point the YOURLS maintainer
 * recommends for trusted reverse-proxy header SSO) so that every admin/API
 * request is authenticated from that header instead of the login form.
 *
 * It ships as the `user/cache.php` drop-in: YOURLS includes that file
 * unconditionally and early (after the core auth/plugin functions load, before
 * yourls_load_plugins()), so the bridge needs no DB-backed plugin activation.
 *
 * Security: the identity header is trusted only on the gated admin path, where
 * oauth2-proxy authenticates the request and nginx overwrites the header. The
 * application port is bound to the internal container network. The bridge
 * activates only when PROXY_HEADER_SSO is truthy (wired by the role's env
 * template behind the oauth2 SSO flavor).
 *
 * Only the X-Forwarded-* headers nginx overwrites are read; the
 * X-Auth-Request and Remote-User variants are deliberately excluded so a client
 * cannot inject an identity nginx did not set.
 *
 * The header is honoured ONLY for requests under the oauth2-proxy-gated admin
 * path (PROXY_HEADER_SSO_GATED_PATH). YOURLS runs oauth2-proxy in ACL-blacklist
 * mode, so nginx overwrites the X-Forwarded-* headers on the gated admin
 * location only; on the public location they pass through untouched and could
 * be forged. Restricting the bridge to the admin path means it trusts the
 * header exactly where nginx guarantees it and unauthenticated requests are
 * bounced to Keycloak before they ever reach this upstream.
 */

if (!function_exists('infinito_sso_enabled')) {
    function infinito_sso_enabled() {
        $value = strtolower((string) getenv('PROXY_HEADER_SSO'));
        return in_array($value, array('true', '1', 'yes', 'on'), true);
    }

    function infinito_sso_on_gated_path() {
        $gated = trim((string) getenv('PROXY_HEADER_SSO_GATED_PATH'));
        if ($gated === '') {
            return false;
        }
        $gated = '/' . trim($gated, '/');
        $uri = isset($_SERVER['REQUEST_URI']) ? (string) $_SERVER['REQUEST_URI'] : '';
        $path = (string) parse_url($uri, PHP_URL_PATH);
        $path = '/' . ltrim($path, '/');
        return $path === $gated || strpos($path, $gated . '/') === 0;
    }

    function infinito_sso_first_header($names) {
        foreach ($names as $name) {
            if (isset($_SERVER[$name])) {
                $value = trim((string) $_SERVER[$name]);
                if ($value !== '') {
                    return $value;
                }
            }
        }
        return null;
    }

    function infinito_sso_split_groups($raw) {
        if ($raw === null || $raw === '') {
            return array();
        }
        $groups = array();
        foreach (preg_split('/[,\s]+/', (string) $raw) as $part) {
            if ($part !== '') {
                $groups[] = $part;
            }
        }
        return $groups;
    }

    function infinito_sso_group_matches($left, $right) {
        $left = ltrim(trim((string) $left), '/');
        $right = ltrim(trim((string) $right), '/');
        return $left !== '' && $left === $right;
    }

    function infinito_sso_is_admin($groups) {
        $admin_group = trim((string) getenv('PROXY_HEADER_SSO_ADMIN_GROUP'));
        if ($admin_group === '') {
            return true;
        }
        foreach ($groups as $group) {
            if (infinito_sso_group_matches($group, $admin_group)) {
                return true;
            }
        }
        return false;
    }

    function infinito_sso_shunt($pre) {
        if (!infinito_sso_on_gated_path()) {
            return $pre;
        }

        $username = infinito_sso_first_header(array(
            'HTTP_X_FORWARDED_PREFERRED_USERNAME',
            'HTTP_X_FORWARDED_USER',
        ));
        if ($username === null) {
            return $pre;
        }

        $groups = infinito_sso_split_groups(
            infinito_sso_first_header(array('HTTP_X_FORWARDED_GROUPS'))
        );
        if (!infinito_sso_is_admin($groups)) {
            return $pre;
        }

        yourls_set_user($username);
        return true;
    }

    if (infinito_sso_enabled()) {
        yourls_add_filter('shunt_is_valid_user', 'infinito_sso_shunt');
    }
}
