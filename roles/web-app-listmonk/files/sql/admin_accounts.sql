SELECT COALESCE(
         json_agg(json_build_object(
           'login', username,
           'email', email,
           'admin', type = 'user' AND user_role_id = 1
         ) ORDER BY id),
         '[]'::json
       )
FROM users;
