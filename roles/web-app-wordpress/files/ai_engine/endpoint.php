<?php
/**
 * Environment:
 *   AI_ENGINE_ENV_ID: id of the environment the deploy manages.
 */

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
