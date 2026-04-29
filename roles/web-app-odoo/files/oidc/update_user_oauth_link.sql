-- Bind an existing Odoo res_users row to its Keycloak identity so SSO
-- recognises the user on next login. Caller passes provider_id +
-- oauth_uid + login as named_args.
UPDATE res_users SET
	oauth_provider_id = %(provider_id)s,
	oauth_uid = %(oauth_uid)s,
	write_date = NOW()
WHERE login = %(login)s;
