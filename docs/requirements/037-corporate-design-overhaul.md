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
8. **Logo generator.** An SVG template renders the lockup, Pillow rasterises PNG and ICO variants. The variant is computed from the target slot format: square slot shows the logo only, wide slot shows logo and title, very wide or two-line slot adds the domain, text-only slot shows the title only. The background stays transparent. The text uses palette colors with an outline so it stands out on light and dark surfaces; the SVG of a slot on a page or panel switches to the dark palette colors under `prefers-color-scheme: dark`. A slot declared with `frame: true` sits on brand-colored chrome and takes the frame text color with a frame-colored outline.
9. **Branch and stack.** One branch `feature/designer`. It has no draft PR of its own: it reaches `main` through the draft PR of `feature/store-i18n`, which merges it round by round (changed by operator decision on 2026-10-13 and recorded in that PR). Exactly one compose stack runs at a time. Base changes land as base commits on the same branch. Role changes stay under `roles/<role>/` and are committed per role after approval.
10. **Verification.** Every change passes `make quality-high` and a minimal compose deploy against the running stack: `make compose-deploy apps=<role> variant=0 disable=<every disableable service except design>` (default `initialize` mode, no teardown, single pass, no `full_cycle`). CSS and branding iterations run without a redeploy through `make design-sync app=<role> variant=0` (re-renders shared CSS, role `style.css` and the generated logo assets). A changed `design.js`, task, template or `meta/` file runs through `make compose-role-sync role=<role> variant=0`, which re-runs only the app role against the running stack and renders the CSP hash in the vhost with it. A role pass runs `make test` and the lint targets of the file types it touched after its last edit, and closes with a role sync and the complete role spec; a pass that changed provisioning runs that role sync twice, and the second run reports no change for the tasks it added. `make quality-high` runs once per two or three role passes, at every merge of the main branch and before a role is committed. Each role is also asserted with one further base color, blue `#001f3f`, through `base=` on the sync targets. Swarm verification is out of scope.
11. **Review gallery.** Each role gets its own private Artifact with at least 20 views, each captured in light and dark mode and in a desktop (1440×900) and a mobile (390×844) viewport, so at least 80 screenshots of the designed state per role. The views favour detail-rich surfaces: settings, administration, forms, lists and detail pages, logged in where the app has accounts, with idempotently seeded showcase content where a list or detail page would otherwise be empty. `make design-gallery app=<role>` captures them in one spec run and copies them to `/tmp/design-gallery/<role>/`. A comparison with the app before the design is captured on request only: `before=true` adds every view with every injected snippet stripped from the document (the body filter wraps its injections in `<!--infinito-inj-->` markers). The operator approves or rejects by comment.
12. **Frontend and backend.** Every role is styled and tested on its frontend and, where the app has one, on its separate backend (admin surface such as `wp-admin`, the Shopware or Magento admin, the Joomla administrator). A role with a backend shows backend views in its gallery in addition to the frontend views, and its Playwright spec covers both surfaces.
13. **Scope.** In-scope roles are invokable, carry a lifecycle inside the tested envelope (`alpha` to `maintenance`), and expose a web UI. A `web-app-` or `web-svc-` role without a UI to design sets `design.enabled: false` in its `meta/services.yml` with `# nocheck: design-off  Reason: <text>`, which a lint enforces, and `make design-queue` skips it: `web-app-bridgy-fed`, `web-app-mig` (operator decision), `web-svc-asset`, `web-svc-cdn`, `web-svc-collabora`, `web-svc-coturn`, `web-svc-file`, `web-svc-legal`, `web-svc-mirror`, `web-svc-onlyoffice`, `web-svc-simpleicons` and `web-svc-xmpp`.

## Acceptance Criteria

### Base

- [x] `roles/web-svc-css` no longer exists and `roles/web-svc-design` deploys and serves the shared CSS.
- [x] `group_vars/all/13_design.yml` no longer exists and the design configuration resolves from `roles/web-svc-design/meta/services.yml`, overridable per inventory.
- [x] No `roles/*/meta/services.yml` declares a `css:` key.
- [x] A role with `design` enabled, `javascript` disabled and a `templates/design.js.j2` receives the injected CSS and its design script, and no functional script.
- [x] A role with `design` disabled and `javascript` enabled receives its functional script and no injected CSS or design script.
- [x] A minimal deploy with `disable=design` injects neither the shared CSS nor a design script.
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
- [x] `web-app-decidim` and `web-app-socialhome` honour an inventory title override. Decidim renames an existing organization and Socialhome an existing household to an inventory title and back.
- [x] The base gallery on `web-app-dashboard`, `web-app-gitea` and `web-app-nextcloud` is approved by the operator.
- [ ] `feature/designer` reaches `main` through the draft PR of `feature/store-i18n` linked below, which merges it round by round. Open: the final designer state is not yet pushed into that PR.

