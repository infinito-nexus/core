SELECT id FROM users
WHERE username = %(admin_username)s
LIMIT 1;
