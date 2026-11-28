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
        enforced: false
      openid2:
        enabled: "{{ lookup('login_method', 'web-app-gitea', 'openid2') }}"
```

- Declare only the methods the application offers: `sso`, `ldap`, `native`, `2fa`, and the extras `passkey`, `openid2`, `odoo_com`, `email` (magic link) and `registration` (local self-registration).
- Every default MUST be the `login_method` lookup of the role and the method. The lookup holds the one table in [login.py](../../../../utils/roles/applications/login.py), and [test_login_methods.py](../../../../tests/lint/ansible/services/test_login_methods.py) fails on any other value.
- The `2fa` method also declares `enforced`, whose default MUST be `true`; the same lint fails on a `2fa` block without it or with any other default. A role whose enforcement would lock out an account the deploy itself provisions defaults to `false` instead, is listed with its reason in `OFFERED_ONLY` of that lint, and says so in its README.
- A role whose SSO entry only renders on the application's own sign-in form defaults `native` to `true` instead, keeping the form beside SSO; it is listed with its reason in `NATIVE_BESIDE_SSO` of that lint and says so in its README.
- An inventory overrides a single method with `applications.<app>.services.<entity>.login.method.<method>.enabled`, and the enforcement with `applications.<app>.services.<entity>.login.method.2fa.enforced`.
- The role reads a method with `lookup('config', application_id, 'services.<entity>.login.method.<method>.enabled')`.

## Defaults by Mode 🧮

`sso` and `ldap` are the application's `services.sso.enabled` and `services.ldap.enabled`; an application without an `ldap` service counts as LDAP off.

| Mode | sso | ldap | native | 2fa | extras and registration |
|---|---|---|---|---|---|
| SSO on | on | off | off (on for a `NATIVE_BESIDE_SSO` role) | off | off |
| SSO off, LDAP on | off | on | off | on | off |
| SSO off, LDAP off | off | off | on | on | off |

- A `NATIVE_BESIDE_SSO` role keeps `native` on under SSO only so its SSO entry renders; it hides the form in the page and refuses the password login at its proxy, as `web-app-mattermost` does.
- With SSO on, the second factor lives in Keycloak, so the application's own one is off. The realm sends every account without a second factor to TOTP enrollment through `services.keycloak.realm.totp_enforced` of `web-app-keycloak` (default `true`).
- `2fa` on runs the application's own second factor. With `enforced: true`, the default, an account without a second factor enrolls one at its next sign-in before it gets in, wherever the application can enforce it; with `enforced: false` the application only offers it.
- The deploy manages the application's own enforcement setting only while `2fa` is on. While `2fa` is off, as in every SSO deployment, it leaves that setting as an admin set it by hand.
- Where the application has no setting that enforces its own second factor, `enforced` only offers it, and the role README says so.
- Every variant whose Playwright spec signs a local account in sets `login.method.2fa.enforced: false`, so automated logins skip enrollment while a production inventory keeps the default. One variant per role that exists to prove the enforced enrollment keeps it on instead: it marks its `enforced` key with `# nocheck: login-methods  Reason: <why>`, and every other local sign-in of its specs skips there.

## Switching a Method Off 🔧

1. Use the application's own setting where one exists (environment variable, config file, database setting, plugin option).
2. Otherwise hide the entry with role-injected CSS or JavaScript through the role's `javascript` service, the way `web-app-pixelfed` hides its local form.
3. Where one form serves local and LDAP accounts, the LDAP mode keeps the form; `native` off then leaves no local account except the break-glass admin wherever the application can tell the two apart, and the role README states the shared form where it cannot.

## Break-Glass Access 🧯

Every application keeps one documented way for its local administrator to sign in while SSO is on: a URL parameter, a recovery account, a CLI or a token. The role README names it; where the path is a browser or HTTP API path, a Playwright spec signs the local administrator in through it.

## Scope 🎯

[test_login_methods.py](../../../../tests/lint/ansible/services/test_login_methods.py) requires the block in every role with `sso.flavor: oidc` or `saml`. A role whose sign-in offers one method only carries `# nocheck: login-methods  Reason: <why>` on its `sso:` key.
