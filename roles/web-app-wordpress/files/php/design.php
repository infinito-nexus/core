<?php
// nocheck: mirrored-unit-test - runs through wp eval-file inside a booted WordPress and writes options, attachments,
// user meta and the global styles post through WordPress's own functions; top-level procedural code
/**
 * Required env:
 *   WORDPRESS_DESIGN  base64 of a JSON object
 *     enabled       "true" applies the design, anything else withdraws what an earlier run applied
 *     title          site title, "" for none
 *     directory      directory below wp-content that holds the stylesheets and the rendered logo set
 *     logos          {"site_icon": "<file>", "site_logo": "<file>"}, {} for none
 *     stylesheets    file names the mu-plugin enqueues from the directory
 *     global_styles  {"<theme stylesheet>": <user theme.json object>}
 *     scheme         {"name", "colors": [<swatch>, ...], "icons": {"base", "focus", "current"}}
 *     tokens         URLs of the token stylesheets the editor canvas loads
 *
 * Title, site icon, site logo and a global styles post are written only while they are unset or still hold what an
 * earlier run wrote. An account moves from the default admin color scheme to the corporate one once.
 *
 * Stdout, last line: changed | unchanged
 */

require_once ABSPATH . 'wp-admin/includes/image.php';
require_once ABSPATH . 'wp-admin/includes/class-wp-site-icon.php';

const INFINITO_DESIGN_OPTION = 'infinito_design';
const INFINITO_DESIGN_ASSET = '_infinito_design_asset';
const INFINITO_DESIGN_ACCOUNT = '_infinito_design_scheme';
const INFINITO_DESIGN_SCHEME = 'infinito';
const INFINITO_DESIGN_DEFAULT_SCHEME = 'modern';
const INFINITO_DESIGN_STYLES_TYPE = 'wp_global_styles';
const INFINITO_DESIGN_STYLES_TAXONOMY = 'wp_theme';

$config = json_decode((string) base64_decode((string) getenv('WORDPRESS_DESIGN'), true), true, 32, JSON_THROW_ON_ERROR);
$enabled = filter_var($config['enabled'], FILTER_VALIDATE_BOOLEAN);
$directory = WP_CONTENT_DIR . '/' . $config['directory'];
$applied = (get_option(INFINITO_DESIGN_OPTION) ?: [])
    + ['title' => '', 'logos' => [], 'global_styles' => [], 'stylesheets' => []];
$changed = false;

$fail = static function (string $message): void {
    fwrite(STDERR, $message . "\n");
    exit(1);
};

$owned = ['title' => '', 'logos' => [], 'global_styles' => [], 'stylesheets' => []];

$title = $enabled ? (string) $config['title'] : '';
$presentTitle = (string) get_option('blogname');
if ($title !== '') {
    if ($presentTitle === '' || ($presentTitle === $applied['title'] && $presentTitle !== $title)) {
        update_option('blogname', $title);
        $presentTitle = $title;
        $changed = true;
    }
    if ($presentTitle === $title) {
        $owned['title'] = $title;
    }
}

$attachment = static function (string $option, string $file) use (&$changed, $fail): int {
    $bytes = file_get_contents($file);
    if ($bytes === false) {
        $fail("cannot read {$file}");
    }
    $mark = $option . ':' . sha1($bytes);
    $known = get_posts([
        'post_type' => 'attachment',
        'post_status' => 'inherit',
        'meta_key' => INFINITO_DESIGN_ASSET,
        'meta_value' => $mark,
        'fields' => 'ids',
        'numberposts' => 1,
    ]);
    if ($known) {
        return (int) $known[0];
    }
    $name = sprintf('infinito-%s-%s.%s', str_replace('_', '-', $option), substr(sha1($bytes), 0, 12), pathinfo($file, PATHINFO_EXTENSION));
    $upload = wp_upload_bits($name, null, $bytes);
    if (!empty($upload['error'])) {
        $fail("cannot store {$name}: {$upload['error']}");
    }
    $id = wp_insert_attachment(
        ['post_mime_type' => wp_check_filetype($name)['type'], 'post_title' => get_option('blogname'), 'post_status' => 'inherit'],
        $upload['file'],
        0,
        true
    );
    if (is_wp_error($id)) {
        $fail("cannot register {$name}: " . $id->get_error_message());
    }
    $sizes = [new WP_Site_Icon(), 'additional_sizes'];
    if ($option === 'site_icon') {
        add_filter('intermediate_image_sizes_advanced', $sizes);
    }
    wp_update_attachment_metadata($id, wp_generate_attachment_metadata($id, $upload['file']));
    remove_filter('intermediate_image_sizes_advanced', $sizes);
    update_post_meta($id, INFINITO_DESIGN_ASSET, $mark);
    $changed = true;

    return (int) $id;
};

