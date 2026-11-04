SELECT s.id,
       (SELECT COUNT(*) FROM `user` u WHERE u.login_source = s.id)
       + (SELECT COUNT(*) FROM external_login_user e WHERE e.login_source_id = s.id)
FROM login_source s
ORDER BY s.id;
