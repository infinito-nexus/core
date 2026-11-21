<?php
// nocheck: mirrored-unit-test - registers filters at load that answer the option and settings hooks AI Engine fires
/**
 * Plugin Name: Infinito.Nexus AI Engine Network Guard
 * Description: Keeps the AI Engine settings to the network administrators and
 *              its MCP server to the main site of a Multisite network.
 */

if (!defined('ABSPATH')) {
    exit;
}

if (!is_multisite()) {
    return;
}

add_filter('mwai_allow_setup', 'infinito_ai_engine_network_allow_setup', PHP_INT_MAX);
add_filter('option_mwai_options', 'infinito_ai_engine_network_options', PHP_INT_MAX);
add_filter('default_option_mwai_options', 'infinito_ai_engine_network_options', PHP_INT_MAX);

/**
 * @param bool $allow Whether AI Engine lets the current user open and save its settings.
 * @return bool $allow for a network administrator, false for everyone else.
 */
function infinito_ai_engine_network_allow_setup($allow) {
    return $allow && is_super_admin();
}

/**
 * AI Engine signs an MCP bearer-token request in as the first administrator of
 * the site, and the network administrators administer every site, so a token a
 * site administrator sets would act with network rights. AI Engine also turns
 * its MCP module on by default on a site without stored options, which is why
 * the default value is filtered as well.
 *
 * @param mixed $options The mwai_options of the current site, stored or default.
 * @return mixed $options, with the MCP module off and no bearer token on every site but the main site.
 */
function infinito_ai_engine_network_options($options) {
    if (is_main_site() || !is_array($options)) {
        return $options;
    }
    $options['module_mcp'] = false;
    unset($options['mcp_bearer_token']);
    return $options;
}
