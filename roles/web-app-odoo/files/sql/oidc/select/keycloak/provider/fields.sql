-- Returns one row: the fields of the oauth_provider form of meta/forms.yml mapped to the values the Keycloak OAuth provider holds, as JSON text; an empty object before the provider exists.
SELECT COALESCE(
	(
		SELECT json_build_object(
			'enabled', enabled,
			'client_id', client_id,
			'body', body ->> 'en_US',
			'css_class', css_class,
			'auth_endpoint', auth_endpoint,
			'scope', scope,
			'validation_endpoint', validation_endpoint,
			'data_endpoint', data_endpoint
		)
		FROM auth_oauth_provider
		WHERE name = 'Keycloak'
		LIMIT 1
	),
	'{}'::json
)::text;
