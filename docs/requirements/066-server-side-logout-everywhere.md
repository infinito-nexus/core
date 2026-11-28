# 066 - Logout everywhere per network and device

## User Story

As a user who is signed in through one browser on the clearnet and the onion network, or on several devices, I want two explicit choices at logout, "Log out on this device" and "Log out everywhere", where the first ends every session of this browser the platform can end server to server and the second also ends every session of mine on all other devices, so that no network or device keeps a live session of mine that I did not choose to keep.

## Acceptance Criteria

### Trust boundary

- [x] No Keycloak client that this requirement adds or changes has `serviceAccountsEnabled: true`, and no service-account user of the realm gains a `realm-management` role through this requirement.
- [x] `web-svc-logout` owns no Keycloak client and its env file holds no Keycloak client secret. Its vhost adds exactly one route, the logout gate `^~ /backchannel/`, which admits POST only, and the only Keycloak values its container reads are the realm issuer, which the gate compares, and the public JWKS URL, the one Keycloak request it sends (operator pick of 2026-11-12, logout gate in universal-logout, replacing "it serves no route it did not serve before this change, and it sends no request to Keycloak"). `tests/unit/python/roles/web-svc-logout/test_trust_boundary.py` holds the env keys, the credential reads, the Keycloak values and the served locations; its negative controls catch the Keycloak client secret, a token endpoint call, an admin API call and a second new route.
- [x] The final state holds no `/everywhere` route, no `LOGOUT_EVERYWHERE_*` key, no `web-svc-logout` client in the realm render and no update routine that maps `realm-management` roles to a service account.
- [x] The realm keeps the values of `eventsEnabled`, `enabledEventTypes`, `eventsExpiration`, `adminEventsEnabled`, `adminEventsDetailsEnabled` and `eventsListeners` it had before this change.
- [x] No choice, nor any later replacement, uses a Keycloak service account, a `realm-management` role, the Keycloak admin REST API, stored realm events or a Keycloak extension (SPI provider); "Log out everywhere" uses only the user's own access token and the `manage-account` role of the `account` client.
- [ ] A logout sends no browser request without a user click that it did not send before this change, and the CSP of every vhost gains no new source and no new directive through this change (operator decision of 2026-11-03, replacing "byte-identical").
- [ ] Every back-channel endpoint this requirement wires answers a logout token with a bad signature, a foreign `iss`, a wrong `aud` or a missing `events` claim with a 4xx status and ends no session.
- [x] The "Log out everywhere" link carries no token, session id, user id or query parameter; it carries only the fragment marker defined below.

### Front-channel sweep per network

- [x] The shared OIDC client keeps `frontchannelLogout: true`, the conductor as `frontchannel.logout.url` and `frontchannel.logout.session.required: "true"`, as rendered by `roles/web-app-keycloak/templates/import/clients/default.json.j2`.
- [x] Each conductor still clears the cookies of every domain of its own network, as it does before this change.
- [x] The shared OIDC client carries no `backchannel.logout.url`.

### Back-channel logout per app

- [ ] Every app whose pinned upstream receives OIDC back-channel logout tokens declares its own client under `services.sso.oidc.clients` in its `meta/services.yml` and renders it in its `templates/keycloak/clients.json.j2`, the way `web-app-stalwart` does, and `roles/web-app-keycloak/filter_plugins/oidc_clients.py` includes it without a change on the Keycloak side.
- [x] Each such client has `frontchannelLogout: false`, `backchannel.logout.session.required: "true"` and a `backchannel.logout.url` on the app's canonical origin, except that the client of an app behind the logout gate sends its logout tokens to the gate `/backchannel/<application_id>` on the logout origin (operator pick of 2026-11-12, logout gate in universal-logout, replacing "and a `backchannel.logout.url` on the app's canonical origin").
- [x] Each such client's `redirectUris`, `webOrigins` and `post.logout.redirect.uris` cover every network sibling of the app through `lookup('network_urls', ...)`.
- [x] Each such client carries the client scopes and protocol mappers the app read from the shared client, so the app receives the same claims as before (username attribute, RBAC group claim, app scopes such as the Nextcloud scope of the shared client). `claim_findings` in `tests/unit/python/roles/web-app-keycloak/templates/test_backchannel_clients.py` holds every back-channel client to the default scopes of the shared client except `service_account`, its optional scopes except the app scopes of other applications, and its protocol mappers; the negative controls drop the group claim scope, the app's own scope and a shared mapper.
- [ ] An existing app user who signs in through the app's new client lands in the same app account as before the switch, and no second account appears.
- [ ] In one browser signed in to the app on the clearnet and on the onion network, a logout started on either network makes the app's next request on the other network ask for a new login.
- [ ] That back-channel logout also happens when JavaScript is disabled in the browser that logs out.
- [ ] Keycloak reaches every `backchannel.logout.url` from its container on a clearnet, an onion-only and a multi-network deployment; for an onion canonical origin, a pin sends the call over the local network to the proxy that serves the vhost, the way the SSO back-channel pin in `plugins/lookup/container_extra_hosts.py` does for calls from apps to Keycloak.
- [x] Keycloak verifies the TLS certificate of every `backchannel.logout.url`; under `TLS_MODE` `self_signed` it trusts the deployment CA, and no setting turns certificate verification off.

