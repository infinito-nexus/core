# 037 - Corporate Design Overhaul

## User Story

As an operator of Infinito.Nexus, I want every web UI to follow one configurable corporate design (palette, typography, logo, title, light and dark mode) so that all apps read as one platform while the base color stays changeable from a single setting.

## Confirmed Decisions

These choices are settled at requirement creation time and bound the implementation. Re-opening any of them MUST be recorded in the implementing PR.

1. **One SPOT role.** `web-svc-css` is renamed to `web-svc-design`. The content of `group_vars/all/13_design.yml` moves into the `design` entity of `roles/web-svc-design/meta/services.yml`, the group_vars file is deleted, and the unused `filters` block is dropped. Inventories and docs are migrated. No compatibility shim.
2. **Service keys.** Consumers replace their `css:` key with `design:`. CSS injection is driven by `design` only. An enabled `design` always brings its own JavaScript channel: the role's optional `templates/design.js.j2`, collapsed, CSP-hashed and injected by `sys-front-inj-design`. The `javascript:` key stays independent and keeps gating the role's functional script (`javascript.js.j2`, which carries SSO and logout glue that must not run without SSO). `sys-front-inj-css` is renamed to `sys-front-inj-design` because injector feature names map one to one onto `sys-front-inj-<feature>` roles; `sys-front-inj-javascript` stays.
3. **Palette engine.** An in-repo OKLCH lookup plugin replaces the `colorscheme_generator` dependency. Its only input is `design.colors.base`. It derives a primary scale 50 to 950, tinted neutrals, status colors (success, warning, danger, info) with fixed hues and harmonised chroma, on-colors chosen by contrast, and a dedicated dark palette (no lightness inversion). Text tokens meet WCAG 2.2 AA (4.5:1), UI and large text meet 3:1, body text meets AAA (7:1). An invalid hex value fails the deploy.
4. **Semantic tokens.** `--design-primary`, `--design-on-primary`, `--design-link`, `--design-surface-1` to `--design-surface-3`, `--design-text`, `--design-text-muted`, `--design-border`, `--design-border-strong`, `--design-success`, `--design-warning`, `--design-danger`, `--design-info` with their `--design-on-*` partners, the interaction states `--design-surface-hover`, `--design-surface-active` and `--design-<fill>-hover`, `--design-<fill>-active` (each keeps its text at AA or better), and the `--design-primary-*` and `--design-neutral-*` scales 50 to 950 replace `--color-NN-SS` and `--color-rgb-NN-SS`. Every color also exists as `<token>-rgb`. `--design-invert` is `0` in light and `1` in dark mode, so `filter: invert(var(--design-invert))` flips a monochrome image with the mode. Scale step 50 sits next to the surface and 950 next to the text in both modes, so a role mapping onto the scale follows dark mode without its own media query. Bootstrap `--bs-*` variables map onto the tokens. The Bootstrap component mapping (`bootstrap.css`) is linked only for roles whose `design:` entry sets `bootstrap: true`. The 22 existing role stylesheets are migrated mechanically in the base and refined in the role loop.
5. **Clean, flat base style.** No gradients on form controls and tables, subtle elevation shadows, one radius scale, 4/8 px spacing, visible focus rings, form state shown by border and icon. Font is the `system-ui` stack; `design.font` stays configurable. The shared element styles sit in the cascade layer `infinito-design`, so an app's own design system always wins over them and keeps its contrast relations. Such an app takes the palette through its own configuration first: a theming configuration, then an in-house theme or custom CSS option. Its role stylesheet maps the app's variables only for what no in-house option reaches.
6. **Dark mode.** An app's native theme toggle wins. Without one, the design follows `prefers-color-scheme`. No theme toggle is injected.
7. **Logo and title override semantics.** `design.logo` defaults to `assets/img/logo.png`, `design.title` defaults to `true`, which resolves to the role title (README H1). Set in `web-svc-design`, a value applies to every role. Set in a role's own `design:` entry, it applies to that role only. `false` or `0` disables the replacement for that scope. The legacy keys `title`, `titel`, `sitename` and `site_name` are migrated, the hardcoded titles in `web-app-joomla` and `web-app-pretix` are removed, and `web-app-decidim` and `web-app-socialhome` read the resolved title instead of `defaults_*`.
8. **Logo generator.** An SVG template renders the lockup, Pillow rasterises PNG and ICO variants. The variant is computed from the target slot format: square slot shows the logo only, wide slot shows logo and title, very wide or two-line slot adds the domain, text-only slot shows the title only. The background stays transparent. The text uses palette colors with an outline so it stands out on light and dark surfaces. A slot declared with `frame: true` sits on brand-colored chrome and takes the frame text color with a frame-colored outline.
9. **Branch and stack.** One branch `feature/designer` and one draft PR, opened once the base is approved. Exactly one compose stack runs at a time. Base changes land as base commits on the same branch. Role changes stay under `roles/<role>/` and are committed per role after approval.
10. **Verification.** Every change passes `make quality-high` and a minimal compose deploy against the running stack: `make compose-deploy apps=<role> variant=0 disable=<every disableable service except design>` (default `initialize` mode, no teardown, single pass, no `full_cycle`). CSS and branding iterations run without a redeploy through `make design-sync app=<role> variant=0` (re-renders shared CSS, role `style.css` and the generated logo assets). A changed `design.js`, task, template or `meta/` file runs through `make compose-role-sync role=<role> variant=0`, which re-runs only the app role against the running stack and renders the CSP hash in the vhost with it. A role pass runs the gate once, after its last edit, and repeats the compose deploy at its end only when it changed provisioning; any other pass closes with a role sync and the complete role spec. Each role is also asserted with one further base color, blue `#001f3f`, through `base=` on the sync targets. Swarm verification is out of scope.
11. **Review gallery.** Each role gets its own private Artifact with at least 20 views, each captured in light and dark mode and in a desktop (1440×900) and a mobile (390×844) viewport, so at least 80 before/after pairs per role. The views favour detail-rich surfaces: settings, administration, forms, lists and detail pages, logged in where the app has accounts, with idempotently seeded showcase content where a list or detail page would otherwise be empty. "Before" is the deployed app with every injected snippet stripped from the document (the body filter wraps its injections in `<!--infinito-inj-->` markers), "after" is the same page with the corporate design. `make design-gallery app=<role>` captures both sides in one spec run and copies them to `/tmp/design-gallery/<role>/`. The operator approves or rejects by comment.
12. **Frontend and backend.** Every role is styled and tested on its frontend and, where the app has one, on its separate backend (admin surface such as `wp-admin`, the Shopware or Magento admin, the Joomla administrator). A role with a backend shows backend views in its gallery in addition to the frontend views, and its Playwright spec covers both surfaces.
13. **Scope.** In-scope roles are invokable, carry a lifecycle inside the tested envelope (`alpha` to `maintenance`), and expose a web UI.

