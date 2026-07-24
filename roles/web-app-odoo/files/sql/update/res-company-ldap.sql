UPDATE res_company_ldap SET
  sequence = %(sequence)s,
  company = %(company_id)s,
  ldap_server_port = %(ldap_server_port)s,
  ldap_binddn = %(ldap_binddn)s,
  ldap_password = %(ldap_password)s,
  ldap_base = %(ldap_base)s,
  ldap_filter = %(ldap_filter)s,
  create_user = %(create_user)s,
  ldap_tls = %(ldap_tls)s,
  write_date = NOW()
WHERE ldap_server = %(ldap_server)s;
