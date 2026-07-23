UPDATE res_users
SET login = %(login)s,
    password = %(password)s,
    write_date = NOW()
WHERE id = 2;
