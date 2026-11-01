<?php
// nocheck: mirrored-unit-test - registers add_action hooks at load and maps roles through WordPress user objects the core supplies
/**
 * Plugin Name: Infinito.Nexus OIDC RBAC Role Mapper
 * Description: Maps the Keycloak claims delivered by
 *              daggerhart/openid-connect-generic to the WordPress role and
 *              profile of the user on every OIDC login, marks profile.php
 *              and user-edit.php of an OIDC account for the shared lock
 *              renderer, and keeps the IdP-managed fields on every other
 *              wp_insert_user write.
 * Version:     2.2.0
 * Author:      Infinito.Nexus
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
add_action('openid-connect-generic-user-create', 'infinito_oidc_sync_profile', 20, 2);
add_action(
    'openid-connect-generic-update-user-using-current-claim',
    'infinito_oidc_sync_profile',
    20,
    2
);
add_filter('admin_body_class', 'infinito_oidc_lock_managed_profile_fields');
add_action('personal_options_update', 'infinito_oidc_keep_managed_profile_fields', 1);
add_filter('wp_pre_insert_user_data', 'infinito_oidc_keep_managed_user_data', 10, 3);
add_filter('insert_user_meta', 'infinito_oidc_keep_managed_user_meta', 10, 3);
add_filter('send_email_change_email', 'infinito_oidc_mail_email_change', 10, 2);

const INFINITO_RBAC_OWNERSHIP_META_KEY = '_infinito_oidc_added_blog_ids';
const INFINITO_RBAC_SUPER_ADMIN_META_KEY = '_infinito_oidc_granted_super_admin';
const INFINITO_OIDC_SUBJECT_META_KEY = 'openid-connect-generic-subject-identity';
const INFINITO_OIDC_MANAGED_PROFILE_CLASS = 'infinito-sso-managed';
const INFINITO_OIDC_MANAGED_USER_FIELDS = array('user_email', 'user_url', 'display_name');
const INFINITO_OIDC_MANAGED_META_FIELDS = array('first_name', 'last_name', 'locale');
const INFINITO_OIDC_PROFILE_SYNC_HOOK = 'infinito_oidc_profile_sync_running';

/**
 * @param string $name Environment variable the role renders into the container.
 * @return string Its value; throws when the deployment did not set it.
 */
function infinito_oidc_env($name) {
    $value = getenv($name);
    if (!is_string($value) || $value === '') {
        throw new RuntimeException($name . ' is not set in the WordPress container environment');
    }
    return $value;
}

/**
 * @return array Group path => array('role' => <WP role>, 'tenant' => <site domain>) or array('network' => true).
 */
function infinito_rbac_group_map() {
    $map = json_decode(infinito_oidc_env('WORDPRESS_RBAC_GROUP_MAP'), true, 8, JSON_THROW_ON_ERROR);
    if (!is_array($map)) {
        throw new RuntimeException('WORDPRESS_RBAC_GROUP_MAP is not a JSON object');
    }
    return $map;
}

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
 * @param mixed $groups The groups claim.
 * @param array $map    The group map from infinito_rbac_group_map().
 * @return array array('global' => roles, 'per_tenant' => tenant => roles, 'network_admin' => bool).
 */
