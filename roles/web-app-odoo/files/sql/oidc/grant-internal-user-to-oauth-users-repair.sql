-- Repair fallback: grant "Internal User" to OAuth-linked users that
-- were created before `base.template_portal_user_id` was set
-- correctly. Excludes the "_oauth_template" sentinel user. New OAuth
-- signups inherit the group from the template, so this only touches
-- legacy users.
INSERT INTO res_groups_users_rel (gid, uid)
SELECT imd.res_id, u.id
FROM ir_model_data imd, res_users u
WHERE imd.module = 'base'
  AND imd.name = 'group_user'
  AND imd.model = 'res.groups'
  AND u.oauth_provider_id IS NOT NULL
  AND u.login != '_oauth_template'
  AND u.active = True
  AND NOT EXISTS (
	SELECT 1 FROM res_groups_users_rel r
	WHERE r.gid = imd.res_id
	  AND r.uid = u.id
  );
