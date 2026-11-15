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

A role whose SSO login, timer or deploy overwrites profile fields declares each of them as a field of its `meta/forms.yml` whose `source` is `sso.<ATTRIBUTE>`: the key of `OIDC.ATTRIBUTES` in [11_oidc.yml](../../../../../group_vars/all/11_oidc.yml) that holds the claim the sign-in writes into it, such as `sso.USERNAME`, never the claim name itself. `claim` in [sso_fields.py](../../../../../utils/roles/applications/sso_fields.py) resolves the claim from that key and refuses any other key:

```yaml
profile:
  path: /
  fields:
    name:
      source: sso.NAME
      mode: enforced
      selector: "#jform_name[data-infinito-sso-locked]"
    email:
      source: sso.EMAIL
      mode: enforced
      selector: "#jform_email1[data-infinito-sso-locked]"
```

The rest stays under `services.sso.profile` in its `meta/services.yml`:

```yaml
sso:
  profile:
    languages: [en]
```

- An `sso.<ATTRIBUTE>` field is `enforced`, takes no `when`, and gets no converge, drift line or banner. Its form `path` is the prefix of every page that shows the field, `/` when the application routes them freely.
- The `selector` MUST match only while the field is locked for the account the form edits, through a marker the role's server side renders for SSO accounts only. Every comma-separated part of it MUST match the role's pattern in `MANAGED_MARKER` of the lint below.
- `languages` lists the UI languages the application serves, `en` included. The renderer embeds only these languages of the catalogue; any other page language falls back to English. Every listed language other than `en` MUST translate each message of the catalogue in `locale/<code>/LC_MESSAGES/core.po`.
- `write_back` lists the fields the application writes back to Keycloak or LDAP itself. A role MAY declare it only with an entry in `WRITE_BACK` of the lint below that names the evidence.
- `overwritten` lists the fields the role's login, timer or deploy overwrites without writing them back; each MUST be an `sso.<ATTRIBUTE>` field or appear in `write_back`. `none_needed` states why no field needs treatment and stands alone. Either key classifies the role in its own meta instead of the inventory lists of the lint below, and a role MUST NOT be classified in both. A custom `roles/web-app-cst-*` role classifies itself this way in the `meta/services.yml` of its source repository, because the lint's lists live in core.
- `marker` is the regular expression every part of an `sso.<ATTRIBUTE>` selector MUST match, for a role that has no entry in `MANAGED_MARKER` of the lint below.
- A role with an `sso.<ATTRIBUTE>` field MUST enable `services.javascript`, include the shared renderer in its `templates/javascript.js.j2`, and prove the lock in `files/playwright/test-profile-lock.js`, required from its `playwright.spec.js`; the spec reads the selectors from `PROFILE_LOCK_SELECTORS_JSON` of its `playwright.env.j2`, which renders `lookup('field_locks', application_id).profile`, and asserts that each matches a locked field. The role's server guard reads the field keys from the same lookup:

  ```jinja
  {% include 'roles/sys-front-inj-javascript/templates/profile_lock.js.j2' %}
  ```

- The renderer sets every `textarea` and text-like `input` of a match read-only and disables every other control, because HTML ignores `readOnly` there: a `select`, a button, a radio button, a checkbox, a color, range or file input. A disabled control that posts a value gets a hidden input per value it would submit, so the form still posts the managed value; a button or a file input gets none. Every match also gets `aria-readonly`, and the renderer shows the `locked` text of [profile_lock_i18n.yml](../../../../../roles/sys-front-inj-javascript/files/profile_lock_i18n.yml) in the page language as the hover title of the field, its labels and its wrapping element. It matches every selector with one query at load and again once per animation frame after the page adds elements. Selectors and catalogue reach the page through the `to_inline_js` filter. New texts reach the other languages through `make i18n-extract domain=core` and `make i18n-translate`.
- The renderer changes the page only. The role MUST also keep the stored value on the server when a form POST or an API request submits another one.
- [test_sso_profile_lock.py](../../../../../tests/lint/ansible/roles/meta/test_sso_profile_lock.py) checks the declaration, fails when a field a treated role overwrites is neither locked nor written back, and fails for a role with `sso` or `ldap`, a custom role included, that neither its inventory lists nor its own `overwritten` or `none_needed` classify.

## Managed Field Lock 🔐

The same renderer locks every other `enforced` field of the role's `meta/forms.yml` whose `when` holds, as `lookup('field_locks', application_id)` lists them next to the profile lock, built by `locks` in [forms.py](../../../../../utils/roles/applications/forms.py). A role without `services.sso.profile.languages` embeds every language of the catalogue:

