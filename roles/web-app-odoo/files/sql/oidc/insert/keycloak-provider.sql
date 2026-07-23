-- First install: register Keycloak as an OAuth provider.
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
	True,
	%(auth_endpoint)s,
	%(userinfo_endpoint)s,
	%(userinfo_endpoint)s,
	%(client_id)s,
	'openid email profile',
	'fa fa-fw fa-key',
	'{"en_US": "Login with SSO"}',
	10,
	NOW(),
	NOW()
);
