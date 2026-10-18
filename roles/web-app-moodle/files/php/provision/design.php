<?php
// nocheck: mirrored-unit-test - a CLI_SCRIPT that requires Moodle's config.php at the top
// level and then writes through set_config, the file storage and the course table; nothing
// loads without a provisioned Moodle install
define('CLI_SCRIPT', true);

require(getenv('MOODLE_CONFIG'));

const MARKER = 'local_infinito_design';

$enabled = getenv('DESIGN_ENABLED') === '1';
$changed = false;
$skipped = [];

$marked = fn(string $key, string $value): bool => sha1($value) === (string) get_config(MARKER, $key);

$plainpanel = (string) get_config('theme_boost', 'loginbackgroundimage') === '' ? 'true' : 'false';
$scss = '$infinito-plain-login-panel: ' . $plainpanel . ";\n"
    . (string) base64_decode((string) getenv('DESIGN_SCSS_B64'), true);

$settings = [
    ['theme_boost', 'brandcolor', (string) getenv('DESIGN_BRAND_COLOR'), ''],
    ['theme_boost', 'scss', $scss, ''],
    ['theme_boost', 'enablecolourmodes', '1', '0'],
    ['theme_boost', 'defaultcolourmode', \theme_boost\colour_mode::AUTO, \theme_boost\colour_mode::LIGHT],
    [null, 'sitenameintitle', 'fullname', 'shortname'],
];
foreach ($settings as [$plugin, $name, $wanted, $default]) {
    $key = ($plugin ?? 'core') . '/' . $name;
    $current = (string) get_config($plugin, $name);
    $owned = $marked($key, $current);
    if (!$enabled) {
        if ($owned) {
            set_config($name, $default, $plugin);
            unset_config($key, MARKER);
            $changed = true;
        }
        continue;
    }
    if ($current === $wanted && $owned) {
        continue;
    }
    if ($current !== $default && $current !== $wanted && !$owned) {
        $skipped[] = $key;
        continue;
    }
    set_config($name, $wanted, $plugin);
    set_config($key, sha1($wanted), MARKER);
    $changed = true;
}

$fs = get_file_storage();
$context = context_system::instance();
$logos = ['logo' => 'DESIGN_LOGO_PATH', 'logocompact' => 'DESIGN_LOGO_COMPACT_PATH', 'favicon' => 'DESIGN_FAVICON_PATH'];
foreach ($logos as $area => $variable) {
    $key = 'core_admin/' . $area;
    $current = (string) get_config('core_admin', $area);
    $stored = $current === '' ? false : $fs->get_file($context->id, 'core_admin', $area, 0, '/', ltrim($current, '/'));
    $owned = $stored && $stored->get_contenthash() === (string) get_config(MARKER, $key);
    $path = $enabled ? (string) getenv($variable) : '';
    if ($path === '') {
        if ($owned) {
            $fs->delete_area_files($context->id, 'core_admin', $area);
            unset_config($area, 'core_admin');
            unset_config($key, MARKER);
            $changed = true;
        }
        continue;
    }
    if ($owned && $stored->get_contenthash() === sha1_file($path)) {
        continue;
    }
    if ($current !== '' && !$owned) {
        $skipped[] = $key;
        continue;
    }
    $fs->delete_area_files($context->id, 'core_admin', $area);
    $file = $fs->create_file_from_pathname([
        'contextid' => $context->id,
        'component' => 'core_admin',
        'filearea' => $area,
        'itemid' => 0,
        'filepath' => '/',
        'filename' => basename($path),
    ], $path);
    set_config($area, '/' . basename($path), 'core_admin');
    set_config($key, $file->get_contenthash(), MARKER);
    $changed = true;
}

$title = (string) getenv('DESIGN_TITLE');
$fullname = (string) $DB->get_field('course', 'fullname', ['id' => SITEID]);
if ($title !== '' && !$marked('core/fullname', $title)) {
    if ($fullname === $title || $marked('core/fullname', $fullname)) {
        $DB->set_field('course', 'fullname', $title, ['id' => SITEID]);
        set_config('core/fullname', sha1($title), MARKER);
        $changed = true;
    } else {
        $skipped[] = 'core/fullname';
    }
}

if ($changed) {
    purge_all_caches();
}

foreach ($skipped as $key) {
    echo 'SKIPPED ' . $key, PHP_EOL;
}
echo $changed ? 'CHANGED' : 'UNCHANGED', PHP_EOL;
