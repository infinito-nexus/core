-- listmonk grants every permission to role id 1 by that id alone
-- (internal/auth/models.go SuperAdminRoleID), whatever the role is named.
SELECT COALESCE(
         json_agg(json_build_object(
           'login', username,
           'email', email,
           'admin', type = 'user' AND user_role_id = 1
         ) ORDER BY id),
         '[]'::json
       )
FROM users;
