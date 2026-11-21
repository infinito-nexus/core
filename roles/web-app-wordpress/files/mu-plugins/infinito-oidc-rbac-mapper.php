<?php
/**
 * Plugin Name: Infinito.Nexus OIDC RBAC Role Mapper
 * Description: Maps the Keycloak claims delivered by
 *              daggerhart/openid-connect-generic to the WordPress role and
 *              profile of the user on every OIDC login, marks profile.php
 *              and user-edit.php of an OIDC account for the shared lock
 *              renderer, and keeps the IdP-managed fields on every other
 *              wp_insert_user write.
 * Version:     2.3.0
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
const INFINITO_OIDC_LOCKABLE_FIELDS = array(
    'first_name' => array('meta' => 'first_name', 'input' => 'first_name', 'submit' => 'restore'),
    'last_name' => array('meta' => 'last_name', 'input' => 'last_name', 'submit' => 'restore'),
    'display_name' => array('column' => 'display_name', 'input' => 'display_name', 'submit' => 'drop'),
    'email' => array('column' => 'user_email', 'input' => 'email', 'submit' => 'restore'),
    'website' => array('column' => 'user_url', 'input' => 'url', 'submit' => 'restore'),
    'language' => array('meta' => 'locale', 'input' => 'locale', 'submit' => 'drop'),
);
const INFINITO_OIDC_PROFILE_SYNC_HOOK = 'infinito_oidc_profile_sync_running';
const INFINITO_RBAC_MEMBER_LABEL = '/^(?:[a-z1-9]+|[a-z1-9]{4}0[a-z1-9]+)$/';
const INFINITO_RBAC_MEMBER_LABEL_MAX = 63;
const INFINITO_RBAC_ILLEGAL_LABELS = array('www', 'web', 'root', 'admin', 'main', 'invite', 'administrator', 'files', 'blog');
const INFINITO_RBAC_SITE_SUBJECT_META_KEY = 'infinito_site_owner_subject';
const INFINITO_RBAC_SITE_LOGIN_META_KEY = 'infinito_site_owner_login';

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
 * @return array Group path => array('role' => <WP role>, 'tenant' => <site domain>), array('network' => true) or array('site_owner' => true).
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
 * @return array array('global' => roles, 'per_tenant' => tenant => roles, 'network_admin' => bool, 'site_owner' => bool).
 */
