<?php
/**
 * Env:
 *   MOODLE_CONFIG          absolute path of Moodle's config.php
 *   MOODLE_MFA_GRACE_MODE  enforced, offered or off
 * Stdout:
 *   last line "CHANGED <n>", n = settings written or removed
 * Exit:
 *   2 unknown mode
 */
define('CLI_SCRIPT', true);

$mode = (string) getenv('MOODLE_MFA_GRACE_MODE');
if (!in_array($mode, ['enforced', 'offered', 'off'], true)) {
    fwrite(STDERR, 'MOODLE_MFA_GRACE_MODE must be enforced, offered or off' . PHP_EOL);
    exit(2);
}

require(getenv('MOODLE_CONFIG'));

$owned = get_config('local_mfaenforce', 'grace_by_deploy') === '1';
$wanted = match (true) {
    $mode === 'enforced' => [
        'factor_grace' => ['enabled' => '1', 'forcesetup' => '1'],
        'local_mfaenforce' => [
            'grace_by_deploy' => $owned || get_config('factor_grace', 'enabled') !== '1' ? '1' : null,
        ],
    ],
    $mode === 'off' || $owned => [
        'factor_grace' => ['enabled' => '0'],
        'local_mfaenforce' => ['grace_by_deploy' => null],
    ],
    default => [],
};

$changed = 0;
foreach ($wanted as $plugin => $settings) {
    foreach ($settings as $name => $value) {
        $old = get_config($plugin, $name);
        if ($value === null && $old !== false) {
            unset_config($name, $plugin);
            $changed++;
        } elseif ($value !== null && $value !== $old) {
            set_config($name, $value, $plugin);
            add_to_config_log($name, $old, $value, $plugin);
            $changed++;
        }
    }
}

echo 'CHANGED ', $changed, PHP_EOL;
