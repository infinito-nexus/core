<?php
// nocheck: mirrored-unit-test - plugin metadata only Moodle's plugin manager reads; it holds no code path to call
defined('MOODLE_INTERNAL') || die();

$plugin->component = 'local_mfaenforce';
$plugin->version = 2026111200;
$plugin->requires = 2024100700;
$plugin->maturity = MATURITY_STABLE;
$plugin->release = '1.0';
$plugin->dependencies = ['factor_grace' => ANY_VERSION];
