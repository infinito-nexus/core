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
 *         the settings whose stored value differs and the number of such hidden settings
 *   write: last line "CHANGED <n>", n = settings whose stored value differed and was written
 * Exit:
 *   2 malformed payload, 4 a setting is forced in config.php
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

$forced = array_intersect_key($settings, $CFG->forced_plugin_settings[$component] ?? []);
if ($forced) {
    fwrite(STDERR, "set in config.php for {$component}, unable to change: " . implode(', ', array_keys($forced)) . PHP_EOL);
    exit(4);
}

$drifted = [];
foreach ($settings as $name => $value) {
    $old = get_config($component, $name);
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
