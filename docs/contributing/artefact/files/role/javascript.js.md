# `javascript.js` 📜

This page documents role-local JavaScript injection and browser-side integration behavior.
Use this page for injector wiring, activation, and repository-wide behavior rules.
For implementation scope, DOM strategy, and live review, see the [`javascript.js` authoring skill](../../../../../agents/skills/i8-file-role-javascript/SKILL.md).
For browser-side validation requirements after visible behavior changes, see [Playwright Tests](../../../actions/testing/playwright.md).

## `javascript.js.j2` ⚙️

- `sys-front-inj-javascript` loads `templates/javascript.js.j2` when it exists and otherwise falls back to `files/javascript/javascript.js`.
- The injector runs when `services.javascript.enabled` is enabled.
- The loaded script is collapsed into a one-liner before injection and added to the CSP hash list so inline execution remains consistent with the generated policy.
- You MUST use `javascript.js.j2` when the script depends on role variables or inventory values, and use `files/javascript/javascript.js` when the script is static.

## Inventory 📋

- You MUST keep `services.javascript.enabled` enabled in the role configuration or override it in the inventory when JavaScript injection should run.
- You MUST pass only the runtime values that the browser logic actually needs. Keep the rendered template surface small and explicit.

## Repository Rules 📏

- You MUST use role-local JavaScript only for browser-side integration gaps that cannot be solved cleanly through app configuration or CSS alone.
- When OIDC is enabled, you MUST disable or hide the normal login form in the UI if the target application does not already provide a dedicated configuration switch for that behavior.
- You MUST disable UI fields that are authored by OIDC or LDAP so users do not edit values locally that are managed by the identity provider or directory. Use the [SSO profile lock](#sso-profile-lock-) for them.
- You MUST NOT write values back from those UI fields to OIDC or LDAP through injected JavaScript. Treat those fields as externally managed and read-only in the application UI.

## SSO Profile Lock 🔒

A role whose SSO login, timer or deploy overwrites profile fields declares them under `services.sso.profile` in its `meta/services.yml`:

```yaml
sso:
  profile:
    locked:
      name: "#jform_name[data-infinito-sso-locked]"
      email: "#jform_email1[data-infinito-sso-locked]"
    languages: [en]
```

- `locked` maps each field to the CSS selector of its input. The selector MUST match only while the field is locked for the account the form edits, through a marker the role's server side renders for SSO accounts only. Every comma-separated part of it MUST match the role's pattern in `MANAGED_MARKER` of the lint below.
- `languages` lists the UI languages the application serves, `en` included. The renderer embeds only these languages of the catalogue; any other page language falls back to English. Every listed language other than `en` MUST translate each message of the catalogue in `locale/<code>/LC_MESSAGES/core.po`.
- `write_back` lists the fields the application writes back to Keycloak or LDAP itself. A role MAY declare it only with an entry in `WRITE_BACK` of the lint below that names the evidence.
- A role with `locked` MUST enable `services.javascript`, include the shared renderer in its `templates/javascript.js.j2`, and prove the lock in `files/playwright/test-profile-lock.js`, required from its `playwright.spec.js`; the spec reads the selectors from `PROFILE_LOCK_SELECTORS_JSON` of its `playwright.env.j2` and asserts that each matches a locked field:

  ```jinja
  {% include 'roles/sys-front-inj-javascript/templates/profile_lock.js.j2' %}
  ```

- The renderer sets every match read-only (`disabled` for a `select`) and `aria-readonly`, and shows the `locked` text of [profile_lock_i18n.yml](../../../../../roles/sys-front-inj-javascript/files/profile_lock_i18n.yml) in the page language as the hover title of the field, its labels and its wrapping element. It matches every selector with one query at load and again once per animation frame after the page adds elements. Selectors and catalogue reach the page through the `to_inline_js` filter. New texts reach the other languages through `make i18n-extract domain=core` and `make i18n-translate`.
- The renderer changes the page only. The role MUST also keep the stored value on the server when a form POST or an API request submits another one.
- [test_sso_profile_lock.py](../../../../../tests/lint/ansible/roles/meta/test_sso_profile_lock.py) checks the declaration, fails when a field a treated role overwrites is neither locked nor written back, and fails for a role with `sso` or `ldap` that is not in its inventory lists.