function infinito_rbac_parse_claim($groups, $map) {
    $parsed = array(
        'global' => array(),
        'per_tenant' => array(),
        'network_admin' => false,
        'site_owner' => false,
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
        if (!empty($entry['site_owner'])) {
            $parsed['site_owner'] = true;
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

/**
 * @param string $login A login exactly as Keycloak delivers it.
 * @return bool True when the login names a member host: a Keycloak username that fits a DNS label and is no WordPress illegal name.
 */
function infinito_rbac_is_member_label($login) {
    return strlen($login) <= INFINITO_RBAC_MEMBER_LABEL_MAX
        && preg_match(INFINITO_RBAC_MEMBER_LABEL, $login) === 1
        && !in_array($login, INFINITO_RBAC_ILLEGAL_LABELS, true);
}

/**
 * @param string $login The login of the member whose own site is resolved.
 * @return array array('domain' => <site domain>, 'url' => <site base URL>); throws when the login names no member host.
 */
function infinito_rbac_site_owner_site($login) {
    if (!infinito_rbac_is_member_label($login)) {
        throw new RuntimeException(sprintf('login %s names no site-owner host', $login));
    }
    $base = infinito_oidc_env('WORDPRESS_SITE_OWNER_BASE_URL');
    $scheme = parse_url($base, PHP_URL_SCHEME);
    $parent = parse_url($base, PHP_URL_HOST);
    if (!is_string($scheme) || !is_string($parent)) {
        throw new RuntimeException('WORDPRESS_SITE_OWNER_BASE_URL is no absolute URL: ' . $base);
    }
    $domain = $login . '.' . strtolower($parent);
    return array('domain' => $domain, 'url' => $scheme . '://' . $domain);
}

/**
 * @param string $domain The domain of an own site.
 * @return \WP_Site|null The site on that domain.
 */
function infinito_rbac_find_site($domain) {
    $found = get_sites(array('domain' => $domain, 'path' => '/', 'number' => 1));
    return $found ? $found[0] : null;
}

/**
 * @param int    $blog_id The site on the member's own domain.
 * @param string $login   The member's login.
 * @param string $subject The member's OIDC subject.
 * @return bool True when the site records this subject, or records none and the deploy reserved it for this login.
 */
function infinito_rbac_site_matches($blog_id, $login, $subject) {
    $recorded = (string) get_site_meta($blog_id, INFINITO_RBAC_SITE_SUBJECT_META_KEY, true);
    if ($recorded !== '') {
        return hash_equals($recorded, $subject);
    }
    return (string) get_site_meta($blog_id, INFINITO_RBAC_SITE_LOGIN_META_KEY, true) === $login;
}

/**
 * @param array  $own     The result of infinito_rbac_site_owner_site().
 * @param int    $user_id The user wp_insert_site() makes the administrator.
 * @param string $key     The site meta key that marks the owner.
 * @param string $value   The owner it records: the member's subject or reserved login.
 * @return int Blog id of the created site; throws when WordPress creates no site or keeps no owner.
 */
function infinito_rbac_insert_own_site($own, $user_id, $key, $value) {
    $created = wp_insert_site(array(
        'domain' => $own['domain'],
        'path' => '/',
        'title' => $own['domain'],
        'user_id' => $user_id,
        'options' => array('home' => $own['url'], 'siteurl' => $own['url']),
        'meta' => array($key => $value),
    ));
    if (is_wp_error($created)) {
        throw new RuntimeException($own['domain'] . ': ' . $created->get_error_message());
    }
    if ((string) get_site_meta((int) $created, $key, true) !== $value) {
        throw new RuntimeException(sprintf('site %d keeps no %s', (int) $created, $key));
    }
    return (int) $created;
}

/**
 * @param int    $blog_id The site the deploy reserved for the member.
 * @param int    $user_id The member signing in for the first time.
 * @param string $subject The member's OIDC subject.
 */
function infinito_rbac_claim_reserved_site($blog_id, $user_id, $subject) {
    update_site_meta($blog_id, INFINITO_RBAC_SITE_SUBJECT_META_KEY, $subject);
    if ((string) get_site_meta($blog_id, INFINITO_RBAC_SITE_SUBJECT_META_KEY, true) !== $subject) {
        throw new RuntimeException(sprintf('site %d keeps no owner subject', $blog_id));
    }
    foreach (get_users(array('blog_id' => $blog_id, 'fields' => 'ID')) as $member_id) {
        if ((int) $member_id !== $user_id) {
            remove_user_from_blog((int) $member_id, $blog_id);
        }
    }
}

/**
 * @param string $login    The inventory login whose own site the deploy reserves.
 * @param int    $owner_id The user who administers the site until its member signs in and claims it.
 * @return bool True when this call created the site; throws when the login names no host or another account holds its domain.
 */
function infinito_rbac_reserve_own_site($login, $owner_id) {
    $own = infinito_rbac_site_owner_site($login);
    $site = infinito_rbac_find_site($own['domain']);
    if ($site === null) {
        infinito_rbac_insert_own_site($own, $owner_id, INFINITO_RBAC_SITE_LOGIN_META_KEY, $login);
        return true;
    }
    $blog_id = (int) $site->blog_id;
    $reserved = (string) get_site_meta($blog_id, INFINITO_RBAC_SITE_LOGIN_META_KEY, true);
    $subject = (string) get_site_meta($blog_id, INFINITO_RBAC_SITE_SUBJECT_META_KEY, true);
    if ($reserved === $login || ($reserved === '' && $subject !== '')) {
        return false;
    }
    throw new RuntimeException(sprintf('%s is site %d of another account', $own['domain'], $blog_id));
}

/**
 * @param string[] $members The logins of every inventory site-owner member.
 * @return string[] The logins whose reserved site this call archived; their sessions end on every site.
 */
function infinito_rbac_archive_reserved_sites_of_former_members($members) {
    $archived = array();
    $reserved = get_sites(array(
        'number' => 0,
        'meta_query' => array(array('key' => INFINITO_RBAC_SITE_LOGIN_META_KEY, 'compare' => 'EXISTS')),
    ));
    foreach ($reserved as $site) {
        $login = (string) get_site_meta((int) $site->blog_id, INFINITO_RBAC_SITE_LOGIN_META_KEY, true);
        if (in_array($login, $members, true) || (int) $site->archived === 1) {
            continue;
        }
        infinito_rbac_update_site((int) $site->blog_id, array('archived' => 1));
        $user = get_user_by('login', $login);
        if ($user instanceof WP_User) {
            WP_Session_Tokens::get_instance((int) $user->ID)->destroy_all();
        }
        $archived[] = $login;
    }
    return $archived;
}

/**
 * @param int   $blog_id The site to update.
 * @param array $data    The site fields wp_update_site() writes.
 */
function infinito_rbac_update_site($blog_id, $data) {
    $updated = wp_update_site($blog_id, $data);
    if (is_wp_error($updated)) {
        throw new RuntimeException(sprintf('site %d: %s', $blog_id, $updated->get_error_message()));
    }
}

/**
 * @param \WP_User $user          The user signing in.
 * @param bool     $is_site_owner True when the groups claim names the site-owner group.
 * @param string   $subject       The OIDC subject of the user, '' when the claim carries none.
 * @param string   $login         The raw username claim, '' when the claim carries none.
 * @return int Blog id of the user's own site, 0 when the user has none; throws when the step cannot complete.
 */
function infinito_rbac_apply_site_owner($user, $is_site_owner, $subject, $login) {
    $user_id = (int) $user->ID;
    if ($login !== (string) $user->user_login) {
        throw new RuntimeException(sprintf('the username claim of user %d differs from its login', $user_id));
    }
    if (!infinito_rbac_is_member_label($login)) {
        if ($is_site_owner) {
            throw new RuntimeException(sprintf('site-owner member %s names no own site', $login));
        }
        return 0;
    }
    if ($subject === '') {
        throw new RuntimeException(sprintf('the claims of %s carry no subject', $login));
    }

    $own = infinito_rbac_site_owner_site($login);
    $site = infinito_rbac_find_site($own['domain']);
    if ($site !== null && !infinito_rbac_site_matches((int) $site->blog_id, $login, $subject)) {
        throw new RuntimeException(sprintf('%s is site %d of another account', $own['domain'], (int) $site->blog_id));
    }

    if (!$is_site_owner) {
        if ($site === null) {
            return 0;
        }
        if ((int) $site->archived !== 1) {
            infinito_rbac_update_site((int) $site->blog_id, array('archived' => 1));
        }
        return (int) $site->blog_id;
    }

    if ($site === null) {
        return infinito_rbac_insert_own_site($own, $user_id, INFINITO_RBAC_SITE_SUBJECT_META_KEY, $subject);
    }

    $blog_id = (int) $site->blog_id;
    if ((string) get_site_meta($blog_id, INFINITO_RBAC_SITE_SUBJECT_META_KEY, true) === '') {
        infinito_rbac_claim_reserved_site($blog_id, $user_id, $subject);
    }
    if ((int) $site->archived === 1) {
        infinito_rbac_update_site($blog_id, array('archived' => 0));
    }
    if (!is_user_member_of_blog($user_id, $blog_id)) {
        $added = add_user_to_blog($blog_id, $user_id, 'administrator');
        if (is_wp_error($added)) {
            throw new RuntimeException($own['domain'] . ': ' . $added->get_error_message());
        }
        return $blog_id;
    }
    switch_to_blog($blog_id);
    $owner = new WP_User($user_id);
    if (!in_array('administrator', (array) $owner->roles, true)) {
        $owner->set_role('administrator');
    }
    restore_current_blog();
    return $blog_id;
}

/**
 * @param string $domain        The own domain of the account's login, '' when the login names none.
 * @param string $login         The account's login.
 * @param bool   $is_site_owner True when the groups grant site-owner.
 * @param string $subject       The OIDC subject of the user, '' when the claim carries none.
 * @return int Blog id of the own site the groups grant the user, 0 when they grant none.
 */
function infinito_rbac_granted_own_site($domain, $login, $is_site_owner, $subject) {
    $site = $is_site_owner && $domain !== '' ? infinito_rbac_find_site($domain) : null;
    return $site !== null && infinito_rbac_site_matches((int) $site->blog_id, $login, $subject)
        ? (int) $site->blog_id
        : 0;
}

/**
 * A failure on the own site is logged and skips only that site, because it
 * must not block the sign-in to every other site of the network.
 *
 * @param \WP_User $user    The user signing in.
 * @param array    $parsed  The result of infinito_rbac_parse_claim().
 * @param string   $subject The OIDC subject of the user, '' when the claim carries none.
 * @param string   $login   The raw username claim, '' when the claim carries none.
 */
function infinito_rbac_apply_multisite($user, $parsed, $subject, $login) {
    $user_id = (int) $user->ID;

    infinito_rbac_apply_super_admin($user_id, $parsed['network_admin']);
    $own_blog_id = 0;
    if (infinito_oidc_env('WORDPRESS_SITE_OWNER_ENABLED') === 'true') {
        $account = (string) $user->user_login;
        $own_domain = '';
        try {
            $own_domain = infinito_rbac_is_member_label($account) ? infinito_rbac_site_owner_site($account)['domain'] : '';
            $own_blog_id = infinito_rbac_apply_site_owner($user, $parsed['site_owner'], $subject, $login);
        } catch (RuntimeException $error) {
            error_log(sprintf(
                'infinito-oidc-rbac-mapper: own site of user %d skipped: %s',
                $user_id,
                $error->getMessage()
            ));
            $own_blog_id = infinito_rbac_granted_own_site($own_domain, $account, $parsed['site_owner'], $subject);
        }
    }

    $owned = get_user_meta($user_id, INFINITO_RBAC_OWNERSHIP_META_KEY, true);
    if (!is_array($owned)) {
        $owned = array();
    }

    $sites = function_exists('get_sites') ? get_sites(array('number' => 0)) : array();
    foreach ($sites as $site) {
        $blog_id = (int) $site->blog_id;
        if ($blog_id === $own_blog_id) {
            continue;
        }
        $tenant = strtolower(trim($site->domain));
        $claimed_roles = array_merge(
            $parsed['global'],
            isset($parsed['per_tenant'][$tenant]) ? $parsed['per_tenant'][$tenant] : array()
        );
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
        $subject = isset($user_claim['sub']) && is_string($user_claim['sub']) ? $user_claim['sub'] : '';
        $login = infinito_oidc_claim_string($user_claim, 'WORDPRESS_OIDC_CLAIM_USERNAME');
        infinito_rbac_apply_multisite($user, $parsed, $subject, $login);
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
 * @return array The INFINITO_OIDC_LOCKABLE_FIELDS entries of the sso.<claim> field keys of meta/forms.yml that
 *               WORDPRESS_OIDC_PROFILE_LOCKED lists, by key; throws when the variable is no non-empty JSON list or
 *               names a field the mapper cannot keep.
 */
function infinito_oidc_locked_fields() {
    $keys = json_decode(infinito_oidc_env('WORDPRESS_OIDC_PROFILE_LOCKED'), true);
    if (!is_array($keys) || $keys === array() || array_values($keys) !== $keys) {
        throw new RuntimeException('WORDPRESS_OIDC_PROFILE_LOCKED is not a non-empty JSON list');
    }
    $fields = array();
    foreach ($keys as $key) {
        if (!is_string($key) || !isset(INFINITO_OIDC_LOCKABLE_FIELDS[$key])) {
            throw new RuntimeException('WORDPRESS_OIDC_PROFILE_LOCKED names ' . json_encode($key) . ', a profile field the mapper cannot keep');
        }
        $fields[$key] = INFINITO_OIDC_LOCKABLE_FIELDS[$key];
    }
    return $fields;
}

/**
 * @param string $storage `column` for users-table columns, `meta` for user meta.
 * @return string[] The locked fields stored there.
 */
function infinito_oidc_locked_storage($storage) {
    return array_column(infinito_oidc_locked_fields(), $storage);
}

/**
 * @param string $classes The admin body classes.
 * @return string The classes plus the one the selectors of the sso.<claim> fields match when profile.php or
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
 * @param int $user_id The user saving their own profile; restoring the locked fields before
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
    foreach (infinito_oidc_locked_fields() as $field) {
        if ($field['submit'] === 'restore') {
            $stored = isset($field['column']) ? $field['column'] : $field['meta'];
            $_POST[$field['input']] = wp_slash($user->$stored);
        } else {
            unset($_POST[$field['input']]);
        }
    }
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
 * @return array The row with the stored locked columns of an OIDC account.
 */
function infinito_oidc_keep_managed_user_data($data, $update, $user_id) {
    if (!infinito_oidc_profile_write_is_guarded($update, $user_id)) {
        return $data;
    }
    $stored = get_userdata((int) $user_id);
    foreach (infinito_oidc_locked_storage('column') as $field) {
        $data[$field] = $stored->$field;
    }
    return $data;
}

/**
 * @param array    $meta   The user meta wp_insert_user writes.
 * @param \WP_User $user   The account it writes them for.
 * @param bool     $update Whether it updates an existing account.
 * @return array The meta with the stored locked meta of an OIDC account.
 */
function infinito_oidc_keep_managed_user_meta($meta, $user, $update) {
    if (!($user instanceof WP_User) || !infinito_oidc_profile_write_is_guarded($update, $user->ID)) {
        return $meta;
    }
    foreach (infinito_oidc_locked_storage('meta') as $key) {
        $meta[$key] = get_user_meta($user->ID, $key, true);
    }
    return $meta;
}

/**
 * @param bool  $send Whether wp_update_user mails the email change notice.
 * @param array $user The account before the update.
 * @return bool False for an OIDC account while its email is locked: the notice is decided before the guard keeps
 *              the stored email.
 */
function infinito_oidc_mail_email_change($send, $user) {
    return $send && !(infinito_oidc_is_managed_user($user['ID']) && in_array('user_email', infinito_oidc_locked_storage('column'), true));
}
