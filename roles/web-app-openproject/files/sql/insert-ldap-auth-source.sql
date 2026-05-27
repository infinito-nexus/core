INSERT INTO ldap_auth_sources
(name, host, port, account, account_password, base_dn, attr_login,
 attr_firstname, attr_lastname, attr_mail, onthefly_register, attr_admin,
 created_at, updated_at, tls_mode, filter_string, verify_peer, tls_certificate_string)
VALUES (
  %(name)s,
  %(host)s,
  %(port)s,
  %(account)s,
  %(account_password)s,
  %(base_dn)s,
  %(attr_login)s,
  %(attr_firstname)s,
  %(attr_lastname)s,
  %(attr_mail)s,
  %(onthefly_register)s,
  %(attr_admin)s,
  NOW(),
  NOW(),
  %(tls_mode)s,
  %(filter_string)s,
  %(verify_peer)s,
  %(tls_certificate_string)s
);
