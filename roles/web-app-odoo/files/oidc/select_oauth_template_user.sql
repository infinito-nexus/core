-- Look up the row id of the internal "_oauth_template" user that
-- newly-created OAuth users inherit groups from. Used to skip the
-- create-template steps on re-deploy.
SELECT id
FROM res_users
WHERE login = '_oauth_template'
LIMIT 1;
