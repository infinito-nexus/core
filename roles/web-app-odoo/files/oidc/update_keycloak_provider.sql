-- Re-deploy: refresh the Keycloak OAuth provider row in place.
UPDATE auth_oauth_provider SET
	enabled = True,
	auth_endpoint = %(auth_endpoint)s,
	validation_endpoint = %(userinfo_endpoint)s,
	data_endpoint = %(userinfo_endpoint)s,
	client_id = %(client_id)s,
	scope = 'openid email profile',
	css_class = 'fa fa-fw fa-key',
	body = '{"en_US": "Login with SSO"}',
	write_date = NOW()
WHERE name = 'Keycloak';
