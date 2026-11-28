-- Param %(ldap_server)s: directory host whose auth_ldap sign-in row is removed,
-- so /web/login and /web/session/authenticate stop binding against it.
DELETE FROM res_company_ldap WHERE ldap_server = %(ldap_server)s;