function infinito_rbac_parse_claim($groups, $map) {
    $parsed = array(
        'global' => array(),
        'per_tenant' => array(),
        'network_admin' => false,
    );
    if (!is_array($groups)) {
        return $parsed;
    }
    foreach ($groups as $group) {
        if (!is_string($group) || !isset($map[$group]) || !is_array($map[$group])) {
            continue;
        }
        $entry = $map[$group];
        if (!empty($entry['network'])) {
            $parsed['network_admin'] = true;
            continue;
        }
        if (!isset($entry['role']) || !is_string($entry['role'])) {
            continue;
        }
        if (isset($entry['tenant']) && is_string($entry['tenant']) && $entry['tenant'] !== '') {
            $tenant = strtolower($entry['tenant']);
            if (!isset($parsed['per_tenant'][$tenant])) {
                $parsed['per_tenant'][$tenant] = array();
            }
            $parsed['per_tenant'][$tenant][] = $entry['role'];
            continue;
        }
        $parsed['global'][] = $entry['role'];
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

function infinito_rbac_apply_single_site($user, $parsed) {
    $selected = infinito_rbac_pick_highest_role($parsed['global']);
    if ($selected === null) {
        $selected = 'subscriber';
    }
    $user->set_role($selected);
}

function infinito_rbac_apply_super_admin($user_id, $is_network_admin) {
    if ($is_network_admin) {
        if (!is_super_admin($user_id)) {
            grant_super_admin($user_id);
            update_user_meta($user_id, INFINITO_RBAC_SUPER_ADMIN_META_KEY, 1);
        }
        return;
    }
    if (get_user_meta($user_id, INFINITO_RBAC_SUPER_ADMIN_META_KEY, true)) {
        revoke_super_admin($user_id);
        delete_user_meta($user_id, INFINITO_RBAC_SUPER_ADMIN_META_KEY);
    }
}

function infinito_rbac_apply_multisite($user, $parsed) {
    $user_id = (int) $user->ID;

    infinito_rbac_apply_super_admin($user_id, $parsed['network_admin']);

    $owned = get_user_meta($user_id, INFINITO_RBAC_OWNERSHIP_META_KEY, true);
    if (!is_array($owned)) {
        $owned = array();
    }

    $sites = function_exists('get_sites') ? get_sites(array('number' => 0)) : array();
    foreach ($sites as $site) {
        $blog_id = (int) $site->blog_id;
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
    $claim = infinito_oidc_env('WORDPRESS_OIDC_CLAIM_GROUPS');
    $groups = isset($user_claim[$claim]) ? $user_claim[$claim] : array();
    $parsed = infinito_rbac_parse_claim($groups, infinito_rbac_group_map());

    if (function_exists('is_multisite') && is_multisite()) {
        infinito_rbac_apply_multisite($user, $parsed);
        return;
    }
    infinito_rbac_apply_single_site($user, $parsed);
}

/**
 * @param array  $user_claim The OIDC claims.
 * @param string $env_name   Environment variable naming the claim.
 * @return string The trimmed claim value, '' when the claim is absent or not a string.
 */
function infinito_oidc_claim_string($user_claim, $env_name) {
    $claim = infinito_oidc_env($env_name);
    if (!isset($user_claim[$claim]) || !is_string($user_claim[$claim])) {
        return '';
    }
    return trim($user_claim[$claim]);
}

/**
 * @param string $value A BCP 47 or POSIX locale such as `de`, `de-DE` or `de_DE`.
 * @return string The installed WordPress locale it names, its normalised form otherwise, '' for none.
 */
function infinito_oidc_wp_locale($value) {
    if ($value === '') {
        return '';
    }
    $parts = explode('_', str_replace('-', '_', $value));
    $locale = strtolower($parts[0]);
    if (isset($parts[1]) && $parts[1] !== '') {
        $locale .= '_' . strtoupper($parts[1]);
    }
    if ($locale === 'en') {
        return 'en_US';
    }
    $installed = get_available_languages();
    if (in_array($locale, $installed, true)) {
        return $locale;
    }
    foreach ($installed as $candidate) {
        if (strpos($candidate, $locale . '_') === 0) {
            return $candidate;
        }
    }
    return $locale;
}

/**
 * @param \WP_User $user       The user whose profile is overwritten from the IdP.
 * @param array    $user_claim The OIDC claims as delivered by the IDP.
 */
function infinito_oidc_sync_profile($user, $user_claim) {
    if (!($user instanceof WP_User) || !is_array($user_claim)) {
        return;
    }
    $update = array(
        'ID' => (int) $user->ID,
        'first_name' => infinito_oidc_claim_string($user_claim, 'WORDPRESS_OIDC_CLAIM_GIVEN_NAME'),
        'last_name' => infinito_oidc_claim_string($user_claim, 'WORDPRESS_OIDC_CLAIM_FAMILY_NAME'),
        'user_url' => esc_url_raw(infinito_oidc_claim_string($user_claim, 'WORDPRESS_OIDC_CLAIM_WEBSITE')),
        'locale' => infinito_oidc_wp_locale(infinito_oidc_claim_string($user_claim, 'WORDPRESS_OIDC_CLAIM_LOCALE')),
    );
    $display_name = infinito_oidc_claim_string($user_claim, 'WORDPRESS_OIDC_CLAIM_NAME');
    if ($display_name !== '') {
        $update['display_name'] = $display_name;
    }
    $email = infinito_oidc_claim_string($user_claim, 'WORDPRESS_OIDC_CLAIM_EMAIL');
    if (is_email($email)) {
        $update['user_email'] = $email;
    }

    add_filter('send_email_change_email', '__return_false');
    add_filter(INFINITO_OIDC_PROFILE_SYNC_HOOK, '__return_true');
    $result = wp_update_user($update);
    remove_filter(INFINITO_OIDC_PROFILE_SYNC_HOOK, '__return_true');
    remove_filter('send_email_change_email', '__return_false');

    if (is_wp_error($result)) {
        error_log(sprintf(
            'infinito-oidc-rbac-mapper: profile sync of user %d failed: %s',
            (int) $user->ID,
            $result->get_error_message()
        ));
    }
}

/**
 * @param int $user_id The user to check.
 * @return bool True when the account signs in through the OIDC plugin, so the IdP owns its profile.
 */
function infinito_oidc_is_managed_user($user_id) {
    return get_user_meta((int) $user_id, INFINITO_OIDC_SUBJECT_META_KEY, true) !== '';
}

/**
 * @param string $classes The admin body classes.
 * @return string The classes plus the one the services.sso.profile.locked selectors match when profile.php or
 *                user-edit.php renders an OIDC account; user-edit.php sets the global $user_id to the edited
 *                account before admin-header.php applies this filter.
 */
function infinito_oidc_lock_managed_profile_fields($classes) {
    global $pagenow, $user_id;
    if (!in_array($pagenow, array('profile.php', 'user-edit.php'), true) || !infinito_oidc_is_managed_user((int) $user_id)) {
        return $classes;
    }
    return $classes . ' ' . INFINITO_OIDC_MANAGED_PROFILE_CLASS;
}

/**
 * @param int $user_id The user saving their own profile; restoring the IdP-managed fields before
 *                     send_confirmation_on_profile_email runs keeps WordPress from mailing a confirmation link to a
 *                     submitted address.
 */
function infinito_oidc_keep_managed_profile_fields($user_id) {
    if (!infinito_oidc_is_managed_user($user_id)) {
        return;
    }
    $user = get_userdata((int) $user_id);
    if (!($user instanceof WP_User)) {
        return;
    }
    $_POST['first_name'] = wp_slash($user->first_name);
    $_POST['last_name'] = wp_slash($user->last_name);
    $_POST['email'] = wp_slash($user->user_email);
    $_POST['url'] = wp_slash($user->user_url);
    unset($_POST['display_name'], $_POST['locale']);
}

/**
 * @param bool $update  Whether wp_insert_user updates an existing account.
 * @param int  $user_id The account it writes.
 * @return bool True when the write keeps the IdP-managed fields: an update of an OIDC account outside
 *              infinito_oidc_sync_profile and outside WP-CLI, the break-glass path.
 */
function infinito_oidc_profile_write_is_guarded($update, $user_id) {
    return $update
        && !apply_filters(INFINITO_OIDC_PROFILE_SYNC_HOOK, false)
        && !(defined('WP_CLI') && WP_CLI)
        && infinito_oidc_is_managed_user($user_id);
}

/**
 * @param array $data    The users-table row wp_insert_user writes.
 * @param bool  $update  Whether it updates an existing account.
 * @param int   $user_id The account it updates.
 * @return array The row with the stored email, website and display name of an OIDC account.
 */
function infinito_oidc_keep_managed_user_data($data, $update, $user_id) {
    if (!infinito_oidc_profile_write_is_guarded($update, $user_id)) {
        return $data;
    }
    $stored = get_userdata((int) $user_id);
    foreach (INFINITO_OIDC_MANAGED_USER_FIELDS as $field) {
        $data[$field] = $stored->$field;
    }
    return $data;
}

/**
 * @param array    $meta   The user meta wp_insert_user writes.
 * @param \WP_User $user   The account it writes them for.
 * @param bool     $update Whether it updates an existing account.
 * @return array The meta with the stored first name, last name and locale of an OIDC account.
 */
function infinito_oidc_keep_managed_user_meta($meta, $user, $update) {
    if (!($user instanceof WP_User) || !infinito_oidc_profile_write_is_guarded($update, $user->ID)) {
        return $meta;
    }
    foreach (INFINITO_OIDC_MANAGED_META_FIELDS as $key) {
        $meta[$key] = get_user_meta($user->ID, $key, true);
    }
    return $meta;
}

/**
 * @param bool  $send Whether wp_update_user mails the email change notice.
 * @param array $user The account before the update.
 * @return bool False for an OIDC account: the notice is decided before the guard keeps the stored email.
 */
function infinito_oidc_mail_email_change($send, $user) {
    return $send && !infinito_oidc_is_managed_user($user['ID']);
}
