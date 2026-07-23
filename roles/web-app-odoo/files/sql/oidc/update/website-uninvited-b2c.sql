-- Allow uninvited OAuth signup on every website that does not already
-- permit it. Bumps `write_date` so Odoo invalidates its caches.
UPDATE website SET
	auth_signup_uninvited = 'b2c',
	write_date = NOW()
WHERE auth_signup_uninvited != 'b2c'
   OR auth_signup_uninvited IS NULL;
