# Todo

- `acl.admin` is a deploy-time snapshot of the `administrator` role, so a group change in Keycloak takes effect only on the next deploy, because ejabberd ACLs cannot query LDAP groups; options: redeploy the role after a group change.
- The vCard map is checked through `mod_http_api` `get_vcard`; what an XMPP client renders over 5222 is not covered by Playwright.
