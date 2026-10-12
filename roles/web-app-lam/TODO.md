# Todos

- `templates/env.j2` passes `LDAP_ADMIN_PASSWORD`, which no script of the LAM 9.7 image reads (`start.sh` reads `LDAP_USER`, `LAM_PASSWORD`, `LDAP_SERVER`, `LDAP_BASE_DN` and friends; the key only feeds the OpenLDAP service of the upstream compose file). It places the LDAP root password into the LAM container environment for nothing, since LAM binds with the password the user types. Option: drop the key.
