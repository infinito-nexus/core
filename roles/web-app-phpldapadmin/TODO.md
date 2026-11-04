# Todos

- No Playwright spec edits an entry through phpLDAPadmin, so the write access the `svc-db-openldap` ACL grants the `web-app-phpldapadmin` administrator group is asserted only through the equivalent `web-app-lam` clause (`roles/web-app-lam/files/playwright/test-directory-login.js`). Cause: the role is end of life and outside every CI round, and its v2 entry editor is a JavaScript form no spec drives yet. Options: add an edit spec when the role returns to a CI lifecycle.