## Acceptance Criteria

### Base

- [x] `roles/web-svc-css` no longer exists and `roles/web-svc-design` deploys and serves the shared CSS.
- [x] `group_vars/all/13_design.yml` no longer exists and the design configuration resolves from `roles/web-svc-design/meta/services.yml`, overridable per inventory.
- [x] No `roles/*/meta/services.yml` declares a `css:` key.
- [x] A role with `design` enabled, `javascript` disabled and a `templates/design.js.j2` receives the injected CSS and its design script, and no functional script.
- [ ] A role with `design` disabled and `javascript` enabled receives its functional script and no injected CSS or design script.
- [ ] A minimal deploy with `disable=design` injects neither the shared CSS nor a design script.
- [x] `colorscheme_generator` is no longer a dependency and the OKLCH lookup plugin produces the full token set.
- [x] A unit test proves AA contrast for text and UI tokens and AAA contrast for body text in light and dark mode across the base colors `#001f3f`, `#FFA500`, `#FFFF00`, `#00FF00`, `#808080` and `#FF00FF`.
- [x] An invalid `design.colors.base` fails the deploy with an error naming the value.
- [x] No `--color-NN-SS` or `--color-rgb-NN-SS` reference remains under `roles/`.
- [x] The shared CSS contains no gradient on form controls or tables.
- [x] The shared CSS switches palettes via `prefers-color-scheme` and injects no theme toggle.
- [x] The logo generator emits SVG, PNG and ICO variants with transparent background for square, wide, very wide and text-only slots.
- [x] A unit test proves the logo and title precedence: global value, per-role override, and `false`/`0` disabling.
- [x] No `roles/*/meta/services.yml` declares a site title as `title`, `titel`, `sitename`, `site_name` or `site_titel` on its primary entity; every site title lives in the role's `design` entry and is read through `lookup('design', application_id)`.
- [x] `web-app-joomla` and `web-app-pretix` carry no hardcoded site title.
- [ ] `web-app-decidim` and `web-app-socialhome` honour an inventory title override.
- [x] The base gallery on `web-app-dashboard`, `web-app-gitea` and `web-app-nextcloud` is approved by the operator.
- [ ] The draft PR from `feature/designer` is open and linked below.

