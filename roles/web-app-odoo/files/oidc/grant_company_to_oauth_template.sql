-- Attach the "_oauth_template" user to the default company (id=1) so
-- copies of this user join that company by default. Idempotent via
-- the NOT EXISTS guard.
INSERT INTO res_company_users_rel (cid, user_id)
SELECT 1, u.id
FROM res_users u
WHERE u.login = '_oauth_template'
  AND NOT EXISTS (
	SELECT 1 FROM res_company_users_rel r
	WHERE r.cid = 1
	  AND r.user_id = u.id
  );
