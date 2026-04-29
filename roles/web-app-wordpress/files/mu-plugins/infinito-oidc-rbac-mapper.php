<?php
/**
 * Plugin Name: Infinito.Nexus OIDC RBAC Role Mapper
 * Description: Maps the Keycloak `groups` claim delivered by
 *              daggerhart/openid-connect-generic to a WordPress role.
 *              Installed as a mu-plugin so it is always active and
 *              cannot be deactivated from the admin UI.
 * Version:     2.0.0
 * Author:      Infinito.Nexus
 *
 * Requirements:
 * - docs/requirements/004-generic-rbac-ldap-auto-provisioning.md
 * - docs/requirements/005-wordpress-multisite-rbac.md
 *
 * Contract:
 * - Each WordPress user's role is derived purely from the `groups` claim
 *   of the OIDC userinfo response. No direct LDAP bind from WordPress.
 * - The claim uses the hierarchical Keycloak group path introduced by
 *   requirement 005:
 *     /roles/web-app-wordpress/<role>                   (single-site)
 *     /roles/web-app-wordpress/<tenant>/<role>          (multisite per-site)
 *     /roles/web-app-wordpress/network-administrator    (multisite global)
 * - Groups for other apps (e.g. /roles/web-app-discourse/editor) are
 *   ignored here.
 * - When the user matches multiple roles for the same scope, the
 *   highest-privilege role wins
 *   (administrator > editor > author > contributor > subscriber).
 * - When no claim entry matches, the weakest role `subscriber` is
 *   assigned as a deterministic fallback. An unauthenticated claim
 *   MUST NOT silently elevate rights.
 */

if (!defined('ABSPATH')) {
    exit;
}

add_action('openid-connect-generic-user-create', 'infinito_oidc_map_rbac_role', 10, 2);
add_action(
    'openid-connect-generic-update-user-using-current-claim',
    'infinito_oidc_map_rbac_role',
    10,
    2
);

const INFINITO_RBAC_APP_ID = 'web-app-wordpress';
const INFINITO_RBAC_NETWORK_ADMIN_ROLE = 'network-administrator';
const INFINITO_RBAC_OWNERSHIP_META_KEY = '_infinito_oidc_added_blog_ids';

/**
 * WP roles in descending privilege order. Must match the requirement 004
 * priority rule exactly; changes here affect the mapping contract.
 */
function infinito_rbac_priority() {
    return array(
        'administrator',
        'editor',
        'author',
        'contributor',
        'subscriber',
    );
}

/**
 * Parse the `groups` claim and return a structured view:
 *   array(
 *     'global' => [ <role>, ... ],
 *     'per_tenant' => [ <tenant> => [ <role>, ... ] ],
 *     'network_admin' => bool,
 *   )
 *
 * Requirement 005 mandates a hierarchical Keycloak group path that
 * mirrors the LDAP RBAC tree:
 *   /<rbac-group-root>/<application_id>/<role>                        (single-site or global)
 *   /<rbac-group-root>/<application_id>/<tenant>/<role>               (per-tenant)
 *   /<rbac-group-root>/<application_id>/network-administrator         (multisite super-admin)
 * Only entries whose second segment equals INFINITO_RBAC_APP_ID are
 * considered; everything else is silently dropped.
 */
function infinito_rbac_parse_claim($groups) {
    $parsed = array(
        'global' => array(),
        'per_tenant' => array(),
        'network_admin' => false,
    );
    if (!is_array($groups)) {
        return $parsed;
    }
    foreach ($groups as $group) {
        if (!is_string($group)) {
            continue;
        }
        $segments = array_values(array_filter(
            explode('/', trim($group, '/')),
            function ($s) { return $s !== ''; }
        ));
        if (count($segments) < 3) {
            continue;
        }
        if ($segments[1] !== INFINITO_RBAC_APP_ID) {
            continue;
        }
        if (count($segments) === 3) {
            $role = $segments[2];
            if ($role === INFINITO_RBAC_NETWORK_ADMIN_ROLE) {
                $parsed['network_admin'] = true;
                continue;
            }
            $parsed['global'][] = $role;
        } elseif (count($segments) === 4) {
            $tenant = strtolower($segments[2]);
            $role = $segments[3];
            if (!isset($parsed['per_tenant'][$tenant])) {
                $parsed['per_tenant'][$tenant] = array();
            }
            $parsed['per_tenant'][$tenant][] = $role;
        }
    }
    return $parsed;
}

