-- Re-deploy: refresh the Keycloak OAuth provider row in place.
-- Args: the fields of the oauth_provider form of meta/forms.yml (enabled, client_id, body, css_class, auth_endpoint, scope, validation_endpoint, data_endpoint).
UPDATE auth_oauth_provider SET
	enabled = %(enabled)s,
	auth_endpoint = %(auth_endpoint)s,
	validation_endpoint = %(validation_endpoint)s,
	data_endpoint = %(data_endpoint)s,
	client_id = %(client_id)s,
	scope = %(scope)s,
	css_class = %(css_class)s,
	body = jsonb_build_object('en_US', %(body)s::text),
	write_date = NOW()
WHERE name = 'Keycloak';
