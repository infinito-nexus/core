-- Re-activate the "_oauth_template" user if a prior run left it
-- inactive. No-op when the user is already active.
UPDATE res_users SET
	active = True,
	write_date = NOW()
WHERE login = '_oauth_template'
  AND active = False;
