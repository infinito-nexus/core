# Identity and Access Management 🔐

OpenTalk authenticates users against the central Keycloak realm via OIDC and looks up users via the Keycloak admin Web API (`keycloak_webapi` backend). OpenLDAP feeds OpenTalk transitively through Keycloak's federation.

## OIDC 🪪

- Issuer URL: `{{ OIDC.CLIENT.ISSUER_URL }}`
- Frontend client ID: `{{ OIDC.CLIENT.ID }}` (shared with the rest of the platform)
- Controller client ID and secret: same shared Keycloak client; the secret is sourced from the central OIDC vault entry

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

Any user that exists in OpenLDAP and is reflected into the Keycloak realm can authenticate to OpenTalk and is auto-provisioned in the OpenTalk database on first login. The username equals the LDAP `uid`, delivered via the `preferred_username` claim.

## Admin Role Mapping 👤

Members of the `application_administrators` LDAP group (per requirement 004) receive `groups` claims that OpenTalk maps to elevated permissions. The exact role-to-group mapping is configured via the controller's role policy file or the Keycloak realm role mapper.

## Verify OIDC Discovery 🩺

```bash
make compose-exec cmd="container exec opentalk-controller sh -c 'curl -fsS {{ OIDC.CLIENT.DISCOVERY_DOCUMENT }} | head -c 200'"
```

## Verify Keycloak Admin API Access 🩺

```bash
make compose-exec cmd="container exec opentalk-controller sh -c 'curl -fsS -H \"Authorization: Bearer <token>\" {{ OPENTALK_KEYCLOAK_BASE_URL }}/admin/realms/{{ OIDC.CLIENT.REALM }}/users?search=alice'"
```
