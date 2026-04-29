-- Add the "_oauth_template" user to the base "Internal User" group so
-- every signup that copies from it inherits internal-user access.
-- Idempotent via the NOT EXISTS guard.
INSERT INTO res_groups_users_rel (gid, uid)
SELECT imd.res_id, u.id
FROM ir_model_data imd, res_users u
WHERE imd.module = 'base'
  AND imd.name = 'group_user'
  AND imd.model = 'res.groups'
  AND u.login = '_oauth_template'
  AND NOT EXISTS (
	SELECT 1 FROM res_groups_users_rel r
	WHERE r.gid = imd.res_id
	  AND r.uid = u.id
  );