### Apps that qualify for back-channel logout

- [x] `web-app-matrix`: both flavors log Synapse in through its own client and set `backchannel_logout_enabled: true`. The compose flavor (`templates/flavor/compose/synapse/homeserver.yaml.j2`) already sets the flag but logs in through the shared client; the ansible flavor (`templates/flavor/ansible/vars.yml.j2`) lacks the flag. The `backchannel.logout.url` is `/_synapse/client/oidc/backchannel_logout` on the Synapse origin.
- [x] `web-app-nextcloud`: when `lookup('sso_oidc_plugin')` (`plugins/lookup/sso_oidc_plugin.py`) resolves to `oidc_login` (the default with LDAP) or `sociallogin` (the default without LDAP), Nextcloud stays on the shared client and its README row names its session lifetime; its own client with the `user_oidc` `backchannel.logout.url` `/index.php/apps/user_oidc/backchannel-logout/<provider identifier>` belongs to [094 - Nextcloud user_oidc Provider Registration](094-nextcloud-user-oidc-provider-registration.md), which registers the provider first (operator decision of 2026-11-03). `test_nextcloud_stays_on_the_shared_client` in `tests/unit/python/roles/web-app-keycloak/templates/test_backchannel_clients.py` holds Nextcloud to no own client for both plugins, and `test_user_oidc_brings_the_own_nextcloud_client` there holds the 094 client to `user_oidc` alone; its row in `roles/web-svc-logout/README.md` names the lifetime of both plugins.
- [x] `web-app-stalwart`: its `webui` and `webmail` clients render `frontchannelLogout: false` without a `backchannel.logout.url`. The Stalwart WebAdmin has no logout-token receiver and gets a README row. The Roundcube webmail receives logout tokens without checking their signature, so its `webmail` client stays without a `backchannel.logout.url` by the operator decision of 2026-11-03, and its README row names that exception. `test_the_stalwart_clients_carry_no_backchannel_logout_url` in `tests/unit/python/roles/web-app-keycloak/templates/test_backchannel_clients.py` renders both clients; the `web-app-stalwart` row of `roles/web-svc-logout/README.md` names both outcomes.
- [ ] `web-app-opencloud`, `web-app-espocrm`, `web-app-xwiki`, `web-app-moodle` and `web-app-openwebui` are checked against the upstream documentation of their pinned versions; each one that receives logout tokens gets its own client under the criteria above, and each one that does not gets a README row.
- [x] Every other role with `sso.flavor: oidc` stays on the shared client and gets a README row naming whether its pinned upstream receives logout tokens and how long its session lives. Each row cites the upstream source it was read from: the version the role pins, or, where the link text says "floating", the newest tag or branch head on 2026-11-06, because the role does not pin that component. `test_every_row_answers_yes_or_no_and_leaves_nothing_to_verify` in `tests/unit/python/roles/web-svc-logout/test_readme_backchannel_table.py` holds every row to a `yes` or `no`, and `test_a_pending_marker_in_any_cell_and_any_case_is_caught` is its negative control for `to verify` and `TBD` in every cell. The rows name four more receivers: `web-app-mediawiki` and `web-app-zammad` sign in through their own clients `mediawiki-web` and `zammad-web`, whose logout tokens go through the logout gate, because each receiver skips a check that OIDC Back-Channel Logout 1.0 requires (operator pick of 2026-11-12, logout gate in universal-logout, replacing "stay on the shared client until each switches to its own client under the criteria above in its own change"); `web-app-opentalk` signs in through its own clients `opentalk-controller` and `opentalk-frontend`, which the role creates through kcadm, and `opentalk-frontend` carries a `backchannel.logout.url` to the controller endpoint `/v1/auth/logout`; `web-app-openpost` signs in through its own confidential client `openpost-web`, whose `backchannel.logout.url` reaches the OpenPost receiver `/api/v1/auth/oidc/instance/backchannel-logout` without the logout gate, because OpenPost v7.42.2 checks the signature, `iss`, `aud` and `events` claim of every logout token through go-oidc's `VerifyLogout` and answers every failure with a 400; `test_the_openpost_client_logs_out_at_its_instance_provider_directly` in `tests/unit/python/roles/web-app-keycloak/templates/test_backchannel_clients.py` holds that client.

