# 066 - Logout everywhere per network and device

## User Story

As a user who is signed in through one browser on the clearnet and the onion network, or on several devices, I want two explicit choices at logout, "Log out on this device" and "Log out everywhere", where the first ends every session of this browser the platform can end server to server and the second also ends every session of mine on all other devices, so that no network or device keeps a live session of mine that I did not choose to keep.

## Acceptance Criteria

### Trust boundary

- [ ] No Keycloak client that this requirement adds or changes has `serviceAccountsEnabled: true`, and no service-account user of the realm gains a `realm-management` role through this requirement.
- [ ] `web-svc-logout` owns no Keycloak client, its env file holds no Keycloak client secret, it serves no route it did not serve before this change, and it sends no request to Keycloak.
- [ ] The final state holds no `/everywhere` route, no `LOGOUT_EVERYWHERE_*` key, no `web-svc-logout` client in the realm render and no update routine that maps `realm-management` roles to a service account.
- [ ] The realm keeps the values of `eventsEnabled`, `enabledEventTypes`, `eventsExpiration`, `adminEventsEnabled`, `adminEventsDetailsEnabled` and `eventsListeners` it had before this change.
- [ ] No choice, nor any later replacement, uses a Keycloak service account, a `realm-management` role, the Keycloak admin REST API, stored realm events or a Keycloak extension (SPI provider); "Log out everywhere" uses only the user's own access token and the `manage-account` role of the `account` client.
- [ ] A logout sends no browser request without a user click that it did not send before this change, and the CSP of every vhost is byte-identical to its render before this change.
- [ ] Every back-channel endpoint this requirement wires answers a logout token with a bad signature, a foreign `iss`, a wrong `aud` or a missing `events` claim with a 4xx status and ends no session.
- [ ] The "Log out everywhere" link carries no token, session id, user id or query parameter; it carries only the fragment marker defined below.

### Front-channel sweep per network

- [ ] The shared OIDC client keeps `frontchannelLogout: true`, the conductor as `frontchannel.logout.url` and `frontchannel.logout.session.required: "true"`, as rendered by `roles/web-app-keycloak/templates/import/clients/default.json.j2`.
- [ ] Each conductor still clears the cookies of every domain of its own network, as it does before this change.
- [ ] The shared OIDC client carries no `backchannel.logout.url`.

### Back-channel logout per app

- [ ] Every app whose pinned upstream receives OIDC back-channel logout tokens declares its own client under `services.sso.oidc.clients` in its `meta/services.yml` and renders it in its `templates/keycloak/clients.json.j2`, the way `web-app-stalwart` does, and `roles/web-app-keycloak/filter_plugins/oidc_clients.py` includes it without a change on the Keycloak side.
- [ ] Each such client has `frontchannelLogout: false`, `backchannel.logout.session.required: "true"` and a `backchannel.logout.url` on the app's canonical origin.
- [ ] Each such client's `redirectUris`, `webOrigins` and `post.logout.redirect.uris` cover every network sibling of the app through `lookup('network_urls', ...)`.
- [ ] Each such client carries the client scopes and protocol mappers the app read from the shared client, so the app receives the same claims as before (username attribute, RBAC group claim, app scopes such as the Nextcloud scope of the shared client).
- [ ] An existing app user who signs in through the app's new client lands in the same app account as before the switch, and no second account appears.
- [ ] In one browser signed in to the app on the clearnet and on the onion network, a logout started on either network makes the app's next request on the other network ask for a new login.
- [ ] That back-channel logout also happens when JavaScript is disabled in the browser that logs out.
- [ ] Keycloak reaches every `backchannel.logout.url` from its container on a clearnet, an onion-only and a multi-network deployment; for an onion canonical origin, a pin sends the call over the local network to the proxy that serves the vhost, the way the SSO back-channel pin in `plugins/lookup/container_extra_hosts.py` does for calls from apps to Keycloak.
- [ ] Keycloak verifies the TLS certificate of every `backchannel.logout.url`; under `TLS_MODE` `self_signed` it trusts the deployment CA, and no setting turns certificate verification off.

