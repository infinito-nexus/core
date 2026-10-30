# Login Methods 🚪

An application whose own sign-in page offers more than one way to sign in declares every method it offers under its entity in `meta/services.yml`, so that each method can be switched on its own and the page shows only what the deployment mode allows.

## Schema 🧩

```yaml
gitea:
  login:
    method:
      sso:
        enabled: "{{ lookup('login_method', 'web-app-gitea', 'sso') }}"
      ldap:
        enabled: "{{ lookup('login_method', 'web-app-gitea', 'ldap') }}"
      native:
        enabled: "{{ lookup('login_method', 'web-app-gitea', 'native') }}"
      2fa:
        enabled: "{{ lookup('login_method', 'web-app-gitea', '2fa') }}"
      openid2:
        enabled: "{{ lookup('login_method', 'web-app-gitea', 'openid2') }}"
```

- Declare only the methods the application offers: `sso`, `ldap`, `native`, `2fa`, and the extras `passkey`, `openid2`, `odoo_com`, `email` (magic link) and `registration` (local self-registration).
- Every default MUST be the `login_method` lookup of the role and the method. The lookup holds the one table in [login.py](../../../../utils/roles/applications/login.py), and [test_login_methods.py](../../../../tests/lint/ansible/services/test_login_methods.py) fails on any other value.
- An inventory overrides a single method with `applications.<app>.services.<entity>.login.method.<method>.enabled`.
- The role reads a method with `lookup('config', application_id, 'services.<entity>.login.method.<method>.enabled')`.

## Defaults by Mode 🧮

`sso` and `ldap` are the application's `services.sso.enabled` and `services.ldap.enabled`; an application without an `ldap` service counts as LDAP off.

| Mode | sso | ldap | native | 2fa | extras and registration |
|---|---|---|---|---|---|
| SSO on | on | off | off | off | off |
| SSO off, LDAP on | off | on | off | on | off |
| SSO off, LDAP off | off | off | on | on | off |

- With SSO on, the second factor lives in Keycloak, so the application's own one is off.
- `2fa` on offers the application's own second factor for enrollment; it never enforces it.

## Switching a Method Off 🔧

1. Use the application's own setting where one exists (environment variable, config file, database setting, plugin option).
2. Otherwise hide the entry with role-injected CSS or JavaScript through the role's `javascript` service, the way `web-app-pixelfed` hides its local form.
3. Where one form serves local and LDAP accounts, the LDAP mode keeps the form; `native` off then leaves no local account except the break-glass admin wherever the application can tell the two apart, and the role README states the shared form where it cannot.

## Break-Glass Access 🧯

Every application keeps one documented way for its local administrator to sign in while SSO is on: a URL parameter, a recovery account, a CLI or a token. The role README names it; where the path is a browser or HTTP API path, a Playwright spec signs the local administrator in through it.

## Scope 🎯

[test_login_methods.py](../../../../tests/lint/ansible/services/test_login_methods.py) requires the block in every role with `sso.flavor: oidc` or `saml`. A role whose sign-in offers one method only carries `# nocheck: login-methods  Reason: <why>` on its `sso:` key.
