-- First install: register Keycloak as an OAuth provider.
-- Args: the fields of the oauth_provider form of meta/forms.yml (enabled, client_id, body, css_class, auth_endpoint, scope, validation_endpoint, data_endpoint).
INSERT INTO auth_oauth_provider (
	name,
	enabled,
	auth_endpoint,
	validation_endpoint,
	data_endpoint,
	client_id,
	scope,
	css_class,
	body,
	sequence,
	create_date,
	write_date
) VALUES (
	'Keycloak',
	%(enabled)s,
	%(auth_endpoint)s,
	%(validation_endpoint)s,
	%(data_endpoint)s,
	%(client_id)s,
	%(scope)s,
	%(css_class)s,
	jsonb_build_object('en_US', %(body)s::text),
	10,
	NOW(),
	NOW()
);
