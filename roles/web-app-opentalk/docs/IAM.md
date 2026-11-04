# Identity and Access Management 🔐

OpenTalk authenticates users against the central Keycloak realm via OIDC and looks up users via the Keycloak admin Web API (`keycloak_webapi` backend). OpenLDAP feeds OpenTalk transitively through Keycloak's federation.

## OIDC 🪪

- Issuer URL: `{{ OIDC.CLIENT.ISSUER_URL }}`
- Frontend client ID: `{{ OPENTALK_FRONTEND_OIDC_CLIENT_ID }}`, a dedicated public client whose audience mapper adds the controller client to every access token, so the controller's token introspection accepts it
- Controller client ID and secret: `{{ OPENTALK_CTRL_OIDC_CLIENT_ID }}`, a confidential client; the secret is `secrets.credentials.controller_oidc_client_secret` of the role

## User Search 🔍

```toml
[user_search]
backend = "keycloak_webapi"
api_base_url = "{{ OPENTALK_KEYCLOAK_BASE_URL }}/admin/realms/{{ OIDC.CLIENT.REALM }}"
users_find_behavior = "from_user_search_backend"
```

The chain is:

```
OpenLDAP  ─►  Keycloak (LDAP federation)  ─►  OpenTalk (Keycloak admin API)
```

Any user that exists in OpenLDAP and is reflected into the Keycloak realm can authenticate to OpenTalk and is auto-provisioned in the OpenTalk database on first login. The controller identifies a user by the `sub` claim and refreshes `email`, `given_name`, `family_name`, `nickname`, `locale`, `zoneinfo` and `picture` from the userinfo endpoint on every login.

## Roles 👤

OpenTalk has no administrator role: controller migration `V21__remove_administrator_role.sql` removed it, and no claim grants elevated rights. The web frontend requests the fixed scopes `openid profile email`, so the `phone` scope is never requested, and the controller stores `phone_number` only when a `[call_in]` section is configured.

## Verify OIDC Discovery 🩺

```bash
make compose-exec cmd="container exec opentalk-controller sh -c 'curl -fsS {{ OIDC.CLIENT.DISCOVERY_DOCUMENT }} | head -c 200'"
```

## Verify Keycloak Admin API Access 🩺

```bash
make compose-exec cmd="container exec opentalk-controller sh -c 'curl -fsS -H \"Authorization: Bearer <token>\" {{ OPENTALK_KEYCLOAK_BASE_URL }}/admin/realms/{{ OIDC.CLIENT.REALM }}/users?search=alice'"
```
