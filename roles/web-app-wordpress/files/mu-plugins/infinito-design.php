<?php
// nocheck: mirrored-unit-test - registers WordPress hooks at load from the infinito_design option; every body only runs inside a booted WordPress request
/**
 * Plugin Name: Infinito.Nexus Corporate Design
 * Description: Registers the corporate admin color scheme, styles the sign-in page and hands the design tokens to the editor canvas, from the infinito_design option the deploy writes.
 */

if (!defined('ABSPATH')) {
    exit;
}

(static function (): void {
    $design = get_option('infinito_design');
    if (!is_array($design)) {
        return;
    }
    $scheme = 'infinito';
    $sheet = static function (string $name) use ($design): string {
        return add_query_arg('v', $design['stylesheets'][$name], content_url($design['directory'] . '/' . $name));
    };

    add_action('admin_init', static function () use ($design, $scheme, $sheet): void {
        wp_admin_css_color(
            $scheme,
            $design['scheme']['name'],
            $sheet('admin.css'),
            $design['scheme']['colors'],
            $design['scheme']['icons']
        );
    }, 2);

    add_action('admin_head', static function () use ($scheme, $sheet): void {
        if (get_user_option('admin_color') !== $scheme) {
            return;
        }
        foreach (['extras.css', 'editor.css'] as $name) {
            printf("<link rel='stylesheet' id='infinito-design-%s' href='%s' media='all' />\n", esc_attr(basename($name, '.css')), esc_url($sheet($name)));
        }
    }, PHP_INT_MAX);

    add_action('wp_enqueue_scripts', static function () use ($scheme, $sheet): void {
        if (is_admin_bar_showing() && get_user_option('admin_color') === $scheme) {
            wp_enqueue_style('infinito-design-admin-bar', $sheet('admin-bar.css'), ['admin-bar'], null);
        }
    });

    add_filter('insert_user_meta', static function (array $meta, $user, bool $update, array $userdata) use ($scheme): array {
        if (!$update && empty($userdata['admin_color'])) {
            $meta['admin_color'] = $scheme;
            $meta['_infinito_design_scheme'] = '1';
        }

        return $meta;
    }, 10, 4);

    add_filter('login_body_class', static function (array $classes) use ($scheme): array {
        return array_map(
            static fn (string $class): string => $class === 'admin-color-modern' ? 'admin-color-' . $scheme : $class,
            $classes
        );
    });

    add_action('login_enqueue_scripts', static function () use ($sheet): void {
        wp_enqueue_style('infinito-design-login', $sheet('login.css'), ['login'], null);
        $logo = wp_get_attachment_image_url((int) get_option('site_logo'), 'full');
        if ($logo) {
            wp_add_inline_style(
                'infinito-design-login',
                sprintf('.login h1 a{background-image:url("%s");background-size:contain}', esc_url_raw($logo))
            );
        }
    });

    add_filter('login_headerurl', static function (): string {
        return home_url('/');
    });

    add_filter('login_headertext', static function (): string {
        return get_bloginfo('name');
    });

    add_action('enqueue_block_assets', static function () use ($design): void {
        if (!is_admin()) {
            return;
        }
        foreach ($design['tokens'] as $index => $url) {
            wp_enqueue_style('infinito-design-tokens-' . $index, $url, [], null);
        }
    });
})();
