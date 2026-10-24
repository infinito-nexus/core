# TODO

- Existing installs that were seeded before the demo seeder was removed still hold the demo users, among them superusers with the upstream factory password; their removal is an open operator decision.
- Installs seeded before the demo seeder was removed keep `ldap_enabled = 1` against `ldap://ldap.forumsys.com` while the `ldap` service is off, because `tasks/02_ldap.yml` only runs with `ldap` on; the upstream login controller then attempts an LDAP login with the submitted user name and password before local authentication (one form sign-in took 1.9 s on the local stack). Fresh installs do not get these settings. Options: write `ldap_enabled = 0` through the Setting model when the service is off.
