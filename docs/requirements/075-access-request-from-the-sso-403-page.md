# 075 - Access Request from the SSO 403 Page

## User Story

As a signed-in user who reaches an application whose role groups I do not hold, I want to request the roles I need right from the 403 page so that an administrator can review and grant them without a separate channel.

## Decisions (2026-11-01)

1. A central access-request service handles every request. It sits behind an SSO login without a group requirement, so it knows the requester from the session, never from a form field.
2. The oauth2-proxy 403 page of every SSO-gated application offers a "request access" action that opens the service with the application id.
3. A request names one or more roles of that application from its `meta/rbac.yml` and carries a mandatory reason.
4. Each request becomes a Zammad ticket when `web-app-zammad` is deployed, and always an email to the approvers (the platform administrator's secondary address under the mailbox email policy).
5. Platform administrators approve every request; members of `/roles/<application>/administrator` approve requests for the non-administrator roles of their own application.
6. Approval works in one click and manually. The one-click link opens a review page; nothing is granted before the approver confirms it there. A switch makes a second, different approver mandatory (four eyes).
7. The service holds no Keycloak administration rights and no service account. It grants a confirmed request with the approving administrator's own token, and Keycloak's fine-grained admin permissions (v2) are the only authority on who may grant which group; the deploy generates those permissions from every role's `meta/rbac.yml`.
8. Every text the service and the 403 page show comes from the `core` gettext catalogs.

## Acceptance Criteria

### Request

- [x] The 403 page an SSO-gated application answers for a user without its role groups shows a "request access" action, and the action opens the access-request service with that application preselected (`roles/web-svc-access-request/templates/sso_proxy/error.html.j2` and the restricted-location redirect at `roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2`; proven by `test_the_request_action_opens_the_service_with_the_application` in `tests/unit/python/roles/web-svc-access-request/templates/test_sso_proxy_error_page.py` and `test_a_refused_restricted_location_redirects_to_the_request_page` in `tests/unit/python/roles/web-app-keycloak/templates/test_sso_proxy_restricted_403.py`).
- [x] The request form lists the application's roles with their descriptions, preselects the least-privileged one, marks administrator roles, allows several roles, and refuses a request without a reason.
- [x] A user holds at most one open request per application; a second request for the same application updates the open one.
- [x] The requester is identified only from the service's SSO session; a requester field in the submitted form is ignored.
- [ ] The service and the 403 page render in the user's language, and every string they show is a `core` catalog message.

### Delivery

- [ ] With `web-app-zammad` deployed, a request creates one Zammad ticket that names the requester, the application, every requested role with its group path and the reason, and links the review page and the user's groups in the Keycloak admin console.
- [x] Every request sends an email with the same content to the approvers, also when Zammad is not deployed.
- [x] The requester receives an email when the request is granted, partly granted or rejected.

### Review and grant

- [x] The review page shows the requester, the application, each requested role with its group path, the reason and the difference to the requester's current groups, and lets the approver deselect roles before confirming.
- [x] Confirming grants exactly the selected group memberships with the approver's own token; the service stores no credential that could grant a membership on its own.
- [ ] A member of `/roles/<application>/administrator` can grant the non-administrator roles of that application and Keycloak refuses that member every other group, enforced by fine-grained admin permissions generated from `meta/rbac.yml`.
- [x] With the four-eyes switch on, a grant takes effect only after a second, different approver confirms it, and the first approver cannot confirm twice.
- [ ] Keycloak's admin events attribute every granted membership to the approver who confirmed it.
- [x] The manual path works without the service: the link in the ticket and email opens the user's groups in the Keycloak admin console (`user_groups_console` in `roles/web-svc-access-request/files/python/access_request/keycloak.py`, placed into the delivery text by `roles/web-svc-access-request/files/python/access_request/app.py`; proven by `test_the_console_link_opens_the_users_groups_tab` in `tests/unit/python/roles/web-svc-access-request/files/access_request/test_keycloak.py` and `test_the_text_names_requester_roles_reason_and_links` in `tests/unit/python/roles/web-svc-access-request/files/access_request/test_delivery.py`).

### Tests

- [x] Unit tests cover the role catalogue built from `meta/rbac.yml`, the one-open-request rule, the four-eyes state and the ignored requester field.
- [ ] A Playwright spec signs in as biber without the role group of an application, requests two roles from its 403 page, signs in as the administrator, deselects one role on the review page, confirms, and asserts that biber holds exactly the confirmed role.
- [ ] A Playwright spec asserts that an application administrator cannot grant that application's administrator role or a role of another application.