function infinito_rbac_pick_highest_role($roles) {
    foreach (infinito_rbac_priority() as $candidate) {
        if (in_array($candidate, $roles, true)) {
            return $candidate;
        }
    }
    return null;
}

/**
 * Single-Site mapping path (requirement 004 contract, rewritten for the
 * hierarchical path from requirement 005). Treats `global` entries as
 * the current-site role source.
 */
function infinito_rbac_apply_single_site($user, $parsed) {
    $matched = array();
    foreach ($parsed['global'] as $role) {
        if (in_array($role, infinito_rbac_priority(), true)) {
            $matched[] = $role;
        }
    }
    $selected = infinito_rbac_pick_highest_role($matched);
    if ($selected === null) {
        $selected = 'subscriber';
    }
    $user->set_role($selected);
}

/**
 * Multisite mapping path. Per requirement 005:
 *   - network-administrator group grants super-admin across the network;
 *     its absence revokes super-admin.
 *   - per-tenant entries grant per-site roles, add missing site
 *     memberships, and withdraw memberships the mu-plugin added earlier.
 */
function infinito_rbac_apply_multisite($user, $parsed) {
    $user_id = (int) $user->ID;

    if ($parsed['network_admin']) {
        grant_super_admin($user_id);
    } else {
        revoke_super_admin($user_id);
    }

    $owned = get_user_meta($user_id, INFINITO_RBAC_OWNERSHIP_META_KEY, true);
    if (!is_array($owned)) {
        $owned = array();
    }

    $sites = function_exists('get_sites') ? get_sites() : array();
    foreach ($sites as $site) {
        $blog_id = (int) $site->blog_id;
        // Resolve the tenant key for this site from its canonical domain.
        $tenant = strtolower(trim($site->domain));
        $claimed_roles = isset($parsed['per_tenant'][$tenant])
            ? $parsed['per_tenant'][$tenant]
            : array();
        $selected = infinito_rbac_pick_highest_role($claimed_roles);

        if ($selected !== null) {
            if (!is_user_member_of_blog($user_id, $blog_id)) {
                add_user_to_blog($blog_id, $user_id, $selected);
                $owned[] = $blog_id;
            } else {
                switch_to_blog($blog_id);
                $user_for_blog = new WP_User($user_id);
                $user_for_blog->set_role($selected);
                restore_current_blog();
            }
        } else {
            if (
                is_user_member_of_blog($user_id, $blog_id)
                && in_array($blog_id, $owned, true)
            ) {
                remove_user_from_blog($user_id, $blog_id);
                $owned = array_values(array_filter(
                    $owned,
                    function ($id) use ($blog_id) { return $id !== $blog_id; }
                ));
            } elseif (is_user_member_of_blog($user_id, $blog_id)) {
                // Member by some other channel; per the fallback rule,
                // set their role to subscriber but do NOT remove them.
                switch_to_blog($blog_id);
                $user_for_blog = new WP_User($user_id);
                $user_for_blog->set_role('subscriber');
                restore_current_blog();
            }
        }
    }

    update_user_meta(
        $user_id,
        INFINITO_RBAC_OWNERSHIP_META_KEY,
        array_values(array_unique($owned))
    );
}

/**
 * Map OIDC `groups` claim to a WordPress role.
 *
 * @param \WP_User $user       The user whose role is being set.
 * @param array    $user_claim The OIDC claims as delivered by the IDP.
 */
function infinito_oidc_map_rbac_role($user, $user_claim) {
    if (!($user instanceof WP_User)) {
        return;
    }
    if (!is_array($user_claim)) {
        $user->set_role('subscriber');
        return;
    }
    $groups = isset($user_claim['groups']) ? $user_claim['groups'] : array();
    $parsed = infinito_rbac_parse_claim($groups);

    if (function_exists('is_multisite') && is_multisite()) {
        infinito_rbac_apply_multisite($user, $parsed);
        return;
    }
    infinito_rbac_apply_single_site($user, $parsed);
}
