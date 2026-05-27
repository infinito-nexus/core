-- Create the active "_oauth_template" user. Its group memberships are
-- granted by the follow-up grant_*.sql scripts. New OAuth signups are
-- copied from this user (`base.template_portal_user_id` /
-- `auth_signup.template_user_id`).
INSERT INTO res_users (
	partner_id,
	company_id,
	login,
	password,
	active,
	create_uid,
	write_uid,
	create_date,
	write_date,
	notification_type
) VALUES (
	%(partner_id)s,
	1,
	'_oauth_template',
	'',
	True,
	1,
	1,
	NOW(),
	NOW(),
	'email'
)
RETURNING id;