### Roles

A role is checked when its frontend and, where present, its backend are styled, its CSS and JS use only `--design-*` tokens, its logo and title are set through the app's own mechanism in the slot format, its Playwright spec covers frontend and backend and asserts token colors, contrast of core elements, light and dark mode, the native toggle where one exists, and the visible logo and title, `make quality-high` and the minimal compose deploy are green, its gallery is approved and linked under "Further Resources" in the role README, and the change is committed.

- [ ] web-app-akaunting
- [ ] web-app-baserow
- [ ] web-app-bigbluebutton
- [ ] web-app-bluesky
- [ ] web-app-bookwyrm
- [ ] web-app-bridgy-fed
- [ ] web-app-checkmk
- [ ] web-app-chess
- [ ] web-app-dashboard
- [ ] web-app-decidim
- [ ] web-app-discourse
- [ ] web-app-erpnext
- [ ] web-app-espocrm
- [ ] web-app-fediwall
- [ ] web-app-fider
- [ ] web-app-flowise
- [ ] web-app-friendica
- [ ] web-app-funkwhale
- [ ] web-app-fusiondirectory
- [ ] web-app-gitea
- [ ] web-app-gitlab
- [ ] web-app-hermes
- [ ] web-app-homeassistant
- [ ] web-app-hugo
- [ ] web-app-jellyfin
- [ ] web-app-jenkins
- [ ] web-app-jitsi
- [ ] web-app-joomla
- [ ] web-app-keycloak
- [ ] web-app-kix
- [ ] web-app-lam
- [ ] web-app-listmonk
- [ ] web-app-litellm
- [ ] web-app-littlejs
- [ ] web-app-magento
- [ ] web-app-mastodon
- [ ] web-app-matomo
- [ ] web-app-matrix
- [ ] web-app-mattermost
- [ ] web-app-mediawiki
- [ ] web-app-mig
- [ ] web-app-mini-qr
- [ ] web-app-mobilizon
- [ ] web-app-moodle
- [ ] web-app-n8n
- [ ] web-app-nextcloud
- [ ] web-app-odoo
- [ ] web-app-openbao
- [ ] web-app-openclaw
- [ ] web-app-opencloud
- [ ] web-app-openproject
- [ ] web-app-opentalk
- [ ] web-app-openwebui
- [ ] web-app-peertube
- [ ] web-app-penpot
- [ ] web-app-pgadmin
- [ ] web-app-phpmyadmin
- [ ] web-app-pihole
- [ ] web-app-pixelfed
- [ ] web-app-postmarks
- [ ] web-app-pretix
- [ ] web-app-prometheus
- [ ] web-app-roulette-wheel
- [ ] web-app-seaweedfs
- [ ] web-app-semaphore
- [ ] web-app-shopware
- [ ] web-app-snipe-it
- [ ] web-app-socialhome
- [ ] web-app-sphinx
- [ ] web-app-stalwart
- [ ] web-app-suitecrm
- [ ] web-app-taiga
- [ ] web-app-wordpress
- [ ] web-app-xwiki
- [ ] web-app-yourls
- [ ] web-app-zammad
- [ ] web-svc-collabora
- [ ] web-svc-html
- [ ] web-svc-legal
- [ ] web-svc-libretranslate
- [ ] web-svc-logout
- [ ] web-svc-onlyoffice

## Cross-linking

- Implementing PR: *to be linked*.

## See Also

- Role style files: [style.css.md](../contributing/artefact/files/role/style.css.md)
- Lifecycle envelope: [lifecycle.md](../contributing/design/role/services/lifecycle.md)
- Compose loop: [compose.md](../agents/action/iteration/compose.md)
