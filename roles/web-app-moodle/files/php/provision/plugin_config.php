<?php
/**
 * Read or converge the settings of one Moodle plugin in a single CLI bootstrap, with
 * the per-setting semantics of admin/cli/cfg.php --component --name --set.
 *
 * Env:
 *   MOODLE_CONFIG  absolute path of Moodle's config.php
 * Stdin:
 *   {"component": "<frankenstyle plugin>", "mode": "read"|"write",
 *    "settings": {"<name>": <string|int>, ...}, "hidden": {"<name>": <string|int>, ...}}
 *   hidden: credentials and settings without a form field, compared and written like
 *   settings, their values never printed
 * Stdout:
 *   read: last line {"settings": {"<name>": <stored string|null>, ...}, "hidden": <n>},
 *         the settings whose stored row differs and the number of such hidden settings
 *   write: last line "CHANGED <n>", n = settings whose stored row differed and was written
 *   Both compare the config_plugins rows, never the $CFG->forced_plugin_settings overlay
 *   get_config() returns.
 * Exit:
 *   2 malformed payload, 4 config.php forces a setting to another value
 */
define('CLI_SCRIPT', true);

$payload = json_decode((string) stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
if (
    !is_array($payload)
    || !is_string($payload['component'] ?? null)
    || in_array($payload['component'], ['', 'core', 'moodle'], true)
    || !in_array($payload['mode'] ?? null, ['read', 'write'], true)
    || !is_array($payload['settings'] ?? null)
    || array_is_list($payload['settings'])
    || !is_array($payload['hidden'] ?? null)
    || ($payload['hidden'] !== [] && array_is_list($payload['hidden']))
) {
    fwrite(STDERR, 'stdin must be {"component": "<plugin>", "mode": "read"|"write", "settings": {"<name>": <value>, ...}, "hidden": {"<name>": <value>, ...}}' . PHP_EOL);
    exit(2);
}

$component = $payload['component'];
$overlap = array_intersect_key($payload['settings'], $payload['hidden']);
if ($overlap) {
    fwrite(STDERR, "{$component}: " . implode(', ', array_keys($overlap)) . ' must be either a setting or hidden' . PHP_EOL);
    exit(2);
}

$settings = [];
foreach ($payload['settings'] + $payload['hidden'] as $name => $value) {
    if (!is_string($value) && !is_int($value)) {
        fwrite(STDERR, "{$component}/{$name} must be a string or an integer" . PHP_EOL);
        exit(2);
    }
    $settings[$name] = (string) $value;
}

require(getenv('MOODLE_CONFIG'));

$conflicts = array_keys(array_filter(
    array_intersect_key($CFG->forced_plugin_settings[$component] ?? [], $settings),
    static fn ($forced, $name) => (string) $forced !== $settings[$name],
    ARRAY_FILTER_USE_BOTH
));
if ($conflicts) {
    fwrite(STDERR, "set in config.php for {$component} to another value, unable to change: " . implode(', ', $conflicts) . PHP_EOL);
    exit(4);
}

$stored = $DB->get_records_menu('config_plugins', ['plugin' => $component], '', 'name, value');
$drifted = [];
foreach ($settings as $name => $value) {
    $old = array_key_exists($name, $stored) ? (string) $stored[$name] : false;
    if ($value !== $old) {
        $drifted[$name] = $old;
    }
}

if ($payload['mode'] === 'read') {
    $shown = array_intersect_key($drifted, $payload['settings']);
    echo json_encode(
        [
            'settings' => (object) array_map(static fn ($old) => $old === false ? null : $old, $shown),
            'hidden' => count($drifted) - count($shown),
        ],
        JSON_THROW_ON_ERROR
    ), PHP_EOL;
    exit(0);
}

foreach ($drifted as $name => $old) {
    set_config($name, $settings[$name], $component);
    add_to_config_log($name, $old, $settings[$name], $component);
}

echo 'CHANGED ', count($drifted), PHP_EOL;
