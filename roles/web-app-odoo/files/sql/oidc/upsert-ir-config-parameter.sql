-- Generic upsert for `ir_config_parameter`. Caller passes %(key)s and
-- %(value)s as named_args. Used for every flag/scalar Odoo system
-- parameter (oauth_providers, invitation_scope, authorization_header,
-- web.base.url, web.base.url.freeze, ...).
INSERT INTO ir_config_parameter (key, value, create_date, write_date)
VALUES (%(key)s, %(value)s, NOW(), NOW())
ON CONFLICT (key) DO UPDATE SET
	value = %(value)s,
	write_date = NOW();
