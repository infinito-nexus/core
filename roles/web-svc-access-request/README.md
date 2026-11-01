# Access Request

## Description

A central service where a signed-in user requests roles of an application, and an approver grants them with their own Keycloak rights.

## Overview

The service sits behind the oauth2-proxy gate of [web-app-keycloak](../web-app-keycloak/) without a group requirement, so every realm user reaches it. It reads the requester only from the gate's headers, never from the form.

The 403 page of every SSO-gated application links here with the application preselected.

## Features

- **Role catalogue:** [catalogue.py](../../utils/roles/rbac/catalogue.py) builds the roles of every application from its `meta/rbac.yml` when the role deploys. The catalogue preselects the least-privileged role and marks administrator roles. A role is an administrator role when its name is `administrator` or ends in `-administrator`, or when it carries `realm_management` roles.
- **Requests:** a user picks several roles and gives a reason, which is mandatory. A user holds one open request per application; a second request updates the open one.
- **Delivery:** every request mails the platform administrator's secondary address through `lookup('email', application_id)`. With `web-app-zammad` deployed, it also files a Zammad ticket. Both carry the review link and a link to the requester's groups in the Keycloak admin console. The requester gets a mail when the request is granted, partly granted or rejected.
- **Review:** the review page shows the requester, the application, each requested role with its group path, the reason, and the requester's live groups. The approver can deselect roles before confirming.
- **Four eyes:** when `services.access-request.four_eyes` is `true`, a grant needs two different approvers. It grants only the roles both kept selected.
- **Grant:** confirming calls the Keycloak admin REST API with the approver's own access token. The service holds no Keycloak credential. An expired token leads to a sign-in page.

## Approvers

| Approver | Group | May grant |
|---|---|---|
| Platform administrator | `/roles/web-svc-access-request/administrator` | every role |
| Application administrator | `/roles/<application>/administrator` | the non-administrator roles of that application |

Keycloak's fine-grained admin permissions (v2) enforce the table. The service only hides what Keycloak would refuse.

## Approver Token

The token must carry:

- the realm the requester belongs to as its issuer;
- an active user session;
- the `manage-group-membership` scope on the user, granted through FGAP v2;
- `view` and `manage-membership` on each group, granted through FGAP v2.

Keycloak checks no audience on the admin REST API, so the session token the gate forwards works.

## Further Resources

- [Fine-grained admin permissions](https://www.keycloak.org/docs/latest/server_admin/#_fine_grained_permissions)
- [oauth2-proxy custom templates](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/)
