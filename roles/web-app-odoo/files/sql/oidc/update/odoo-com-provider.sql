-- Param %(enabled)s: true shows Odoo's shipped "Odoo.com Accounts" provider
-- (auth_oauth.provider_openerp, noupdate data) on the login page, false hides it.
UPDATE auth_oauth_provider SET
	enabled = %(enabled)s,
	write_date = NOW()
WHERE id IN (
	SELECT res_id
	FROM ir_model_data
	WHERE module = 'auth_oauth'
	  AND name = 'provider_openerp'
	  AND model = 'auth.oauth.provider'
)
  AND enabled IS DISTINCT FROM %(enabled)s;
