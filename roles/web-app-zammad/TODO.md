# Todo

- The LdapSource task in `tasks/01_manager_ops.yml` now masks its output with `MASK_CREDENTIALS_IN_LOGS`, because its environment carries `LDAP_BIND_PW`; Playwright cannot observe a deploy log, so no spec covers it. Options: a lint that requires `no_log` on every task whose `environment:` reads `LDAP.BIND_CREDENTIAL`.