### oauth2-proxy-gated apps

- [x] `roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2` renders `cookie_refresh` from one configuration key of `web-app-keycloak` that the role config sets explicitly, and the render fails when the key is absent.
- [x] The shipped `cookie_refresh` value is the one the operator picks; `1m` is the proposal. The operator picked `1m` (listening round 2026-11-03); it ships at `roles/web-app-keycloak/meta/services.yml` and `tests/unit/python/roles/web-app-keycloak/templates/test_sso_proxy_cookie_refresh.py` holds it below both session lifetimes.
- [x] The value is shorter than the realm's `ssoSessionIdleTimeout` and than oauth2-proxy's `cookie_expire`, and a unit test fails on a value that is not.
- [ ] After Keycloak ends a user session, an oauth2-proxy session of that user on any network or device fails its next refresh, and the first request after one `cookie_refresh` interval redirects to the Keycloak login, never to a 5xx page.

### Decided: two logout choices

The operator decided that the user gets two explicit choices at logout, "Log out on this device" and "Log out everywhere". A logout on device A without the second choice ends no Keycloak session of device B.

#### Where the choices are offered

- [x] Every logout control lands on the Keycloak logout confirmation page `/realms/<realm>/protocol/openid-connect/logout` on the Keycloak origin of its network: `sys-front-inj-logout` points every app's logout control at `OIDC.CLIENT.LOGOUT_URL` without an `id_token_hint` (`roles/sys-front-inj-logout/templates/logout_one_liner.js.j2`), and the dashboard menu item does the same (`roles/web-app-dashboard/templates/menu/header.yml.j2`). This page shows both choices.
- [x] "Log out on this device" is Keycloak's existing confirm submit (`#kc-logout`), relabelled.
- [x] "Log out everywhere" is a plain link to the dashboard of the same network with the fragment `#logout-everywhere`.
- [ ] Both choices render with JavaScript on and with JavaScript off: a `logout-confirm.ftl` override in the corporate login theme (`roles/web-app-keycloak/templates/theme/login/`, staged by `roles/web-app-keycloak/tasks/utils/theme.yml`) renders them server side; when `services.keycloak.design` disables the corporate theme, the logout panel (`roles/web-app-keycloak/files/javascript/logout-panel.js`) adds the "Log out everywhere" link and the page shows the stock "Log out on this device" submit.
- [x] The "Account" menu of the dashboard (`roles/web-app-dashboard/templates/menu/header.yml.j2`) shows the same two items: "Log out on this device" with the existing `OIDC.CLIENT.LOGOUT_URL` and "Log out everywhere" with the `#logout-everywhere` marker.
- [x] When `web-app-dashboard` with OIDC is not part of the deployment, the confirmation page renders no "Log out everywhere".

#### "Log out on this device"

- [ ] It runs the existing logout: the front-channel conductor sweep per network for the shared client, the per-app back-channel logout and the oauth2-proxy `cookie_refresh` of the sections above.
- [ ] It ends this browser's Keycloak session, so the clearnet and onion siblings of one browser are both logged out, and no session of another device or browser context.
- [x] Its success message (`all_done` in `roles/web-app-keycloak/files/logout_i18n.yml`) names its scope, this device, and no longer reads "everywhere".

#### "Log out everywhere"

