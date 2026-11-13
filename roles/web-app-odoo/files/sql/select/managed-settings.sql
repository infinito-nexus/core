-- Returns one row: the forms general, base_url and base_url_freeze of meta/forms.yml, each mapped to its fields and the values Odoo holds, as JSON text; the customer account comes from the first website, whose value the settings page shows.
SELECT json_build_object(
	'general', json_build_object(
		'auth_signup_uninvited', (SELECT auth_signup_uninvited FROM website ORDER BY id LIMIT 1),
		'auth_signup_reset_password', (SELECT value FROM ir_config_parameter WHERE key = 'auth_signup.reset_password')
	),
	'base_url', json_build_object(
		'web_base_url', (SELECT value FROM ir_config_parameter WHERE key = 'web.base.url')
	),
	'base_url_freeze', json_build_object(
		'web_base_url_freeze', (SELECT value FROM ir_config_parameter WHERE key = 'web.base.url.freeze')
	)
)::text;
