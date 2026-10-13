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
9. **Branch and stack.** One branch `feature/designer` and one draft PR, opened once the base is approved. Exactly one compose stack runs at a time. Base changes land as base commits on the same branch. Role changes stay under `roles/<role>/` and are committed per role after approval.
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
- [ ] A role with `design` disabled and `javascript` enabled receives its functional script and no injected CSS or design script. Open: no deploy of such a role is on record.
- [ ] A minimal deploy with `disable=design` injects neither the shared CSS nor a design script. Open: no minimal deploy with `disable=design` is on record.
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
- [ ] `web-app-decidim` and `web-app-socialhome` honour an inventory title override. Open: no deploy with an inventory title override is on record, and Socialhome takes the title on its first boot only (`roles/web-app-socialhome/TODO.md`).
- [x] The base gallery on `web-app-dashboard`, `web-app-gitea` and `web-app-nextcloud` is approved by the operator.
- [ ] The draft PR from `feature/designer` is open and linked below. Open: by operator decision `feature/designer` reaches `main` through the draft PR of `feature/store-i18n` instead of a PR of its own; the merge of `feature/designer` into `feature/store-i18n` is in progress.

### Roles

A role is checked when its frontend and, where present, its backend are styled, its CSS and JS use only `--design-*` tokens, its logo and title are set through the app's own mechanism in the slot format, its Playwright spec covers frontend and backend and asserts token colors, contrast of core elements, light and dark mode, the native toggle where one exists, and the visible logo and title, `make quality-high` and the minimal compose deploy are green, its gallery is approved and linked under "Further Resources" in the role README, and the change is committed.

Two base commits changed many roles after their last run: `6c2de017f8` split vendor selector lists in role stylesheets, so rules Chromium used to drop now apply, and `63f3631567` changed the colors of the generated logo lockups. Merges of `main` also bumped app images after some runs. A role whose open reason is only such a later change needs one more green run of its complete spec on its final state.

