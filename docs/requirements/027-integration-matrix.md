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

## Acceptance Criteria

- [ ] Every `web-app-*` role has had its upstream plugin ecosystem surveyed once, and each
      integration found is either declared under `meta/addons/` or recorded as deliberately
      skipped with a reason.
- [ ] A reader can answer "does role A integrate role B" from the repository alone, without
      consulting a generated page.