- It locks a field only on the page whose path and query start with the field's form `path`, and shows the `managed` text of the catalogue followed by the field's inventory path, `applications.<role>.<source>` or `users.<key>.<attr>`, as the hover title.
- A form `path` that holds a `#/` route matches against the location hash as well. The renderer reruns on every hash change and releases each field it no longer holds, so leaving a managed route leaves no lock behind.
- A form that names a `record` locks its fields only while the input its `selector` names shows one of the ids its `source` holds, the records the deployment created. A record an admin created stays editable, and turning to another record releases the field and resets its unlock. Every page carries the ids, so the source MUST name no secret.
- One banner with the `banner` text lists the label and inventory path of every managed field the page shows, above the form of the first one.
- A double-click on a managed field or its label asks the `unlock` text in a confirmation dialog; after the confirmation every control the field's selector matches stays editable, a disabled button that receives no double-click included, and so does every control the page renders for it later, until the page turns to another record or leaves the form's page. The banner keeps listing the field. A profile field offers no unlock, because the next sign-in overwrites it anyway. An unlock frees only what the renderer locked; a control the page disabled itself stays disabled.
- A text-like `input` of a field the fail-closed rule of `utils/roles/applications/forms.py` does not clear turns into a password input, so its value stays hidden on screen. The value still reaches the page source, so the role MUST NOT render a secret into the form where the application allows it.
- A `seeded` field gets no marker.
- A form with `native: true` is one the application locks itself, through a value its own config renders read-only, such as Matomo's `config.ini.php`, Moodle's `forced_plugin_settings` or Shopware's static configuration. The renderer gives its fields no marker, no banner and no unlock, while the deploy still converges them and reports their drift. A native form takes no `record` and no `sso.<ATTRIBUTE>` field, and `native` takes only `true`.
- A form with `lock: pending` holds fields no lock reaches yet, such as entity rows without a stable selector, and names in `issue` the upstream issue URL or id that tracks the missing lock. Its fields stay `enforced`: the deploy converges them and reports their drift, while the renderer gets none of them and `renderer_findings` accepts the missing lock. `lock` takes only `pending`, needs a non-empty `issue`, and excludes `native` and an `sso.<ATTRIBUTE>` field, whose warning the renderer must show; an `issue` without `lock: pending` is refused.
- A Rails `check_box` renders a hidden input of the same `name` with the value `0` in front of the checkbox. A selector by that `name` matches both, so the renderer disables both and carries the hidden `0` and, while the box is checked, its value after it. Rails reads the last value of a name, so a locked form posts the stored state.
- A role with an `enforced` field whose `source` is no `sso.<ATTRIBUTE>`, outside a native form, MUST set `services.javascript.enabled` to a literal `true`, which no variant overrides, and its `templates/javascript.js.j2` MUST reach the shared renderer, through the include above or a role template it renders, as the field lock of [web-app-keycloak](../../../../../roles/web-app-keycloak/templates/javascript.js.j2) does. `renderer_findings` in [test_forms.py](../../../../../tests/lint/ansible/roles/meta/test_forms.py) fails a role that misses either.

## Managed Field Keys and Sources 🧮

- A field key is the application's own setting name, in lower snake_case, lower camelCase or kebab-case, for example Matomo's `excludedQueryParameters` or the `publish-username` key of wp-discourse's `discourse_connect` array. A form key stays lower snake_case. A template reads a kebab-case key by subscript, as in `WORDPRESS_X['publish-username']`. `schema_errors` in [form_schema.py](../../../../../utils/roles/applications/form_schema.py) refuses any other key.
- A field of a form the role's env file carries reads the variable its `env` names, such as Pi-hole's `FTLCONF_webserver_domain`. Without `env` it reads its upper-cased key, which then stays lower snake_case. `env` takes a variable name that no other field of the form takes. `dotenv_names` and `dotenv_fields` in [dotenv.py](../../../../../plugins/filter/dotenv.py) derive the names [env.yml](../../../../../tasks/utils/forms/env.yml) reads from the form's fields, the role's env template writes each value under the name `dotenv_names` returns for them, and `name_findings` in [test_env_forms.py](../../../../../tests/lint/ansible/roles/meta/test_env_forms.py) fails an env form whose fields name no distinct variables.
- A value the role computes gets one key of its own in its `meta/services.yml`, and the field's `source` names that key. A role that enforces its title computes it in that key as `lookup('design', '<role>').label`, the design title or, without one, the H1 of the role's README. The lookup renders inside the applications render, and there is no shared title lookup.
- A field with `optional: true` is managed only while its `source` is not `false`. A role that leaves its title to the application while the design title is switched off sources `lookup('design', '<role>').title`, which is `false` then, and marks the field `optional`. `_applies` in [forms.py](../../../../../utils/roles/applications/forms.py) skips such a field after its `when`, so it gets no converge, no drift line and no lock. Without `optional`, a `false` source is a value the deploy writes and locks, as for a checkbox that is off. `optional` takes only `true` and no `sso.<ATTRIBUTE>` source.
