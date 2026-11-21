<?php
/**
 * Environment:
 *   AI_ENGINE_ENV_ID: id of the environment the deploy manages.
 *
 * Stdout: a JSON object of the managed settings the site holds, each left out while unset:
 *   endpoint          endpoint of that environment
 *   ai_default_env    default environment
 *   ai_default_model  default model
 */

// nocheck: mirrored-unit-test - runs through `wp eval-file` and reads mwai_options off
// the booted site; the WordPress runtime it needs is only present inside the container

$wanted = getenv('AI_ENGINE_ENV_ID');
$options = get_option('mwai_options', array());
$options = is_array($options) ? $options : array();
$envs = (isset($options['ai_envs']) && is_array($options['ai_envs'])) ? $options['ai_envs'] : array();

$held = array();
foreach ($envs as $env) {
    if (is_array($env) && ($env['id'] ?? '') === $wanted && isset($env['endpoint'])) {
        $held['endpoint'] = $env['endpoint'];
    }
}
foreach (array('ai_default_env', 'ai_default_model') as $key) {
    if (isset($options[$key])) {
        $held[$key] = $options[$key];
    }
}

echo json_encode((object) $held);
