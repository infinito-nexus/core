# web-app-opencloud TODO 📝

- [ ] Promote individual users to OpenCloud admin via OCC after first login. The default driver assigns the standard `user` role to every auto-provisioned account; admin promotion is currently manual.
- [ ] Surface an OpenTalk launcher in the OpenCloud sidebar. `WEB_OPTION_OPENTALK_URL` is set, but a clickable launcher needs an upstream OpenCloud Web app or extension.
- [ ] Verify back-channel logout from Keycloak terminates the OpenCloud session in a real browser.
- [ ] Add an LDAP-bind login scenario to [files/playwright/playwright.spec.js](./files/playwright/playwright.spec.js) so variant 1 (`oidc.enabled: false`, `ldap.enabled: true` per [meta/variants.yml](./meta/variants.yml)) is actually exercised; gate via `skipUnlessServiceEnabled('ldap')`. Tracked in [docs/requirements/018-playwright-ldap-coverage.md](../../docs/requirements/018-playwright-ldap-coverage.md).
