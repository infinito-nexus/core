<?php
/**
 * Environment:
 *   AI_ENGINE_PAYLOAD: base64 of {"environment": {...}, "default_model": "..."}.
 */

$payload = json_decode(base64_decode(getenv('AI_ENGINE_PAYLOAD')), true);
if (!is_array($payload) || empty($payload['environment']['id'])) {
    WP_CLI::error('AI_ENGINE_PAYLOAD did not decode to an environment');
}

$options = get_option('mwai_options', array());
if (!is_array($options)) {
    $options = array();
}

$existing = (isset($options['ai_envs']) && is_array($options['ai_envs'])) ? $options['ai_envs'] : array();
$kept = array();
foreach ($existing as $env) {
    if ((isset($env['id']) ? $env['id'] : '') !== $payload['environment']['id']) {
        $kept[] = $env;
    }
}
$kept[] = $payload['environment'];

$options['ai_envs'] = $kept;
$options['ai_default_env'] = $payload['environment']['id'];
$options['ai_default_model'] = $payload['default_model'];

update_option('mwai_options', $options);
