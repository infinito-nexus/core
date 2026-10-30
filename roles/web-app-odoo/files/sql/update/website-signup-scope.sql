-- Param %(scope)s: 'b2c' lets uninvited visitors sign up on every website,
-- 'b2b' hides the signup link. Bumps `write_date` so Odoo invalidates its caches.
UPDATE website SET
	auth_signup_uninvited = %(scope)s,
	write_date = NOW()
WHERE auth_signup_uninvited IS DISTINCT FROM %(scope)s;
