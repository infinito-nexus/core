UPDATE res_partner
SET email = %(email)s,
    write_date = NOW()
WHERE id = (SELECT partner_id FROM res_users WHERE login = %(login)s);
