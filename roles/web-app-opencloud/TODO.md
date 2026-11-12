# web-app-opencloud TODO 📝

- [ ] Map role groups without SSO: the role mapping reads `realm_access.roles` from Keycloak, so the SSO-less variants (built-in lico IDP) keep the `default` driver and give every account `user`. Options: a deploy-time reconcile through the Graph `appRoleAssignments` API, which needs a bootstrap admin (`OC_ADMIN_USER_ID`) first.
- [ ] The `oidc` role assignment driver refuses a login whose `realm_access.roles` holds no mapped value (`services/proxy/pkg/userroles/oidcroles.go` at `v7.2.4`). Removing `default-roles-<realm>` from a Keycloak user, or the `roles` client scope from the OpenCloud client, therefore locks that user out of OpenCloud. Options: keep the default realm role on every account.
- [ ] Surface an OpenTalk launcher in the OpenCloud sidebar. `WEB_OPTION_OPENTALK_URL` is set, but a clickable launcher needs an upstream OpenCloud Web app or extension.
- [ ] Verify back-channel logout from Keycloak terminates the OpenCloud session in a real browser.
- [ ] Let the App Store load its catalogue. `/app-store/list` shows "No apps found" because the browser refuses `https://raw.githubusercontent.com/opencloud-eu/awesome-apps/main/webApps/apps.json`: the `connect-src` of [meta/csp.yml](./meta/csp.yml) does not list that host. Options: add the host to `connect-src`, or drop `app-store` from the web apps OpenCloud loads.
