UPDATE res_users
SET password = %(password)s,
    write_date = NOW()
WHERE login = %(login)s;
