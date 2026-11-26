<?php
/**
 * Turns the AI Engine MCP module off and deletes the MCP bearer token in the
 * stored mwai_options of every site but the main site of the network. The
 * infinito-ai-engine-network mu-plugin hides both keys on read, so its filter
 * is removed before the stored row is read.
 *
 * Output:
 *   "CHANGED <blog id>" once per site whose stored options this run changed.
 */

remove_all_filters('option_mwai_options');

foreach (get_sites(array('fields' => 'ids', 'number' => 0)) as $blog_id) {
    if (is_main_site($blog_id)) {
        continue;
    }
    switch_to_blog($blog_id);
    $options = get_option('mwai_options');
    if (is_array($options) && (!empty($options['module_mcp']) || array_key_exists('mcp_bearer_token', $options))) {
        $options['module_mcp'] = false;
        unset($options['mcp_bearer_token']);
        update_option('mwai_options', $options, false);
        WP_CLI::log('CHANGED ' . $blog_id);
    }
    restore_current_blog();
}
