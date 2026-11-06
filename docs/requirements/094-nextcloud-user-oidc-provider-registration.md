# 094 - Nextcloud user_oidc Provider Registration

## User Story

As a platform operator who runs Nextcloud with the `user_oidc` plugin, I want the deployment to register the Keycloak provider in `user_oidc` with Nextcloud's own Keycloak client, so that Nextcloud signs its users in to their existing accounts and ends their sessions when Keycloak sends a back-channel logout token.

## Background

[066 - Logout everywhere per network and device](066-server-side-logout-everywhere.md) keeps Nextcloud on the shared client: `oidc_login` (the default with LDAP) and `sociallogin` (the default without LDAP) receive no logout token, and `user_oidc` does, but `lookup('sso_oidc_plugin')` (`plugins/lookup/sso_oidc_plugin.py`) can select `user_oidc` only through `services.sso.oidc.plugin`, and the role does not register its provider yet (`roles/web-svc-logout/README.md`, row `web-app-nextcloud`). The operator decided on 2026-11-03 that the provider registration is a requirement of its own.

`user_oidc` v8.12.0 documents the provider command `occ user_oidc:provider`, the back-channel logout URL `/index.php/apps/user_oidc/backchannel-logout/<provider identifier>` with "Backchannel Logout Session Required", and a user id that hashes the provider id with the user id unless the provider option turns that off ([README](https://github.com/nextcloud/user_oidc/blob/v8.12.0/README.md)).

## Acceptance Criteria

- [ ] With `lookup('sso_oidc_plugin')` resolving to `user_oidc`, the deploy registers exactly one Keycloak provider through `occ user_oidc:provider` with the realm's discovery URI and the id and secret of Nextcloud's own client, and a second deploy converges it without creating another provider.
- [ ] `web-app-nextcloud` declares its own client under `services.sso.oidc.clients` in `meta/services.yml` and renders it in `templates/keycloak/clients.json.j2`, and `roles/web-app-keycloak/filter_plugins/oidc_clients.py` includes it without a change on the Keycloak side.
- [ ] That client has `frontchannelLogout: false`, `backchannel.logout.session.required: "true"`, the `backchannel.logout.url` `/index.php/apps/user_oidc/backchannel-logout/<provider identifier>` on Nextcloud's canonical origin, and redirect URIs, web origins and post-logout redirect URIs for every network sibling through `lookup('network_urls', ...)`.
- [ ] The client carries the client scopes and protocol mappers Nextcloud read from the shared client, including the Nextcloud scope and the RBAC group claim, so that `claim_findings` in `tests/unit/python/roles/web-app-keycloak/templates/test_backchannel_clients.py` reports nothing for it.
- [ ] The provider maps the Nextcloud user id to `preferred_username` and turns the hashed unique user id off, so an existing account signs in to the same account after the switch and no second account appears.
- [ ] The provider maps display name, email, quota and groups from the claims, and the group claim provisions the RBAC groups the other plugins provision.
- [ ] A variant in `roles/web-app-nextcloud/meta/variants.yml` selects `user_oidc`, so the matrix deploys it.
- [ ] In one browser signed in to Nextcloud on the clearnet and on the onion network, a logout started on either network makes Nextcloud's next request on the other network ask for a new login, also with JavaScript disabled in the browser that logs out.
- [ ] With SSO on, the `user_oidc` sign-in page shows only the SSO entry and the README documents the break-glass path of the local administrator, as [064 - Login Methods per Application](064-login-methods-per-application.md) requires.
- [ ] A unit test renders the provider registration and the client, and a Playwright spec of the `user_oidc` variant signs biber in to the account biber held before the switch and proves the back-channel logout.
- [ ] The `web-app-nextcloud` row of `roles/web-svc-logout/README.md` names the `user_oidc` client, its endpoint and its session lifetime once the switch is deployed.