- [x] The token holder is the keycloak-js instance of `roles/web-app-dashboard/templates/javascript/oidc.js.j2`: it runs `check-sso` with the dashboard's own public client, declared under `services.sso.oidc.clients` in `roles/web-app-dashboard/meta/services.yml` and rendered by `roles/web-app-dashboard/templates/keycloak/clients.json.j2`, and keeps the user's access token fresh. The action runs while the user's session is still valid; when `check-sso` finds no session, the dashboard starts `keycloak.login()` and runs the action after the return.
- [x] Its access token carries the `account` audience through the audience resolve mapper of the `roles` scope (`roles/web-app-keycloak/templates/import/realm.json.j2`), `manage-account` through `default-roles-<realm>` (`realm.json.j2`) and the dashboard origin in `allowed-origins` through the client-level `oidc-allowed-origins-mapper` of the dashboard's own client, fed by that client's own `webOrigins`. Keycloak's Account REST API checks that audience and answers CORS from that `allowed-origins` claim.
- [x] On the `#logout-everywhere` marker or the menu click, the dashboard sends, with that token only, `GET /realms/<realm>/account/applications`, then `DELETE /realms/<realm>/account/applications/<clientId>/consent` for every entry with `offlineAccess: true`, which revokes that client's offline token, then `DELETE /realms/<realm>/account/sessions`, the call the Account Console's "Sign out all devices" makes, which ends every other online session of the user.
- [x] It then calls `keycloak.logout()`, which runs "Log out on this device" for this browser, conductor sweep included.
- [x] The realm keeps `manage-account` of the `account` client in `default-roles-<realm>` and keeps the `account` client, both rendered by `roles/web-app-keycloak/templates/import/realm.json.j2`.
- [ ] After "Log out everywhere" on device A, the next OIDC authentication on device B asks for credentials, no offline token of the user still refreshes, B's sessions of every app with its own back-channel client end at their next request, and B's oauth2-proxy sessions end within one `cookie_refresh` interval.
- [x] Rejected: the Account Console route `/realms/<realm>/account/account-security/device-activity` as the place of the action, because its "Sign out all devices" ends online sessions only, is hidden while one session exists and skips the logout when its `DELETE` fails (`signOutAll` in Keycloak's `DeviceActivity.tsx` has no error handling), and changing that needs a custom account theme build.

#### Labels

- [x] The labels "Log out on this device" and "Log out everywhere", the everywhere success message and the partial-logout message live in the `logout` catalogue (`roles/web-app-keycloak/files/logout_i18n.yml`), served through `lookup('i18n_catalogue', 'logout', ...)`, and have a translation in every language block the catalogue serves; the dashboard reads the same keys.

### Failure semantics

- [ ] When a back-channel endpoint is unreachable or answers with a non-2xx status, Keycloak still ends the user session and completes the logout redirect, and Keycloak's log names the client whose back-channel call failed.
- [x] The app behind such a failed call keeps its session until its own expiry, which its README row names.
- [x] The per-network sweep keeps its failure reporting: the conductor's `done` report counts failed domains and the Keycloak logout panel shows its `partial` message.
- [ ] A failed oauth2-proxy refresh ends the proxy session and redirects to the Keycloak login.
- [x] When any Account REST call of "Log out everywhere" fails, times out or answers with a non-2xx status, the dashboard still calls `keycloak.logout()`, this browser is logged out as with "Log out on this device", and after the post-logout redirect the user sees the partial-logout message that other devices may still be signed in.
- [x] A per-app client reuses `OIDC.CLIENT.SECRET`, as the Stalwart `webmail` client does, and the realm render and the Keycloak update routine succeed on an inventory created before this change without running the credential generator.

### Documentation

- [x] `roles/web-svc-logout/README.md` holds one table row per role with an `sso` service, except a custom `roles/web-app-cst-*` role, which declares the same row under `sso.backchannel` in its own `meta/services.yml`: its flavor, whether its pinned upstream receives OIDC back-channel logout tokens (yes, no or to verify), its endpoint, the upstream documentation link, and how long its session lives on another network or device when nothing ends it. `test_the_table_holds_one_row_per_sso_role_with_its_flavor` in `tests/unit/python/roles/web-svc-logout/test_readme_backchannel_table.py` holds the table to one filled row per role with an `sso` service and its flavor, and `test_every_row_answers_yes_or_no_and_leaves_nothing_to_verify` refuses `to verify` and `TBD`, in any case, in every cell.
- [x] The same README describes the two choices, "Log out on this device" (per-network front-channel sweep, per-app back-channel logout, oauth2-proxy refresh) and "Log out everywhere" (the Account REST calls with the user's own token, then "Log out on this device"), and lists which sessions each one ends.

### Tests

- [x] A unit test renders every `templates/keycloak/clients.json.j2` and asserts per back-channel client `frontchannelLogout: false`, `serviceAccountsEnabled: false`, a `backchannel.logout.url` on the app's canonical origin, or the logout gate for an app behind it, and redirect URIs for every network sibling; a negative control with a `backchannel.logout.url` on the shared client fails it (operator pick of 2026-11-12, logout gate in universal-logout, replacing "a `backchannel.logout.url` on the app's canonical origin and redirect URIs"). In `tests/unit/python/roles/web-app-keycloak/templates/test_backchannel_clients.py`, `test_every_backchannel_client_is_safe_and_reaches_every_network` and `test_every_gated_client_sends_its_logout_tokens_through_the_gate` hold the clients, `test_a_backchannel_url_on_the_shared_client_fails_the_check` is the shared-client control, and `test_a_gated_client_that_skips_the_gate_fails_the_check`, `test_a_gate_url_of_another_role_fails_the_check` and `test_a_role_the_gate_does_not_serve_cannot_use_the_gate` are the controls of the gate.
- [x] A unit test renders `roles/web-app-keycloak/templates/import/realm.json.j2` against an inventory fixture that holds only the credentials present before this change, asserts that the render succeeds and asserts that no service-account user holds a `realm-management` role.
- [x] A unit test renders the oauth2-proxy config, asserts that `cookie_refresh` equals the configured value and asserts that the render fails when the key is absent.
- [x] A unit test renders both Synapse flavors and asserts the Synapse client id and `backchannel_logout_enabled: true` in each.
- [ ] Network case of the Playwright spec of `web-svc-logout`: in one browser context, biber signs in to a back-channel app and to an oauth2-proxy app on the clearnet origin and on the onion origin of the same node, logs out on the clearnet origin, and the spec asserts that the back-channel app's next onion request asks for a login and that the oauth2-proxy app's onion request does so after one `cookie_refresh` interval.
- [ ] The network case also passes with `javaScriptEnabled: false` for the logout step.
- [x] A unit test loads `roles/web-app-keycloak/files/logout_i18n.yml` through the `i18n_catalogue` lookup and asserts that both choice labels, the everywhere success message and the partial-logout message have a non-empty translation in every language block.
- [ ] Choice case of the same spec: on the Keycloak logout confirmation page and in the dashboard "Account" menu, both choices are visible with `javaScriptEnabled: true` and on the confirmation page also with `javaScriptEnabled: false`.
- [ ] Device case "on this device": biber signs in on two browser contexts A and B, A signed in on the clearnet and the onion origin; after "Log out on this device" in A, both networks of A ask for a login and B is still signed in to Keycloak and to its back-channel app.
- [ ] Device case "everywhere": after "Log out everywhere" in A, both networks of A ask for a login, B's next OIDC authentication asks for credentials, B's back-channel app session ended and `GET /realms/<realm>/account/applications` with a fresh token of biber lists no entry with `offlineAccess: true`.
- [ ] Failure case: with the Account REST `DELETE` answered by a non-2xx status through Playwright request routing, A is still logged out on both networks and shows the partial-logout message.
- [ ] Forged-token case of the same spec: it POSTs a logout token signed with a foreign key to every back-channel endpoint, asserts a 4xx status and asserts that biber's session in that app is still alive.
- [ ] After the spec, Keycloak's log holds no failed back-channel call for any per-app client.

### Rollout

- [ ] Each app switches to its own client in its own change with its own Playwright proof. Switching an app back to the shared client is an explicit change of its client id in its `meta/services.yml`, and a missing `services.sso.oidc.clients` entry fails the render loudly; no lookup falls back to the shared client silently.
- [x] On an existing realm, the update routine `roles/web-app-keycloak/tasks/update/01_settings.yml`, fed by `KEYCLOAK_SETTINGS_CLIENT_IDS`, creates and converges each per-app client without a realm re-import.
- [ ] The logout gate ships in a universal-logout release, and the image pin in `roles/web-svc-logout/meta/services.yml` names that release (operator pick of 2026-11-12, logout gate in universal-logout, replacing "This requirement needs no universal-logout release").
- [ ] The unit tests, the lint suite and ruff pass on every change of this rollout.
