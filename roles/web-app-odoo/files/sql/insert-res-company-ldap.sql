INSERT INTO res_company_ldap
(sequence, company, ldap_server, ldap_server_port, ldap_binddn, ldap_password,
 ldap_base, ldap_filter, create_user, ldap_tls, create_date, write_date)
VALUES (
  %(sequence)s,
  %(company_id)s,
  %(ldap_server)s,
  %(ldap_server_port)s,
  %(ldap_binddn)s,
  %(ldap_password)s,
  %(ldap_base)s,
  %(ldap_filter)s,
  %(create_user)s,
  %(ldap_tls)s,
  NOW(),
  NOW()
);
