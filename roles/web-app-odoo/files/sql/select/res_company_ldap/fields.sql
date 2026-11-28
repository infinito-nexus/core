-- Param %(ldap_server)s: directory host whose res_company_ldap row the ldap_directory form of meta/forms.yml manages.
-- Returns one row: the fields of that form mapped to the values the row holds, as JSON text; an empty object before the row exists.
SELECT COALESCE(
	(
		SELECT json_build_object(
			'ldap_server_port', ldap_server_port,
			'ldap_tls', ldap_tls,
			'ldap_base', ldap_base,
			'ldap_filter', ldap_filter,
			'create_user', create_user
		)
		FROM res_company_ldap
		WHERE ldap_server = %(ldap_server)s
		ORDER BY sequence, id
		LIMIT 1
	),
	'{}'::json
)::text;