### Roles

A role is checked when its frontend and, where present, its backend are styled, its CSS and JS use only `--design-*` tokens, its logo and title are set through the app's own mechanism in the slot format, its Playwright spec covers frontend and backend and asserts token colors, contrast of core elements, light and dark mode, the native toggle where one exists, and the visible logo and title, `make quality-high` and the minimal compose deploy are green, its gallery is approved and linked under "Further Resources" in the role README, and the change is committed.

Two base commits changed many roles after their last run: `6c2de017f8` split vendor selector lists in role stylesheets, so rules Chromium used to drop now apply, and `63f3631567` changed the colors of the generated logo lockups. Merges of `main` also bumped app images after some runs. A role whose open reason is only such a later change needs one more green run of its complete spec on its final state.

- [x] web-app-akaunting
- [x] web-app-baserow
- [x] web-app-bigbluebutton
- [x] web-app-bluesky
- [x] web-app-bookwyrm
- [x] web-app-checkmk
- [x] web-app-chess
- [x] web-app-dashboard
- [x] web-app-decidim
- [x] web-app-discourse
- [x] web-app-erpnext
- [x] web-app-espocrm
- [x] web-app-fediwall
- [x] web-app-fider
- [x] web-app-flowise
- [x] web-app-friendica
- [x] web-app-funkwhale
- [x] web-app-fusiondirectory
- [x] web-app-gitea
- [x] web-app-gitlab
- [x] web-app-hermes
- [x] web-app-homeassistant
- [x] web-app-hugo
- [x] web-app-jellyfin
- [x] web-app-jenkins
- [x] web-app-jitsi
- [x] web-app-joomla
- [x] web-app-keycloak
- [x] web-app-kix
- [x] web-app-lam
- [x] web-app-listmonk
- [x] web-app-litellm
- [x] web-app-littlejs
- [x] web-app-magento
- [x] web-app-mastodon
- [x] web-app-matomo
- [x] web-app-matrix
- [x] web-app-mattermost
- [x] web-app-mediawiki
- [x] web-app-mini-qr
- [x] web-app-mobilizon
- [x] web-app-moodle
- [x] web-app-n8n
- [x] web-app-nextcloud
- [x] web-app-odoo
- [x] web-app-openbao
- [x] web-app-openclaw
- [x] web-app-opencloud
- [x] web-app-openproject
- [x] web-app-opentalk
- [ ] web-app-openwebui: logo and title stay Open WebUI's own because clause 4 of its license allows replacing the branding only up to 50 users, with written permission or under an enterprise license (operator decision, see `roles/web-app-openwebui/TODO.md`).
- [x] web-app-peertube
- [x] web-app-penpot
- [x] web-app-pgadmin
- [x] web-app-phpmyadmin
- [x] web-app-pihole
- [x] web-app-pixelfed
- [ ] web-app-postmarks: the server HTML and the Atom feeds keep the title `Postmarks`, because Postmarks reads `site_name` only from `account.json`, which switches on fediverse mode; `design.js` sets the browser title (upstream option in `roles/web-app-postmarks/TODO.md`).
- [x] web-app-pretix
- [x] web-app-prometheus
- [x] web-app-roulette-wheel
- [x] web-app-seaweedfs
- [x] web-app-semaphore
- [x] web-app-shopware
- [x] web-app-snipe-it
- [x] web-app-socialhome
- [x] web-app-sphinx
- [ ] web-app-stalwart: handed over to `feature/store-i18n`. Under `sso` the web administration specs need its administrator group grant (`199f2a6d41`), which `feature/designer` does not carry, so `feature/store-i18n` ticks this item after a green run of the stalwart spec with `design`, `sso` and `email` on its merged state.
- [x] web-app-suitecrm
- [x] web-app-taiga
- [x] web-app-wordpress
- [x] web-app-xwiki
- [x] web-app-yourls
- [x] web-app-zammad
- [x] web-svc-html
- [x] web-svc-libretranslate
- [x] web-svc-logout

## Cross-linking

- Implementing PR: [#625](https://github.com/infinito-nexus/core/pull/625), the draft PR of `feature/store-i18n`, which carries `feature/designer` to `main`.

## See Also

- Role style files: [style.css.md](../contributing/artefact/files/role/style.css.md)
- Lifecycle envelope: [lifecycle.md](../contributing/design/role/services/lifecycle.md)
- Compose loop: [compose.md](../../agents/skills/i8-iterate-compose/SKILL.md)
