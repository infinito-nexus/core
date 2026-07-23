-- Attach OAuth-signup users to the default company (id=1) so they can
-- access company-scoped data after first SSO login. Excludes admin
-- (id <= 2) and only touches users whose primary company is already
-- the default one. Idempotent via the NOT EXISTS guard.
INSERT INTO res_company_users_rel (cid, user_id)
SELECT 1, u.id
FROM res_users u
WHERE u.oauth_provider_id IS NOT NULL
  AND u.active = True
  AND u.id > 2
  AND u.company_id = 1
  AND NOT EXISTS (
	SELECT 1 FROM res_company_users_rel r
	WHERE r.cid = 1
	  AND r.user_id = u.id
  );