$logos = $enabled ? $config['logos'] : [];
foreach (array_unique(array_merge(array_keys($applied['logos']), array_keys($logos))) as $option) {
    $present = (int) get_option($option);
    $ours = (int) ($applied['logos'][$option] ?? 0);
    if ($present !== 0 && $present !== $ours && get_post($present) !== null) {
        continue;
    }
    if (isset($logos[$option])) {
        $id = $attachment($option, $directory . '/' . $logos[$option]);
        if ($present !== $id) {
            update_option($option, $id);
            $changed = true;
        }
        $owned['logos'][$option] = $id;
    } elseif ($present !== 0) {
        delete_option($option);
        $changed = true;
    }
}
$kept = array_map('intval', array_values($owned['logos']));
$stale = get_posts([
    'post_type' => 'attachment',
    'post_status' => 'inherit',
    'meta_key' => INFINITO_DESIGN_ASSET,
    'fields' => 'ids',
    'numberposts' => -1,
]);
foreach (array_diff(array_map('intval', $stale), $kept) as $id) {
    wp_delete_attachment($id, true);
    $changed = true;
}

$stylesPost = static function (string $theme): ?WP_Post {
    $posts = get_posts([
        'post_type' => INFINITO_DESIGN_STYLES_TYPE,
        'post_status' => 'publish',
        'numberposts' => 1,
        'orderby' => 'date',
        'order' => 'DESC',
        'tax_query' => [['taxonomy' => INFINITO_DESIGN_STYLES_TAXONOMY, 'field' => 'name', 'terms' => $theme]],
    ]);

    return $posts ? $posts[0] : null;
};
$pristine = ['version' => WP_Theme_JSON::LATEST_SCHEMA, 'isGlobalStylesUserThemeJSON' => true];
$styles = $enabled ? $config['global_styles'] : [];
kses_remove_filters();
foreach (array_unique(array_merge(array_keys($applied['global_styles']), array_keys($styles))) as $theme) {
    $post = $stylesPost((string) $theme);
    $present = $post === null ? null : json_decode($post->post_content, true);
    $ours = $applied['global_styles'][$theme] ?? null;
    $untouched = $present === null || $present == $ours || !array_diff_key($present, $pristine);
    if (!$untouched) {
        continue;
    }
    $wanted = $styles[$theme] ?? null;
    if ($wanted !== null) {
        $owned['global_styles'][$theme] = $wanted;
    }
    $content = $wanted ?? $pristine;
    if ($present == $content || ($present === null && $wanted === null)) {
        continue;
    }
    $data = [
        'post_content' => wp_slash(wp_json_encode($content)),
        'post_status' => 'publish',
        'post_title' => 'Custom Styles',
        'post_type' => INFINITO_DESIGN_STYLES_TYPE,
        'post_name' => sprintf('wp-global-styles-%s', urlencode((string) $theme)),
    ];
    $id = $post === null ? wp_insert_post($data, true) : wp_update_post(['ID' => $post->ID] + $data, true);
    if (is_wp_error($id)) {
        $fail("cannot write the global styles of {$theme}: " . $id->get_error_message());
    }
    wp_set_object_terms($id, (string) $theme, INFINITO_DESIGN_STYLES_TAXONOMY);
    $changed = true;
}
wp_clean_theme_json_cache();

if ($enabled) {
    foreach (get_users(['fields' => 'ID']) as $id) {
        if (get_user_meta((int) $id, INFINITO_DESIGN_ACCOUNT, true) !== '') {
            continue;
        }
        if (in_array(get_user_meta((int) $id, 'admin_color', true), ['', INFINITO_DESIGN_DEFAULT_SCHEME], true)) {
            update_user_meta((int) $id, 'admin_color', INFINITO_DESIGN_SCHEME);
        }
        update_user_meta((int) $id, INFINITO_DESIGN_ACCOUNT, '1');
        $changed = true;
    }
    foreach ($config['stylesheets'] as $name) {
        $hash = sha1_file($directory . '/' . $name);
        if ($hash === false) {
            $fail("cannot read {$directory}/{$name}");
        }
        $owned['stylesheets'][$name] = substr($hash, 0, 12);
    }
} else {
    foreach (get_users(['fields' => 'ID', 'meta_key' => 'admin_color', 'meta_value' => INFINITO_DESIGN_SCHEME]) as $id) {
        update_user_meta((int) $id, 'admin_color', INFINITO_DESIGN_DEFAULT_SCHEME);
        $changed = true;
    }
    foreach (get_users(['fields' => 'ID', 'meta_key' => INFINITO_DESIGN_ACCOUNT]) as $id) {
        delete_user_meta((int) $id, INFINITO_DESIGN_ACCOUNT);
        $changed = true;
    }
    if (is_dir($directory)) {
        $entries = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($directory, FilesystemIterator::SKIP_DOTS),
            RecursiveIteratorIterator::CHILD_FIRST
        );
        foreach ($entries as $entry) {
            $entry->isDir() ? rmdir($entry->getPathname()) : unlink($entry->getPathname());
        }
        rmdir($directory);
        $changed = true;
    }
}

$state = $enabled
    ? $owned + ['directory' => $config['directory'], 'scheme' => $config['scheme'], 'tokens' => $config['tokens']]
    : false;
if ($state != get_option(INFINITO_DESIGN_OPTION)) {
    $state === false ? delete_option(INFINITO_DESIGN_OPTION) : update_option(INFINITO_DESIGN_OPTION, $state, true);
    $changed = true;
}

echo $changed ? "changed\n" : "unchanged\n";
