UPDATE res_partner
SET email = %(email)s,
    name = %(name)s,
    write_date = NOW()
WHERE id = (SELECT partner_id FROM res_users WHERE id = 2);
