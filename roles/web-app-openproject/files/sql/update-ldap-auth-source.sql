UPDATE ldap_auth_sources SET
  host = %(host)s,
  port = %(port)s,
  account = %(account)s,
  account_password = %(account_password)s,
  base_dn = %(base_dn)s,
  attr_login = %(attr_login)s,
  attr_firstname = %(attr_firstname)s,
  attr_lastname = %(attr_lastname)s,
  attr_mail = %(attr_mail)s,
  onthefly_register = %(onthefly_register)s,
  attr_admin = %(attr_admin)s,
  updated_at = NOW(),
  tls_mode = %(tls_mode)s,
  filter_string = %(filter_string)s,
  verify_peer = %(verify_peer)s,
  tls_certificate_string = %(tls_certificate_string)s
WHERE name = %(name)s;
