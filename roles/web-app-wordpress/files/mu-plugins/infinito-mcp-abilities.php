<?php
/**
 * Plugin Name: Infinito MCP Abilities
 * Description: Registers the reviewed read-only Abilities the MCP adapter may expose, and keeps the application password usable on the internal MCP hop.
 *
 * The filter at the end of this file sets the default MCP server's tools to
 * exactly these three abilities and empties its resources and prompts, at
 * PHP_INT_MAX so that the usual extension at default priority cannot widen it.
 *
 * Every ability is a read of already-published content and carries its own
 * permission callback. The callback is not decoration: the adapter authorises
 * the transport, the callback authorises the operation, and dropping it would
 * let any authenticated caller reach the ability.
 */

// nocheck: mirrored-unit-test - a mu-plugin the WordPress loader includes; it exits
// unless ABSPATH is defined, and every ability calls get_posts, current_user_can and
// wp_register_ability against the booted site

defined( 'ABSPATH' ) || exit;

const INFINITO_MCP_MAX_RESULTS = 20;

/**
 * Whether the caller may read published content through MCP.
 */
function infinito_mcp_may_read() {
	return is_user_logged_in() && current_user_can( 'read' );
}

/**
 * Refuse an MCP transport request the site cannot attribute to a user.
 *
 * The adapter gates JSON-RPC methods that touch an ability, but answers the
 * `initialize` handshake to anyone, so the server and its protocol version are
 * readable without a credential.
 *
 * Args:
 *   $result:  the short-circuited response, or null while none was produced.
 *   $server:  the REST server handling the request.
 *   $request: the request being dispatched.
 */
function infinito_mcp_guard_transport( $result, $server, $request ) {
	if ( null !== $result || is_user_logged_in() ) {
		return $result;
	}
	if ( 0 !== strpos( ltrim( $request->get_route(), '/' ), 'mcp/' ) ) {
		return $result;
	}
	return new WP_Error(
		'infinito_mcp_unauthorized',
		'Authentication is required to reach the MCP server.',
		array( 'status' => 401 )
	);
}

add_filter( 'rest_pre_dispatch', 'infinito_mcp_guard_transport', 10, 3 );

/**
 * @param bool $available Whether core already considers them available.
 */
function infinito_mcp_app_passwords_available( $available ) {
	return $available || 'https' === wp_parse_url( home_url(), PHP_URL_SCHEME );
}

add_filter( 'wp_is_application_passwords_available', 'infinito_mcp_app_passwords_available' );

/**
 * Reduce a post to the non-sensitive fields an agent needs.
 *
 * @param WP_Post $post Post to summarise.
 */
function infinito_mcp_public_post( $post ) {
	return array(
		'id'        => $post->ID,
		'title'     => get_the_title( $post ),
		'excerpt'   => wp_strip_all_tags( get_the_excerpt( $post ) ),
		'permalink' => get_permalink( $post ),
		'date'      => get_post_time( 'c', true, $post ),
	);
}

add_action(
	'wp_abilities_api_categories_init',
	function () {
		wp_register_ability_category(
			'infinito',
			array(
				'label'       => __( 'Infinito', 'infinito' ),
				'description' => __( 'Reviewed read-only access to published content.', 'infinito' ),
			)
		);
	}
);

add_action(
	'wp_abilities_api_init',
	function () {
		wp_register_ability(
			'infinito/search-posts',
			array(
				'label'               => __( 'Search published posts', 'infinito' ),
				'description'         => __( 'Full-text search across published posts.', 'infinito' ),
				'category'            => 'infinito',
				'input_schema'        => array(
					'type'       => 'object',
					'properties' => array(
						'query' => array( 'type' => 'string' ),
					),
					'required'   => array( 'query' ),
				),
				'permission_callback' => 'infinito_mcp_may_read',
				'execute_callback'    => function ( $input ) {
					$posts = get_posts(
						array(
							's'                => (string) ( $input['query'] ?? '' ),
							'post_status'      => 'publish',
							'post_type'        => 'post',
							'posts_per_page'   => INFINITO_MCP_MAX_RESULTS,
							'suppress_filters' => false,
						)
					);
					return array( 'posts' => array_map( 'infinito_mcp_public_post', $posts ) );
				},
				'meta'                => array( 'mcp' => array( 'public' => true ) ),
			)
		);

		wp_register_ability(
			'infinito/get-post',
			array(
				'label'               => __( 'Get one published post', 'infinito' ),
				'description'         => __( 'Fetch a single published post by id.', 'infinito' ),
				'category'            => 'infinito',
				'input_schema'        => array(
					'type'       => 'object',
					'properties' => array(
						'id' => array( 'type' => 'integer' ),
					),
					'required'   => array( 'id' ),
				),
				'permission_callback' => 'infinito_mcp_may_read',
				'execute_callback'    => function ( $input ) {
					$post = get_post( (int) ( $input['id'] ?? 0 ) );
					if ( ! $post || 'publish' !== $post->post_status || 'post' !== $post->post_type ) {
						return array( 'post' => null );
					}
					return array( 'post' => infinito_mcp_public_post( $post ) );
				},
				'meta'                => array( 'mcp' => array( 'public' => true ) ),
			)
		);

		wp_register_ability(
			'infinito/list-categories',
			array(
				'label'               => __( 'List categories', 'infinito' ),
				'description'         => __( 'List the site categories with post counts.', 'infinito' ),
				'category'            => 'infinito',
				'input_schema'        => array( 'type' => 'object', 'properties' => array() ),
				'permission_callback' => 'infinito_mcp_may_read',
				'execute_callback'    => function () {
					$terms = get_terms(
						array(
							'taxonomy'   => 'category',
							'hide_empty' => false,
							'number'     => INFINITO_MCP_MAX_RESULTS,
						)
					);
					if ( is_wp_error( $terms ) ) {
						return array( 'categories' => array() );
					}
					return array(
						'categories' => array_map(
							function ( $term ) {
								return array(
									'id'    => $term->term_id,
									'name'  => $term->name,
									'slug'  => $term->slug,
									'count' => $term->count,
								);
							},
							$terms
						),
					);
				},
				'meta'                => array( 'mcp' => array( 'public' => true ) ),
			)
		);
	}
);

add_filter(
	'mcp_adapter_default_server_config',
	function ( $config ) {
		$config['tools']     = array( 'infinito/search-posts', 'infinito/get-post', 'infinito/list-categories' );
		$config['resources'] = array();
		$config['prompts']   = array();
		return $config;
	},
	PHP_INT_MAX
);
