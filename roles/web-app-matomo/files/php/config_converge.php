<?php

/**
 * Converge keys of Matomo's config.ini.php.
 *
 * Env:
 *   MATOMO_CONFIG_SECTIONS  JSON object of section name to {key: value}; each section is
 *                           replaced by exactly these keys, an empty object empties it
 *   MATOMO_CONFIG_GENERAL   JSON object of General key to value; an empty string removes the key
 *
 * Output: CHANGED when a key moved.
 */

use Piwik\Application\Environment;
use Piwik\Config;
use Piwik\FrontController;

define('PIWIK_INCLUDE_PATH', '/var/www/html');
define('PIWIK_USER_PATH', '/var/www/html');
define('PIWIK_ENABLE_DISPATCH', false);
define('PIWIK_ENABLE_ERROR_HANDLER', false);
define('PIWIK_ENABLE_SESSION_START', false);
require_once PIWIK_INCLUDE_PATH . '/index.php';

function json_object_env(string $name): array
{
    $raw = getenv($name);
    if ($raw === false || $raw === '') {
        fwrite(STDERR, "[FAIL] $name is empty\n");
        exit(1);
    }
    $value = json_decode($raw, true, 16, JSON_THROW_ON_ERROR);
    if (!is_array($value)) {
        fwrite(STDERR, "[FAIL] $name is no JSON object\n");
        exit(1);
    }
    return $value;
}

function ini_value($value)
{
    if (is_array($value)) {
        return array_map('ini_value', $value);
    }
    if (is_bool($value)) {
        return $value ? '1' : '0';
    }
    return (string) $value;
}

$sections = json_object_env('MATOMO_CONFIG_SECTIONS');
$generalKeys = json_object_env('MATOMO_CONFIG_GENERAL');

$environment = new Environment(null);
$environment->init();
FrontController::getInstance()->init();

$config = Config::getInstance();
$changed = false;

foreach ($sections as $section => $settings) {
    if ($section === 'General' || !is_array($settings)) {
        fwrite(STDERR, "[FAIL] MATOMO_CONFIG_SECTIONS.$section is no replaceable section\n");
        exit(1);
    }
    $current = $config->$section;
    $desired = array_map('ini_value', $settings);
    if (array_map('ini_value', is_array($current) ? $current : []) != $desired) {
        $config->$section = $desired;
        $changed = true;
    }
}

$general = $config->General;
foreach ($generalKeys as $key => $value) {
    $desired = ini_value($value);
    if ($desired === '') {
        if (array_key_exists($key, $general)) {
            unset($general[$key]);
            $changed = true;
        }
    } elseif (!array_key_exists($key, $general) || ini_value($general[$key]) != $desired) {
        $general[$key] = $desired;
        $changed = true;
    }
}

if ($changed) {
    $config->General = $general;
    $config->forceSave();
    echo "CHANGED\n";
}
