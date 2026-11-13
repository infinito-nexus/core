# 100 - Cosmos Background in Designed Apps

## User Story

As the operator of a deployment that runs the custom role `web-app-cst-cosmos`, I want every designed app to load the cosmos library through its head injection and to clear its page surface while the sky is drawn, so that all apps share the live sky as one calm background, and a deployment without that role keeps every page exactly as it is.

This is core's part of [cosmos requirement 001](https://github.com/kevinveenbirkenbach/cosmos/blob/main/docs/requirements/001-cosmos.md) (decision 6; decisions 9, 10, 13, 16, 17 and 18 bind core).

## Acceptance Criteria

### Gate

- [ ] `roles/web-svc-design/meta/services.yml` declares the service `cosmos` with `enabled: true` and `shared: true`, so the design role switches cosmos on and the service resolver deploys its provider with every designed app.
- [ ] Core addresses the provider only through the service key `cosmos` and the service registry ([046](046-custom-roles.md) places `web-app-cst-cosmos` under `roles/`, its entity `cosmos` registers it); no core file names the role.
- [ ] `lookup('design', application_id).cosmos` returns the provider role while the registry knows a provider, the design role enables the service, and the designed role leaves `services.cosmos.enabled` unset or true; it returns `""` for a role that sets it to false, so a role forbids the sky explicitly.
- [ ] `roles/sys-front-inj-design/templates/head_sub.j2` renders the cosmos tag only while that lookup returns a provider.
- [ ] Without a provider, rendering the head resolves no lookup naming a cosmos role, so a core checkout without the pulled role never asks `domain`, `tls` or `config` for it.

### Module tag

- [ ] The tag is `<script type="module" src="/_infinito/cdn/roles/web-app-cst-cosmos/latest/js/cosmos.js?v=<mtime>" data-cosmos="...">`: the same-origin CDN path every front-proxy vhost serves, which `script-src-elem 'self'` of every generated CSP already allows, with the local mtime of `roles/web-app-cst-cosmos/files/javascript/cosmos.js` as cache buster.
- [ ] `data-cosmos` holds `zone` = `HOST_TIMEZONE`, the deployment default the module uses when the browser's timezone hides the place; core passes no coordinates.
- [ ] `data-cosmos` holds `hotkey` only when `applications.web-app-cst-cosmos.services.cosmos.hotkey` sets one.
- [ ] `data-cosmos` holds `cookieDomain` = `DOMAIN_PRIMARY` when the vhost is `DOMAIN_PRIMARY` or a name below it; an onion vhost and a vhost on another domain get no `cookieDomain`, so the module keeps a host-only cookie there.
- [ ] The config is HTML-escaped, and an HTML parser reads back the exact JSON, also for a hotkey that carries quotes, `<` and `>`.

### Lint

- [ ] `eslint.config.js` lints `roles/web-app-cst-cosmos/files/javascript/**/*.js` as ES modules, so the one-file library passes core's JavaScript lint once the role is pulled.

### Cleared surfaces

- [ ] A role clears its page surfaces in its own `templates/cosmos.css.j2`; `sys-front-inj-design` appends that sheet to the role stylesheet only while `lookup('design', application_id).cosmos` returns a provider.
- [ ] Every rule of such a sheet is scoped by `COSMOS_SKY_SELECTOR` (`html[data-cosmos-mode="full"]`) from `roles/sys-front-inj-design/vars/main.yml`, the only place that names the attribute, so a viewer who switched cosmos off by cookie and a framed page in `colors` mode keep the app's own background.
- [ ] Without an active provider, the composed stylesheet of every role and its `?version=` stay byte-identical.
- [ ] A cleared surface takes its text color from `--cosmos-text`.
- [ ] While cosmos marks `html[data-cosmos-legible="top"]` (sunrise and sunset glow, where no text color holds 4.5:1 on the lower sky), the content blocks that carry text get their own surface, while `html` and `body` stay clear so cosmos keeps drawing the sky; the sheet scopes that rule by `COSMOS_LEGIBLE_TOP_SELECTOR` from the same vars file.
- [ ] `web-svc-html` clears `body`, and its links on the sky take that text color with an underline; in the legible-top band the children of its `body` take `--design-surface-1` and `--design-text`.

### Tests

- [ ] A unit test resolves the provider for a silent role, an enabling role and a forbidding role, and returns `""` without a pulled provider and while the design role does not enable the service.
- [ ] A unit test renders `head_sub.j2` with and without a provider and reads the tag back with an HTML parser.
- [ ] A unit test runs the resolve task of `sys-front-inj-design` for a mapped and an unmapped role, with and without a provider.
- [ ] In a compose deploy with the cosmos role pulled through [124](124-custom-roles-manifest.md), the `web-svc-html` Playwright spec finds the module tag, the module served as JavaScript, `html[data-cosmos-mode="full"]`, and a transparent `body` with `--cosmos-text` as color in light and dark mode; with the legible band pinned to `top` the `body` stays transparent and its children take `--design-surface-1` and `--design-text`.
- [ ] In a compose deploy without the cosmos role, the same spec finds no module tag, no `data-cosmos-mode` and a `body` that keeps `--design-surface-1`.
- [ ] `make test` passes.

### Rollout

- [ ] Each further designed app gets its `templates/cosmos.css.j2` once a Playwright run with cosmos on shows its page surface cleared and its text readable on the sky; until then it shows the sky only where its own surfaces leave it visible.
- [ ] A role whose page cannot sit on the sky sets `services.cosmos.enabled: false` in its `meta/services.yml`.
