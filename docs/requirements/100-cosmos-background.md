# 100 - Cosmos Background in Designed Apps

## User Story

As the operator of a deployment that runs the custom role `web-app-cst-cosmos`, I want every designed app to load the cosmos library through its head injection and to clear its page surface while the sky is drawn, so that all apps share the live sky as one calm background, and a deployment without that role keeps every page exactly as it is.

This is core's part of [cosmos requirement 001](https://github.com/kevinveenbirkenbach/cosmos/blob/main/docs/requirements/001-cosmos.md) (decision 6; decisions 9, 10, 13, 16, 17 and 18 bind core).

## Acceptance Criteria

### Gate

- [x] `roles/web-svc-design/meta/services.yml` declares the service `cosmos` with `enabled: true` and `shared: true`, so the design role switches cosmos on and the service resolver deploys its provider with every designed app. Proof: `roles/web-svc-design/meta/services.yml`; `tests/unit/python/utils/design/test_cosmos.py` `TestTheServiceResolverDeploysThePulledProviderWithEveryDesignedRole` (fixture checkouts of every in-tree role: with the pulled role the ordered registry maps `cosmos` to it and `ServicesResolver` reaches it from each of the 91 designed roles; without it the key is absent).
- [x] Core addresses the provider only through the service key `cosmos` and the service registry ([046](046-custom-roles.md) places `web-app-cst-cosmos` under `roles/`, its entity `cosmos` registers it); no core file names the role. Proof: `tests/lint/repository/test_cosmos_provider_by_service_key.py` scans every file Git would track; the exempt files are the requirement texts, the test fixtures, the `eslint.config.js` entry the Lint criterion below demands, and the root custom roles manifest `meta/custom_roles.yml`, which pins the roles a checkout pulls.
- [x] `lookup('design', application_id).cosmos` returns the provider role while the registry knows a provider, the design role enables the service, and the designed role leaves `services.cosmos.enabled` unset or true; it returns `""` for a role that sets it to false, so a role forbids the sky explicitly. Proof: `utils/design/cosmos.py`, `plugins/lookup/design.py`; `tests/unit/python/utils/design/test_cosmos.py`, `tests/unit/python/plugins/lookup/test_design.py`.
- [x] `roles/sys-front-inj-design/templates/head_sub.j2` renders the cosmos tag only while that lookup returns a provider. Proof: `head_sub.j2`; `tests/unit/python/roles/sys-front-inj-design/test_cosmos_module_tag.py`.
- [x] Without a provider, rendering the head resolves no lookup naming a cosmos role, so a core checkout without the pulled role never asks `domain`, `tls` or `config` for it. Proof: `test_cosmos_module_tag.py` `test_no_lookup_names_the_reserved_role` (the `domain`, `tls` and `config` stubs fail on any call).

### Module tag

- [x] The tag is `<script type="module" src="/_infinito/cdn/roles/web-app-cst-cosmos/latest/js/cosmos.js?v=<mtime>" data-cosmos="...">`: the same-origin CDN path every front-proxy vhost serves, which `script-src-elem 'self'` of every generated CSP already allows, with the local mtime of `roles/web-app-cst-cosmos/files/javascript/cosmos.js` as cache buster. Proof: `head_sub.j2`; `test_cosmos_module_tag.py` `test_the_module_loads_same_origin_with_a_cache_buster`; the CDN location `roles/sys-svc-proxy/templates/cdn.conf.j2` is carried by every vhost flavour, enforced by `tests/lint/ansible/roles/test_vhost_cross_cutting_includes.py`; every directive starts with `'self'` at `plugins/filter/csp_filters.py`, asserted by `tests/unit/python/plugins/filter/test_csp_filters/test_build_basic.py`.
- [x] `data-cosmos` holds `zone` = `HOST_TIMEZONE`, the deployment default the module uses when the browser's timezone hides the place; core passes no coordinates. Proof: `head_sub.j2`; `test_cosmos_module_tag.py` `test_the_config_carries_the_host_zone_and_the_parent_cookie_domain`.
- [x] `data-cosmos` holds `hotkey` only when `applications.web-app-cst-cosmos.services.cosmos.hotkey` sets one. Proof: `head_sub.j2`; `test_cosmos_module_tag.py` `test_a_configured_hotkey_reaches_the_config_and_an_unset_one_stays_out`.
- [x] `data-cosmos` holds `cookieDomain` = `DOMAIN_PRIMARY` when the vhost is `DOMAIN_PRIMARY` or a name below it; an onion vhost and a vhost on another domain get no `cookieDomain`, so the module keeps a host-only cookie there. Proof: `head_sub.j2`; `test_cosmos_module_tag.py` `test_the_primary_domain_itself_shares_the_parent_cookie_domain`, `test_a_vhost_outside_the_primary_domain_gets_a_host_only_cookie` (onion, another domain, a name that only ends in the primary domain).
- [x] The config is HTML-escaped, and an HTML parser reads back the exact JSON, also for a hotkey that carries quotes, `<` and `>`. Proof: `head_sub.j2`; `test_cosmos_module_tag.py` `test_a_hostile_hotkey_survives_the_attribute`.

