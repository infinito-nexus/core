# 027 - Integration Matrix

Companion to [026-unified-addon-syntax.md](026-unified-addon-syntax.md): how a cross-role
integration is declared, where its truth lives, and which ones are still open.

This page replaces the generated role×role grid that used to live here. The grid listed every
pair of `web-app-*` and `web-svc-*` entity names, which grows with the square of the role
count, and it was only refreshed when somebody ran its generator by hand. Nothing compared it
against the repository, so it drifted silently: at the point of removal its hardcoded axes were
missing fourteen roles, carried one role that no longer existed, and therefore dropped 84 of the
574 integration edges the repository actually declares.

## Where the truth lives

An integration has exactly two possible homes, and both are machine-readable.

**A service flag in the row role's `meta/services.yml`.** The infinito-native integrations are
plain service keys — `sso` (keycloak), `matomo`, `prometheus`, `email` (mailu), `dashboard`,
`css`, `logout`, `cdn`, `coturn`, `collabora`, `onlyoffice`, `libretranslate` and `litellm`. Each
is group-gated, so the flag tells you both that the integration exists and when it is active.
`lookup('roles_with_service', '<key>')` answers "who consumes this" from the repository itself;
no second list needs to agree with it.

**An addon under the row role's `meta/addons/`.** Everything that needs an upstream plugin lives
there, with its `mechanism` and, for an in-repo partner, a `bridges:` entry resolving to the
service key it wires. The addon contract and its lints are requirement
[026](026-unified-addon-syntax.md).

A pair that appears in neither place has no integration. That is the whole state space, and it is
queryable — which is why a frozen copy of it was worth less than the query.

## Layers

| Layer | Meaning | Where it is declared |
|---|---|---|
| Wired | Active through an infinito-native service flag | `meta/services.yml` of the row role |
| Declared | Upstream plugin wired as an addon | `meta/addons/` of the row role |
| Open | A verified upstream plugin exists, nothing declares it | nowhere yet — this is the backlog |
| Paid | Integration exists only behind a commercial tier | nowhere; opt-in by the operator |
| None | No known integration between the two roles | nowhere |

Integrations are **directional**: the row role hosts the flag or the plugin. A bidirectional pair
such as `nextcloud` ↔ `openproject` is two declarations, one on each side.

Two classes need no declaration and are therefore never "open". Native ActivityPub federation
between the fediverse roles (`mastodon`, `peertube`, `pixelfed`, `funkwhale`, `mobilizon`,
`bookwyrm`, `socialhome`) works without a plugin. And `ldap`, `redis` and `mariadb` resolve to
`svc-db-*` roles, which are infrastructure rather than integration partners.

## Open work

The wired and declared layers are exhaustive by construction — they are read from the
repository. The open layer is not: it grows as each role's upstream plugin ecosystem is
surveyed. A MediaWiki survey, for example, surfaced `DiscourseSsoConsumer`, `PeerTubeEmbed`,
`MachineTranslation` (libretranslate), `Extension:AWS` (minio) and an LLM editor (openwebui) —
five integrations that no list had carried before someone looked.

## Skipped Integrations

A deliberately skipped integration is recorded as a disabled `meta/addons/<id>.yml` entry with a `skipped:` reason, which a lint checks.

## Acceptance Criteria

- [ ] Every `web-app-*` role, not only the integration hubs, has had its upstream plugin ecosystem surveyed once, so the open and paid layers are exhaustive rather than hub-biased. Each survey records, per partner role, the real upstream plugin or its documented absence with a source URL, the MediaWiki survey being the template for depth, and each integration found is either declared under `meta/addons/` or recorded as skipped per [Skipped Integrations](#skipped-integrations).
- [x] A reader can answer "does role A integrate role B" from the repository alone, without
      consulting a generated page.
- [ ] Every open edge is wired: the row role declares an addon in its `meta/addons/` that integrates the column role, with `mechanism` set appropriately and, when the column role is an in-repo role, a `bridges:` entry resolving to the row role's `meta/services.yml` service for that target.
- [x] Each wired integration addon is either `required: false` and disabled by default, or `required: true` with an `enabled` gated on the bridged partner's `services.<target>.enabled` flag, so an integration never activates when its partner role is not deployed. ([test_addons_partner_gate.py](../../tests/lint/ansible/services/test_addons_partner_gate.py) requires every bridged addon that is required or enabled by default to name `services.<target>.enabled` for each bridge, `or`-joined when any one partner suffices; an optional addon gated on another key fails the same way. One reasoned exemption: Discourse `discourse-activity-pub` federates with every fediverse server, Mastodon being one partner of many.)
- [x] Paid edges are opt-in: they are declared in `meta/addons/` but remain disabled, and the role README documents the required commercial tier; they are not enabled by default and do not block this requirement. ([test_addons_paid_tier.py](../../tests/lint/ansible/services/test_addons_paid_tier.py) holds every addon whose `config.tier` or `config.*_tier` names `paid` or `enterprise` to `enabled: false`, `required: false` and a README line naming the addon and the tier.)
- [x] Where an edge links to an already-wired plugin (e.g. Nextcloud↔Collabora/BBB, WordPress↔Discourse), the migration reconciles the existing wiring with the declaration instead of duplicating it. ([richdocuments.yml](../../roles/web-app-nextcloud/meta/addons/richdocuments.yml), [bbb.yml](../../roles/web-app-nextcloud/meta/addons/bbb.yml) and [wp-discourse.yml](../../roles/web-app-wordpress/meta/addons/wp-discourse.yml) carry the existing plugin configuration and bridge `collabora`, `bigbluebutton` and `discourse`; the Collabora task runs only from the addon hook `roles/web-app-nextcloud/tasks/addons/richdocuments.yml`, and WordPress reads its Discourse settings from `addons.wp-discourse.config` in `roles/web-app-wordpress/vars/main.yml`; [test_addons_bridges.py](../../tests/lint/ansible/services/test_addons_bridges.py) resolves every bridge to a service block of the same role.)
- [ ] Each newly wired integration with a user-facing surface ships a Playwright spec (per Confirmed Decision 11 of [026](026-unified-addon-syntax.md)) proving the two roles are actually connected when both are deployed.
- [x] SSO-to-`keycloak` edges already satisfied centrally by the `sso` service (requirement 021) are marked as such and are not re-implemented as duplicate per-role OIDC addons. ([integrations.py](../../roles/web-app-docs/files/python/infinito_docs/generators/integrations.py) marks every `sso` edge `(central SSO)` on the service and add-on pages; [test_addons_sso_central.py](../../tests/lint/ansible/services/test_addons_sso_central.py) fails an addon that bridges `keycloak`, `oidc`, `openid` or `saml` instead of `sso`.)
