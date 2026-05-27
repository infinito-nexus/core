-- Specialised upsert for `ir_config_parameter` rows whose value is the
-- internal template user's id. The value is computed by a subquery so
-- the template user's id never has to round-trip through Ansible.
-- Caller passes the parameter name as %(key)s
-- (base.template_portal_user_id or auth_signup.template_user_id).
INSERT INTO ir_config_parameter (key, value, create_date, write_date)
VALUES (
	%(key)s,
	(SELECT id::text FROM res_users WHERE login = '_oauth_template'),
	NOW(),
	NOW()
)
ON CONFLICT (key) DO UPDATE SET
	value = (SELECT id::text FROM res_users WHERE login = '_oauth_template'),
	write_date = NOW();