- [ ] web-app-akaunting: title not set from the design (company name stays literal) and not asserted; `style.css.j2` changed by `6c2de017f8` after the last run.
- [ ] web-app-baserow: literal RGB fallback at `style.css.j2:1918`; title neither set nor asserted against the configured value.
- [ ] web-app-bigbluebutton: title not set through Greenlight (the spec asserts the literal upstream name); the meeting client keeps the upstream design; `vars/main.yml` rewritten after the last full run.
- [ ] web-app-bluesky: title never set; the spec compares it with the upstream default.
- [ ] web-app-bookwyrm: no green complete run on the final state; the last one failed the SeaweedFS avatar upload test.
- [ ] web-app-checkmk: `theme.css.j2` changed by `6c2de017f8` after the last run.
- [x] web-app-chess
- [x] web-app-dashboard
- [ ] web-app-decidim: `style.css.j2` changed by `6c2de017f8` after the last run.
- [x] web-app-discourse
- [ ] web-app-erpnext: visible title not asserted (only the raw `/desk` HTML); logo lockup changed by `63f3631567` after the last run.
- [ ] web-app-espocrm: the Administration is captured by the gallery only, no assertion runs on it.
- [ ] web-app-fediwall: literal colors in `templates/index.html.j2:18-27`; title not set through the wall config's native title.
- [ ] web-app-fider: the logo does not reach Fider while the object store is enabled.
- [ ] web-app-flowise: `env.j2`, `playwright.env.j2` and `tasks/utils/mcp.yml` changed after the last green run.
- [ ] web-app-friendica: frontend and backend gaps recorded in the gallery remain; the `/admin` pages get a visibility check only.
- [ ] web-app-funkwhale: the Django admin is not covered; `/manage` has no contrast or mode assertion; the native switch is set through `localStorage` only; the loader keeps upstream colors.
- [ ] web-app-fusiondirectory: title neither set nor asserted.
- [ ] web-app-gitea: visible logo not asserted, only the bytes of the served file.
- [ ] web-app-gitlab: final state never ran (the design-only commit removed the administrator provisioning); `/admin` is checked for HTTP 200 only.
- [x] web-app-hermes
- [ ] web-app-homeassistant: `vars/main.yml` changed after the last role sync that deployed the role.
- [ ] web-app-hugo: logo and title applied by `design.js` and CSS instead of Hugo's own build.
- [ ] web-app-jellyfin: final state never ran (`branding.css.j2` split by `6c2de017f8`, spec and administrator password changed).
- [ ] web-app-jenkins: `test-design.js` restored after the last complete run; no run on the restored file.
- [ ] web-app-jitsi: `style.css.j2` changed twice after the last green run.
- [ ] web-app-joomla: the backend editor (TinyMCE 7) keeps its upstream design; the `admin-login` lockup changed by `63f3631567` after the last run.
- [ ] web-app-keycloak: `tasks/utils/theme.yml` (`63f3631567`) and the image bump to 26.8.1 came after the last run; literal color fallbacks in `logout-panel.js` and `javascript.js.j2`.
- [ ] web-app-kix: `test-design.js` changed after the last green run.
- [ ] web-app-lam: title neither set nor asserted; spec and `playwright.env.j2` rewritten after the last run.
- [ ] web-app-listmonk: administrator tasks, env, SQL and spec rewritten after the last run.
- [ ] web-app-litellm: logo swapped by CSS `content` instead of LiteLLM's `logo_url` setting.
- [ ] web-app-littlejs: title appended by `design.js` instead of the launcher template, which keeps a literal title.
- [ ] web-app-magento: literal `darkgrey` at `style.css.j2:5513` and `:5554`; `style.css.j2` changed by `6c2de017f8` after the last run.
- [ ] web-app-mastodon: switch to the platform administrator not deployed.
- [ ] web-app-matomo: Matomo's own `themeMode` preference is not exercised (the spec flips the DOM); the administration is not asserted.
- [ ] web-app-matrix: `vars/main.yml` rewritten after the last complete run.
- [ ] web-app-mattermost: about 50 literal RGB fallbacks inside `var()` in `style.css.j2`; `style.css.j2` changed by `6c2de017f8` after the last run.
- [ ] web-app-mediawiki: switch to the platform administrator not deployed.
- [ ] web-app-mini-qr: the scanner view keeps upstream colors; the PWA manifest keeps the upstream name and theme color.
- [ ] web-app-mobilizon: literal colors at `style.css.j2:1373`, `:1631` and `:2316`; switch to the platform administrator not deployed.
- [ ] web-app-moodle: `test-design.js` rewritten after the last complete run; page-slot lockup changed by `63f3631567`.
- [ ] web-app-n8n: image bump to 2.44.0 and provisioning rewrite from `main` came after the last complete run.
- [ ] web-app-nextcloud: Nextcloud's theme picker and the admin settings are not asserted, the visible logo is not checked; final state never ran.
- [ ] web-app-odoo: literal colors in `files/theme/backend.css` and `frontend.css`, among them the invalid focus ring `box-shadow` at `backend.css:2203`; final state not exercised.
- [x] web-app-openbao
- [ ] web-app-openclaw: `test-design.js` rewritten after the last complete run.
- [ ] web-app-opencloud: `tasks/main.yml` restructured after the last deploy with design on.
- [x] web-app-openproject
- [ ] web-app-opentalk: the conference room is not covered; the native theme setting is half exercised; the title check cannot fail; logo lockup changed by `63f3631567`.
- [ ] web-app-openwebui: logo and title switched off (license clause, operator decision open); switch to the platform administrator not deployed.
- [ ] web-app-peertube: `tasks/design/apply.yml` rewritten after the last green run.
- [ ] web-app-penpot: images bumped by `main` after the last run.
- [ ] web-app-pgadmin: switch to the platform administrator not deployed.
- [ ] web-app-phpmyadmin: literal named colors in `templates/theme/design.css.j2`; phpMyAdmin's theme chooser is not exercised.
- [ ] web-app-pihole: a test was added after the last complete run; Pi-hole's own theme setting is only simulated.
- [ ] web-app-pixelfed: literal SVG colors in `style.css.j2`; final state not exercised.
- [ ] web-app-postmarks: title written by `design.js` although Postmarks has `site_name`; the `/admin` pages are not asserted; the title check cannot fail.
- [ ] web-app-pretix: administrator and stylesheet rework not deployed.
- [ ] web-app-prometheus: merges of `main` changed spec, services, volumes and tasks after the last run; literal colors in the logout button of `javascript.js.j2`.
- [ ] web-app-roulette-wheel: the wheel labels stay below AA on dark segments in dark mode, and no test asserts their contrast.
- [x] web-app-seaweedfs
- [ ] web-app-semaphore: the admin users page is not asserted; code backgrounds keep Vuetify's tint.
- [ ] web-app-shopware: literal colors (`gold`, SVG fills) in `style.css.j2`; `style.css.j2` changed by `6c2de017f8` after the last run.
- [ ] web-app-snipe-it: the complete spec never ran green on the final `test-design.js`.
- [ ] web-app-socialhome: image bump to 2026.10.11 from `main` came after the last run.
- [ ] web-app-sphinx: title neither set nor asserted.
- [ ] web-app-stalwart: `style.css.j2` changed by `6c2de017f8` and the image bump to v0.16.26 came after the last run.
- [ ] web-app-suitecrm: visible title not asserted; literal SVG fills in `files/style.css`; the session rework from `main` never ran with the design.
- [ ] web-app-taiga: title neither set nor asserted; `meta/volumes.yml` changed after the last green run.
- [ ] web-app-wordpress: literal RGB fallbacks in `admin.css` and `extras.css`; the stylesheets changed by `6c2de017f8` after the last run.
- [x] web-app-xwiki
- [ ] web-app-yourls: switch to the platform administrator not deployed.
- [ ] web-app-zammad: switch to the platform administrator and the move of the watermark defaults not deployed.
- [ ] web-svc-html: logo neither set nor asserted; the title test checks another role's page.
- [ ] web-svc-libretranslate: literal colors (`gold`, SVG fill) in `style.css.j2`.
- [x] web-svc-logout

## Cross-linking

- Implementing PR: [#625](https://github.com/infinito-nexus/core/pull/625), the draft PR of `feature/store-i18n`, which carries `feature/designer` to `main`.

## See Also

- Role style files: [style.css.md](../contributing/artefact/files/role/style.css.md)
- Lifecycle envelope: [lifecycle.md](../contributing/design/role/services/lifecycle.md)
- Compose loop: [compose.md](../agents/action/iteration/compose.md)
