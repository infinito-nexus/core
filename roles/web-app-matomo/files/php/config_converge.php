<?php

/**
 * Converge keys of Matomo's config.ini.php.
 *
 * Env:
 *   MATOMO_CONFIG_SECTIONS  JSON object of section name to {key: value}; each section is
 *                           replaced by exactly these keys, an empty object empties it
 *   MATOMO_CONFIG_GENERAL   JSON object of General key to value; an empty string removes the key
 *   MATOMO_CONFIG_MODE      "read" compares only and writes nothing
 *   MATOMO_CONFIG_FORM_FIELDS  read mode only: JSON object of section name to the keys
 *                           meta/forms.yml declares; only their stored values are printed
 *
 * Output: CHANGED when a key moved; in read mode
 *   {"settings": {<section>: {<key>: <stored value>}}, "hidden": <count of other differing keys>}.
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
$readOnly = getenv('MATOMO_CONFIG_MODE') === 'read';
$formFields = $readOnly ? json_object_env('MATOMO_CONFIG_FORM_FIELDS') : [];

$environment = new Environment(null);
$environment->init();
FrontController::getInstance()->init();

$config = Config::getInstance();
$changed = false;
$drift = [];
$hidden = 0;

foreach ($sections as $section => $settings) {
    if ($section === 'General' || !is_array($settings)) {
        fwrite(STDERR, "[FAIL] MATOMO_CONFIG_SECTIONS.$section is no replaceable section\n");
        exit(1);
    }
    $current = is_array($config->$section) ? $config->$section : [];
    $stored = array_map('ini_value', $current);
    $desired = array_map('ini_value', $settings);
    if ($readOnly) {
        foreach (array_keys($stored + $desired) as $key) {
            if (array_key_exists($key, $stored) && array_key_exists($key, $desired) && $stored[$key] == $desired[$key]) {
                continue;
            }
            if (array_key_exists($key, $desired) && in_array($key, $formFields[$section] ?? [], true)) {
                $drift[$section][$key] = $current[$key] ?? null;
            } else {
                $hidden++;
            }
        }
        continue;
    }
    if ($stored != $desired) {
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

if ($readOnly) {
    $hidden += $changed ? 1 : 0;
    echo json_encode(['settings' => (object) $drift, 'hidden' => $hidden], JSON_THROW_ON_ERROR) . "\n";
    exit(0);
}

if ($changed) {
    $config->General = $general;
    $config->forceSave();
    echo "CHANGED\n";
}
