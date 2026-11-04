<?php
/**
 * Converge the settings of one Moodle plugin in a single CLI bootstrap, with
 * the per-setting semantics of admin/cli/cfg.php --component --name --set.
 *
 * Env:
 *   MOODLE_CONFIG  absolute path of Moodle's config.php
 * Stdin:
 *   {"component": "<frankenstyle plugin>", "settings": {"<name>": <string|int>, ...}}
 * Stdout:
 *   last line "CHANGED <n>", n = settings whose stored value differed and was written
 * Exit:
 *   2 malformed payload, 4 a setting is forced in config.php
 */
define('CLI_SCRIPT', true);

$payload = json_decode((string) stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
if (
    !is_array($payload)
    || !is_string($payload['component'] ?? null)
    || in_array($payload['component'], ['', 'core', 'moodle'], true)
    || !is_array($payload['settings'] ?? null)
    || array_is_list($payload['settings'])
) {
    fwrite(STDERR, 'stdin must be {"component": "<plugin>", "settings": {"<name>": <value>, ...}}' . PHP_EOL);
    exit(2);
}

$component = $payload['component'];
$settings = [];
foreach ($payload['settings'] as $name => $value) {
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

$changed = 0;
foreach ($settings as $name => $value) {
    $old = get_config($component, $name);
    if ($value !== $old) {
        set_config($name, $value, $component);
        add_to_config_log($name, $old, $value, $component);
        $changed++;
    }
}

echo 'CHANGED ', $changed, PHP_EOL;
