<?php
// nocheck: mirrored-unit-test - runs through wp eval-file inside a booted WordPress and reads the options and the
// global styles posts the corporate design writes; top-level procedural code
/**
 * Required env:
 *   WORDPRESS_DESIGN  base64 of the JSON object design.php applies
 *
 * Stdout: a JSON list of the parts the run is about to overwrite, each a part the site holds other than the last run
 *         wrote it: site_icon, site_logo, global_styles.<theme stylesheet>
 */

$config = json_decode((string) base64_decode((string) getenv('WORDPRESS_DESIGN'), true), true, 32, JSON_THROW_ON_ERROR);
$applied = (get_option('infinito_design') ?: []) + ['logos' => [], 'global_styles' => []];
$pristine = ['version' => WP_Theme_JSON::LATEST_SCHEMA, 'isGlobalStylesUserThemeJSON' => true];
$drifted = [];

foreach (array_keys($config['logos']) as $option) {
    $present = (int) get_option($option);
    if ($present !== 0 && $present !== (int) ($applied['logos'][$option] ?? 0)) {
        $drifted[] = $option;
    }
}

foreach (array_keys($config['global_styles']) as $theme) {
    $posts = get_posts([
        'post_type' => 'wp_global_styles',
        'post_status' => 'publish',
        'numberposts' => 1,
        'orderby' => 'date',
        'order' => 'DESC',
        'tax_query' => [['taxonomy' => 'wp_theme', 'field' => 'name', 'terms' => (string) $theme]],
    ]);
    $present = $posts ? json_decode($posts[0]->post_content, true) : null;
    if (is_array($present) && array_diff_key($present, $pristine) && $present != ($applied['global_styles'][$theme] ?? null)) {
        $drifted[] = 'global_styles.' . $theme;
    }
}

echo json_encode($drifted);
