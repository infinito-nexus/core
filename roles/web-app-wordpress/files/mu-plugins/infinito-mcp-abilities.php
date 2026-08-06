<?php
/**
 * Plugin Name: Infinito MCP Abilities
 * Description: Registers the reviewed read-only Abilities the MCP adapter may expose.
 *
 * The MCP Adapter publishes an ability only when it carries
 * meta.mcp.public = true, so this file is the entire tool surface: whatever is
 * not registered here cannot be reached over MCP, no matter what else the site
 * has installed.
 *
 * Every ability is a read of already-published content and carries its own
 * permission callback. The callback is not decoration: the adapter authorises
 * the transport, the callback authorises the operation, and dropping it would
 * let any authenticated caller reach the ability.
 */

defined( 'ABSPATH' ) || exit;

const INFINITO_MCP_MAX_RESULTS = 20;

/**
 * Whether the caller may read published content through MCP.
 */
function infinito_mcp_may_read() {
	return is_user_logged_in() && current_user_can( 'read' );
}

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
	'abilities_api_init',
	function () {
		if ( ! function_exists( 'wp_register_ability' ) ) {
			return;
		}

		wp_register_ability(
			'infinito/search-posts',
			array(
				'label'               => __( 'Search published posts', 'infinito' ),
				'description'         => __( 'Full-text search across published posts.', 'infinito' ),
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
					return array_map( 'infinito_mcp_public_post', $posts );
				},
				'meta'                => array( 'mcp' => array( 'public' => true ) ),
			)
		);

		wp_register_ability(
			'infinito/get-post',
			array(
				'label'               => __( 'Get one published post', 'infinito' ),
				'description'         => __( 'Fetch a single published post by id.', 'infinito' ),
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
					if ( ! $post || 'publish' !== $post->post_status ) {
						return null;
					}
					return infinito_mcp_public_post( $post );
				},
				'meta'                => array( 'mcp' => array( 'public' => true ) ),
			)
		);

		wp_register_ability(
			'infinito/list-categories',
			array(
				'label'               => __( 'List categories', 'infinito' ),
				'description'         => __( 'List the site categories with post counts.', 'infinito' ),
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
						return array();
					}
					return array_map(
						function ( $term ) {
							return array(
								'id'    => $term->term_id,
								'name'  => $term->name,
								'slug'  => $term->slug,
								'count' => $term->count,
							);
						},
						$terms
					);
				},
				'meta'                => array( 'mcp' => array( 'public' => true ) ),
			)
		);
	}
);
