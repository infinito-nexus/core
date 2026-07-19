-- Grant "Internal User" group to OAuth-linked users created via
-- signup. Auto-created OAuth users get portal access by default; this
-- promotes them to internal so they can reach the main Odoo
-- interface. Excludes the protected admin/system users (id <= 2) and
-- is idempotent via the NOT EXISTS guard.
INSERT INTO res_groups_users_rel (gid, uid)
SELECT imd.res_id, u.id
FROM ir_model_data imd, res_users u
WHERE imd.module = 'base'
  AND imd.name = 'group_user'
  AND imd.model = 'res.groups'
  AND u.oauth_provider_id IS NOT NULL
  AND u.active = True
  AND u.id > 2
  AND NOT EXISTS (
	SELECT 1 FROM res_groups_users_rel r
	WHERE r.gid = imd.res_id
	  AND r.uid = u.id
  );
