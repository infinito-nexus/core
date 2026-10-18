UPDATE users SET is_admin = 1
WHERE username = %(admin_username)s AND is_admin = 0;
SELECT ROW_COUNT();
