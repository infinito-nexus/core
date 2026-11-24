# Access Request

## Description

A central service where a signed-in user requests roles of an application, and an approver grants them with their own Keycloak rights.

## Overview

The service sits behind the oauth2-proxy gate of [web-app-keycloak](../web-app-keycloak/) without a group requirement. Its gate sets `any_email`, so it admits a realm user of any email domain. It reads the requester only from the gate's headers, never from the form.

While the service is deployed, the 403 page links here with the application preselected:

- An application whose gate requires role groups (`services.sso.oauth2.allowed_groups`) answers with its own oauth2-proxy 403 page, [error.html.j2](templates/sso_proxy/error.html.j2). [sso_proxy.yml](../web-app-keycloak/tasks/sso_proxy.yml) renders it next to the gate's configuration.
- A restricted location (`services.sso.oauth2.restricted_locations`) redirects its 403 to the request page and preselects the roles of the location's groups.

An application whose gate requires no role group keeps the default oauth2-proxy pages.

## Features

- **Role catalogue:** [catalogue.py](../../utils/roles/rbac/catalogue.py) builds the roles of every deployed application from its `meta/rbac.yml` when the role deploys. The catalogue preselects the least-privileged role and marks administrator roles. A role is an administrator role when its name is `administrator` or ends in `-administrator`, or when it carries `realm_management` roles, such as `user-manager` of [web-app-keycloak](../web-app-keycloak/meta/rbac.yml).
- **Requests:** a user picks several roles and gives a reason, which is mandatory. A user holds one open request per application; a second request updates the open one.
- **Delivery:** every request mails the platform administrator's secondary address, or the primary one when it has none, through `lookup('email', application_id)`. With `web-app-zammad` deployed, it also files a Zammad ticket as the `access-request-zammad` agent, which [web-app-zammad](../web-app-zammad/) creates with the service's `zammad_api_token`. Both carry the review link and a link to the requester's groups in the Keycloak admin console. The requester gets a mail when the request is granted, partly granted or rejected.
- **Review:** the review page shows the requester, the application, each requested role with its group path, the reason, and the requester's live groups. The approver can deselect roles before confirming.
- **Four eyes:** when `services.access-request.four_eyes` is `true`, a grant needs two different approvers. It grants only the roles both kept selected.
- **Grant:** confirming calls the Keycloak admin REST API with the approver's own access token. The service holds no Keycloak credential. An expired token leads to a sign-in page.
- **Sign-out:** every signed-in page links to the gate's sign-out, which `lookup('sso', application_id, 'logout_url')` resolves. It clears the oauth2-proxy session and opens Keycloak's logout prompt, which ends the Keycloak session once confirmed. The link reuses the `choice_device` text of [logout_i18n.yml](../web-app-keycloak/files/logout_i18n.yml), so it reads like the dashboard's logout entry. The `401` sign-in page shows no sign-out.
- **Audit:** the realm records admin events, so every membership the service grants appears under the approver who confirmed it, for as many days as `services.keycloak.events.admin.expiration_days` of [web-app-keycloak](../web-app-keycloak/README.md) sets.
- **Texts:** the service and the 403 page read their texts from the `core` gettext catalogs under the `access_request:` and `rbac:` contexts of [extract.py](../../utils/i18n/extract.py).

## Approvers

| Approver | Group | May grant |
|---|---|---|
| Platform administrator | `/roles/web-svc-access-request/administrator` | every role group of the catalogue |
| Application administrator | `/roles/<application>/administrator` | the non-administrator roles of that application |

The realm enables fine-grained admin permissions (v2). While the service is deployed, [admin_permissions.py](../web-app-keycloak/files/python/rbac/admin_permissions.py) generates the table from the catalogue as `access-request:` policies and permissions of the realm's `admin-permissions` client. The service only hides what Keycloak would refuse.

## Approver Token

The token must carry:

- the realm the requester belongs to as its issuer;
- an active user session;
- the `manage-group-membership` scope on the user, granted through FGAP v2;
- `view` and `manage-membership` on each group, granted through FGAP v2;
- the built-in client scope `kc-admin-api`, without which Keycloak 26.8.2 answers `401`.

The gate therefore signs in through the service's own confidential client `access-request`, which `services.sso.oauth2.client` in [services.yml](meta/services.yml) declares with `kc-admin-api` as a default client scope; its secret is `sso_proxy_client_secret` from [secrets.yml](meta/secrets.yml). [web-app-keycloak](../web-app-keycloak/README.md) renders the client, and the shared client keeps the scope out, so a token of any other gated application cannot call the admin REST API.

## Persona contract opt-outs

The service has no login of its own. [identity.py](files/python/access_request/identity.py) reads the signed-in user only from the headers of the oauth2-proxy gate, so without the gate every request gets the `401` sign-in page. In the `services.sso.enabled: false` matrix variants the gate is gone, so [playwright.env.j2](templates/playwright.env.j2) renders `PERSONA_ADMINISTRATOR_BLOCKED=true` and `PERSONA_BIBER_BLOCKED=true`. With SSO enabled both personas run. The `guest` persona and the forged-identity scenario run in every variant. The same variants declare `server.status_codes.default: 401` in [variants.yml](meta/variants.yml), so the webserver and CSP health checks expect that sign-in page at `/` instead of the gate's redirect.

## Further Resources

- [Fine-grained admin permissions](https://www.keycloak.org/docs/latest/server_admin/#_fine_grained_permissions)
- [oauth2-proxy custom templates](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/)