### Lint

- [x] `eslint.config.js` lints `roles/web-app-cst-cosmos/files/javascript/**/*.js` as ES modules, so the one-file library passes core's JavaScript lint once the role is pulled. Proof: `eslint.config.js`; ESLint over the library of cosmos `ansible/roles/web-app-cst-cosmos/files/javascript/cosmos.js` under that path reports no problem, under a CommonJS role path it fails to parse `import`/`export`.

### Cleared surfaces

- [x] A role clears its page surfaces in its own `templates/cosmos.css.j2`; `sys-front-inj-design` appends that sheet to the role stylesheet only while `lookup('design', application_id).cosmos` returns a provider. Proof: `roles/sys-front-inj-design/tasks/main.yml`, `templates/css/app.css.j2`; `test_resolve_render_once.py` `TestCosmosClearsASurfaceOnlyWhileItsProviderIsActive`; `test_cosmos_byte_identity.py` `test_an_active_provider_changes_exactly_the_roles_that_ship_a_cosmos_sheet`.
- [x] Every rule of such a sheet is scoped by `COSMOS_SKY_SELECTOR` (`html[data-cosmos-mode="full"]`) from `roles/sys-front-inj-design/vars/main.yml`, the only place that names the attribute, so a viewer who switched cosmos off by cookie and a framed page in `colors` mode keep the app's own background. Proof: `vars/main.yml`; `tests/lint/filesystem/test_cosmos_sheets.py` (every selector of every sheet starts with the rendered selector; no role file outside the vars file and the Playwright specs names a `data-cosmos-mode` or `data-cosmos-legible` attribute).
- [x] Without an active provider, the composed stylesheet of every role and its `?version=` stay byte-identical. Proof: `tests/unit/python/roles/sys-front-inj-design/test_cosmos_byte_identity.py` composes the sheet of every in-tree role on both networks, with and without the logo, through the current task and through its pre-cosmos expressions, and compares the facts and their SHA-1 version.
- [x] A cleared surface takes its text color from `--cosmos-text`. Proof: `test_cosmos_sheets.py` (a rule that clears `background` or `background-color` must set `color: var(--cosmos-text)`); `roles/web-svc-html/templates/cosmos.css.j2`.
- [x] While cosmos marks `html[data-cosmos-legible="top"]` (sunrise and sunset glow, where no text color holds 4.5:1 on the lower sky), the content blocks that carry text get their own surface, while `html` and `body` stay clear so cosmos keeps drawing the sky; the sheet scopes that rule by `COSMOS_LEGIBLE_TOP_SELECTOR` from the same vars file. Proof: `test_cosmos_sheets.py` (a sheet that clears a surface needs a legible-top rule with a surface and a text color whose subject is neither `html` nor `body`); `roles/web-svc-html/templates/cosmos.css.j2`.
- [x] `web-svc-html` clears `body`, and its links on the sky take that text color with an underline; in the legible-top band the children of its `body` take `--design-surface-1` and `--design-text`. Proof: `roles/web-svc-html/templates/cosmos.css.j2`; `test_resolve_render_once.py` `test_an_active_provider_appends_the_mapping_of_the_role`.

### Tests

- [x] A unit test resolves the provider for a silent role, an enabling role and a forbidding role, and returns `""` without a pulled provider and while the design role does not enable the service. Proof: `tests/unit/python/utils/design/test_cosmos.py`, `tests/unit/python/plugins/lookup/test_design.py`.
- [x] A unit test renders `head_sub.j2` with and without a provider and reads the tag back with an HTML parser. Proof: `tests/unit/python/roles/sys-front-inj-design/test_cosmos_module_tag.py`.
- [x] A unit test runs the resolve task of `sys-front-inj-design` for a mapped and an unmapped role, with and without a provider. Proof: `test_resolve_render_once.py` `TestCosmosClearsASurfaceOnlyWhileItsProviderIsActive` (four cases).
- [ ] In a compose deploy with the cosmos role pulled through [046](046-custom-roles.md), the `web-svc-html` Playwright spec finds the module tag, the module served as JavaScript, `html[data-cosmos-mode="full"]`, and a transparent `body` with `--cosmos-text` as color in light and dark mode; with the legible band pinned to `top` the `body` stays transparent and its children take `--design-surface-1` and `--design-text`.
- [ ] In a compose deploy without the cosmos role, the same spec finds no module tag, no `data-cosmos-mode` and a `body` that keeps `--design-surface-1`.
- [ ] `make test` passes.

### Rollout

- [ ] Each further designed app gets its `templates/cosmos.css.j2` once a Playwright run with cosmos on shows its page surface cleared and its text readable on the sky; until then it shows the sky only where its own surfaces leave it visible.
- [ ] A role whose page cannot sit on the sky sets `services.cosmos.enabled: false` in its `meta/services.yml`.
