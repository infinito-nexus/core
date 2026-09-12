<?php
/**
 * Environment:
 *   AI_ENGINE_ENV_ID: id of the environment the deploy manages.
 */

// nocheck: mirrored-unit-test - runs through `wp eval-file` and reads mwai_options off
// the booted site; the WordPress runtime it needs is only present inside the container

$wanted = getenv('AI_ENGINE_ENV_ID');
$options = get_option('mwai_options', array());
$envs = (is_array($options) && isset($options['ai_envs']) && is_array($options['ai_envs']))
    ? $options['ai_envs']
    : array();

foreach ($envs as $env) {
    if ((isset($env['id']) ? $env['id'] : '') === $wanted) {
        echo isset($env['endpoint']) ? $env['endpoint'] : '';
    }
}
