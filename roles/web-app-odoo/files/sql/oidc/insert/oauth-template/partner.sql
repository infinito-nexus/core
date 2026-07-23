-- Create the partner row that backs the "_oauth_template" template
-- user. The new partner stays inactive (active = False) and exists
-- only to satisfy the FK from res_users.partner_id.
INSERT INTO res_partner (
	name,
	email,
	active,
	autopost_bills,
	create_uid,
	write_uid,
	create_date,
	write_date
) VALUES (
	'OAuth Template User',
	'oauth-template@localhost',
	False,
	'ask',
	1,
	1,
	NOW(),
	NOW()
)
RETURNING id;