### Apps that qualify for back-channel logout

- [ ] `web-app-matrix`: both flavors log Synapse in through its own client and set `backchannel_logout_enabled: true`. The compose flavor (`templates/flavor/compose/synapse/homeserver.yaml.j2`) already sets the flag but logs in through the shared client; the ansible flavor (`templates/flavor/ansible/vars.yml.j2`) lacks the flag. The `backchannel.logout.url` is `/_synapse/client/oidc/backchannel_logout` on the Synapse origin.
- [ ] `web-app-nextcloud`: when `lookup('sso_oidc_plugin')` (`plugins/lookup/sso_oidc_plugin.py`) resolves to `user_oidc`, Nextcloud logs in through its own client with the `backchannel.logout.url` `/index.php/apps/user_oidc/backchannel-logout/<provider identifier>`; when it resolves to `oidc_login` (the default with LDAP) or `sociallogin` (the default without LDAP), Nextcloud stays on the shared client and its README row names its session lifetime.
- [ ] `web-app-stalwart`: its `webui` and `webmail` clients already render `frontchannelLogout: false` without a `backchannel.logout.url`; the pinned Stalwart WebAdmin and Roundcube are checked for a logout-token receiver, each one that has one gets its `backchannel.logout.url`, and each one that has none gets a README row.
- [ ] `web-app-opencloud`, `web-app-espocrm`, `web-app-xwiki`, `web-app-moodle` and `web-app-openwebui` are checked against the upstream documentation of their pinned versions; each one that receives logout tokens gets its own client under the criteria above, and each one that does not gets a README row.
- [ ] Every other role with `sso.flavor: oidc` stays on the shared client and gets a README row naming whether its pinned upstream receives logout tokens and how long its session lives.

### oauth2-proxy-gated apps

- [ ] `roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2` renders `cookie_refresh` from one configuration key of `web-app-keycloak` that the role config sets explicitly, and the render fails when the key is absent.
- [ ] The shipped `cookie_refresh` value is the one the operator picks; `1m` is the proposal.
- [ ] The value is shorter than the realm's `ssoSessionIdleTimeout` and than oauth2-proxy's `cookie_expire`, and a unit test fails on a value that is not.
- [ ] After Keycloak ends a user session, an oauth2-proxy session of that user on any network or device fails its next refresh, and the first request after one `cookie_refresh` interval redirects to the Keycloak login, never to a 5xx page.

### Decided: two logout choices

The operator decided that the user gets two explicit choices at logout, "Log out on this device" and "Log out everywhere". A logout on device A without the second choice ends no Keycloak session of device B.

#### Where the choices are offered

- [ ] Every logout control lands on the Keycloak logout confirmation page `/realms/<realm>/protocol/openid-connect/logout` on the Keycloak origin of its network: `sys-front-inj-logout` points every app's logout control at `OIDC.CLIENT.LOGOUT_URL` without an `id_token_hint` (`roles/sys-front-inj-logout/templates/logout_one_liner.js.j2:1-9`), and the dashboard menu item does the same (`roles/web-app-dashboard/templates/menu/header.yml.j2:41-47`). This page shows both choices.
- [ ] "Log out on this device" is Keycloak's existing confirm submit (`#kc-logout`), relabelled.
- [ ] "Log out everywhere" is a plain link to the dashboard of the same network with the fragment `#logout-everywhere`.
- [ ] Both choices render with JavaScript on and with JavaScript off: a `logout-confirm.ftl` override in the corporate login theme (`roles/web-app-keycloak/templates/theme/login/`, staged by `roles/web-app-keycloak/tasks/utils/theme.yml`) renders them server side; when `services.keycloak.design` disables the corporate theme, the logout panel (`roles/web-app-keycloak/files/javascript/logout-panel.js`) adds the "Log out everywhere" link and the page shows the stock "Log out on this device" submit.
- [ ] The "Account" menu of the dashboard (`roles/web-app-dashboard/templates/menu/header.yml.j2`) shows the same two items: "Log out on this device" with the existing `OIDC.CLIENT.LOGOUT_URL` and "Log out everywhere" with the `#logout-everywhere` marker.
- [ ] When `web-app-dashboard` with OIDC is not part of the deployment, the confirmation page renders no "Log out everywhere".

