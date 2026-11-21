<?php
// nocheck: mirrored-unit-test - runs only inside Moodle's admin tree build against its live $ADMIN and admin_setting classes
defined('MOODLE_INTERNAL') || die();

if ($hassiteconfig) {
    $settings = new admin_settingpage('local_mfaenforce', new lang_string('pluginname', 'local_mfaenforce'));
    $settings->add(new admin_setting_configcheckbox(
        'local_mfaenforce/enabled',
        new lang_string('enabled', 'local_mfaenforce'),
        new lang_string('enabled_desc', 'local_mfaenforce'),
        0
    ));
    $ADMIN->add('localplugins', $settings);
}