#### "Log out on this device"

- [ ] It runs the existing logout: the front-channel conductor sweep per network for the shared client, the per-app back-channel logout and the oauth2-proxy `cookie_refresh` of the sections above.
- [ ] It ends this browser's Keycloak session, so the clearnet and onion siblings of one browser are both logged out, and no session of another device or browser context.
- [ ] Its success message (`all_done` in `roles/web-app-keycloak/files/logout_i18n.yml`) names its scope, this device, and no longer reads "everywhere".

#### "Log out everywhere"

- [ ] The token holder is the existing keycloak-js instance of `roles/web-app-dashboard/templates/javascript/oidc.js.j2:155-173`: it runs `check-sso` with the shared client and keeps the user's access token fresh. The action runs while the user's session is still valid; when `check-sso` finds no session, the dashboard starts `keycloak.login()` and runs the action after the return.
- [ ] Its access token carries the `account` audience through the audience resolve mapper of the `roles` scope (`roles/web-app-keycloak/templates/import/realm.json.j2:1154-1194`), `manage-account` through `default-roles-<realm>` (`realm.json.j2:59-74`) and the dashboard origin in `allowed-origins` through the `web-origins` scope (`realm.json.j2:1101-1103`, fed by `KEYCLOAK_WEB_ORIGINS` in `roles/web-app-keycloak/vars/main.yml:119`). Keycloak's Account REST API checks that audience and answers CORS from that `allowed-origins` claim.
- [ ] On the `#logout-everywhere` marker or the menu click, the dashboard sends, with that token only, `GET /realms/<realm>/account/applications`, then `DELETE /realms/<realm>/account/applications/<clientId>/consent` for every entry with `offlineAccess: true`, which revokes that client's offline token, then `DELETE /realms/<realm>/account/sessions`, the call the Account Console's "Sign out all devices" makes, which ends every other online session of the user.
- [ ] It then calls `keycloak.logout()`, which runs "Log out on this device" for this browser, conductor sweep included.
- [ ] The realm keeps `manage-account` of the `account` client in `default-roles-<realm>` and keeps the `account` client, both rendered by `roles/web-app-keycloak/templates/import/realm.json.j2`.
- [ ] After "Log out everywhere" on device A, the next OIDC authentication on device B asks for credentials, no offline token of the user still refreshes, B's sessions of every app with its own back-channel client end at their next request, and B's oauth2-proxy sessions end within one `cookie_refresh` interval.
- [ ] Rejected: the Account Console route `/realms/<realm>/account/account-security/device-activity` as the place of the action, because its "Sign out all devices" ends online sessions only, is hidden while one session exists and skips the logout when its `DELETE` fails (`signOutAll` in Keycloak's `DeviceActivity.tsx` has no error handling), and changing that needs a custom account theme build.

#### Labels

- [ ] The labels "Log out on this device" and "Log out everywhere", the everywhere success message and the partial-logout message live in the `logout` catalogue (`roles/web-app-keycloak/files/logout_i18n.yml`), served through `lookup('i18n_catalogue', 'logout', ...)`, and have a translation in every language block the catalogue serves; the dashboard reads the same keys.

### Failure semantics

- [ ] When a back-channel endpoint is unreachable or answers with a non-2xx status, Keycloak still ends the user session and completes the logout redirect, and Keycloak's log names the client whose back-channel call failed.
- [ ] The app behind such a failed call keeps its session until its own expiry, which its README row names.
- [ ] The per-network sweep keeps its failure reporting: the conductor's `done` report counts failed domains and the Keycloak logout panel shows its `partial` message.
- [ ] A failed oauth2-proxy refresh ends the proxy session and redirects to the Keycloak login.
- [ ] When any Account REST call of "Log out everywhere" fails, times out or answers with a non-2xx status, the dashboard still calls `keycloak.logout()`, this browser is logged out as with "Log out on this device", and after the post-logout redirect the user sees the partial-logout message that other devices may still be signed in.
- [ ] A per-app client reuses `OIDC.CLIENT.SECRET`, as the Stalwart `webmail` client does, and the realm render and the Keycloak update routine succeed on an inventory created before this change without running the credential generator.

### Documentation

- [ ] `roles/web-svc-logout/README.md` holds one table row per role with an `sso` service: its flavor, whether its pinned upstream receives OIDC back-channel logout tokens (yes, no or to verify), its endpoint, the upstream documentation link, and how long its session lives on another network or device when nothing ends it.
- [ ] The same README describes the two choices, "Log out on this device" (per-network front-channel sweep, per-app back-channel logout, oauth2-proxy refresh) and "Log out everywhere" (the Account REST calls with the user's own token, then "Log out on this device"), and lists which sessions each one ends.

### Tests

- [ ] A unit test renders every `templates/keycloak/clients.json.j2` and asserts per back-channel client `frontchannelLogout: false`, `serviceAccountsEnabled: false`, a `backchannel.logout.url` on the app's canonical origin and redirect URIs for every network sibling; a negative control with a `backchannel.logout.url` on the shared client fails it.
- [ ] A unit test renders `roles/web-app-keycloak/templates/import/realm.json.j2` against an inventory fixture that holds only the credentials present before this change, asserts that the render succeeds and asserts that no service-account user holds a `realm-management` role.
- [ ] A unit test renders the oauth2-proxy config, asserts that `cookie_refresh` equals the configured value and asserts that the render fails when the key is absent.
- [ ] A unit test renders both Synapse flavors and asserts the Synapse client id and `backchannel_logout_enabled: true` in each.
- [ ] Network case of the Playwright spec of `web-svc-logout`: in one browser context, biber signs in to a back-channel app and to an oauth2-proxy app on the clearnet origin and on the onion origin of the same node, logs out on the clearnet origin, and the spec asserts that the back-channel app's next onion request asks for a login and that the oauth2-proxy app's onion request does so after one `cookie_refresh` interval.
- [ ] The network case also passes with `javaScriptEnabled: false` for the logout step.
- [ ] A unit test loads `roles/web-app-keycloak/files/logout_i18n.yml` through the `i18n_catalogue` lookup and asserts that both choice labels, the everywhere success message and the partial-logout message have a non-empty translation in every language block.
- [ ] Choice case of the same spec: on the Keycloak logout confirmation page and in the dashboard "Account" menu, both choices are visible with `javaScriptEnabled: true` and on the confirmation page also with `javaScriptEnabled: false`.
- [ ] Device case "on this device": biber signs in on two browser contexts A and B, A signed in on the clearnet and the onion origin; after "Log out on this device" in A, both networks of A ask for a login and B is still signed in to Keycloak and to its back-channel app.
- [ ] Device case "everywhere": after "Log out everywhere" in A, both networks of A ask for a login, B's next OIDC authentication asks for credentials, B's back-channel app session ended and `GET /realms/<realm>/account/applications` with a fresh token of biber lists no entry with `offlineAccess: true`.
- [ ] Failure case: with the Account REST `DELETE` answered by a non-2xx status through Playwright request routing, A is still logged out on both networks and shows the partial-logout message.
- [ ] Forged-token case of the same spec: it POSTs a logout token signed with a foreign key to every back-channel endpoint, asserts a 4xx status and asserts that biber's session in that app is still alive.
- [ ] After the spec, Keycloak's log holds no failed back-channel call for any per-app client.

### Rollout

- [ ] Each app switches to its own client in its own change with its own Playwright proof, and removing its `services.sso.oidc.clients` entry returns it to the shared client.
- [ ] On an existing realm, the update routine `roles/web-app-keycloak/tasks/update/01_settings.yml`, fed by `KEYCLOAK_SETTINGS_CLIENT_IDS`, creates and converges each per-app client without a realm re-import.
- [ ] This requirement needs no universal-logout release, and the image pin in `roles/web-svc-logout/meta/services.yml` keeps the version it had before this change.
- [ ] The unit tests, the lint suite and ruff pass on every change of this rollout.
