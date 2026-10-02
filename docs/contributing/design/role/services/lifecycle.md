# Role lifecycle 🌱

This page enumerates the values the `meta/services.yml.<entity>.lifecycle` key MAY take and what each value commits the project to.
The on-disk shape of `lifecycle` itself is documented in [layout.md](layout.md); this page is the semantic counterpart.

For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../../../documentation.md).

## Overview 🗺️

A role's lifecycle value sits on a single linear axis from `planned` (no code yet) to `eol` (end of life).
A subset of stages is the **tested** envelope: roles in those stages MUST be exercised by the project's automated test suite on every change, and a failing test blocks the release.
Stages outside that envelope MAY ship without automated coverage.

```
planned       (no code yet)
pre-alpha     (early scaffolding, not yet stable enough to test)
┌─ alpha       ─┐
│  beta         │   ← TESTED ENVELOPE (CI gates apply)
│  rc           │
│  stable       │
└─ maintenance ─┘
deprecated    (kept for compatibility, do not adopt for new deploys)
eol           (end of life: shipped but not tested or maintained)
```

## Stages 📋

Each stage entry below lists the criteria a role MUST satisfy to claim that stage.
Promotion to the next stage is a deliberate human decision, not an automated transition.
A role MAY only be tagged with a stage whose criteria are fully met; any drift MUST be corrected by either fixing the role or demoting the lifecycle key to the highest stage whose criteria still hold.

### planned 🛣️

The role does not exist on disk yet (or only as a placeholder `meta/services.yml`).
It is listed in this state so that contributors can discover what the project intends to ship next.

A role tagged `planned`:

- MUST appear in [docs/](../..) or in a referenced requirement so the intent is discoverable.
- MUST NOT have a working `tasks/` tree.
- MAY have stub `meta/` files.

### pre-alpha 🧪

Initial scaffolding exists but the role is too unstable to test.
Use this stage when the deploy can break in obvious ways and you do NOT want CI to treat that as a regression.

A role tagged `pre-alpha`:

- MUST have a `tasks/main.yml` and the minimum role-meta layout from [layout.md](layout.md).
- MAY ship without `templates/playwright.env.j2`.
- MUST NOT be added to any deploy matrix that gates a release.

### alpha 🐣

The role deploys end-to-end on the project's reference distribution and is covered by **at least** a smoke-level Playwright spec, but neither the deploy nor the spec depth is considered production-grade.

A role tagged `alpha`:

- MUST deploy cleanly via `make compose-deploy mode=reinstall` against the reference distribution.
- MUST ship `templates/playwright.env.j2` and `files/playwright/playwright.spec.js`, with at least one assertion that covers the role's canonical landing surface.
- MUST be exercised by the matrix-deploy on every push.
- MAY have known minor issues documented in its `README.md` or in an open issue.

### beta 🌿

The role is functionally complete for the documented contract.
The minimum bar today is:

- All `alpha` criteria.
- The role's documented integrations (OIDC, RBAC, email, dashboard, service-gating, etc., as applicable) are exercised end-to-end by its Playwright spec or by a peer role's spec when the integration is cross-role.
- Single sign-on is wired in by default whenever the upstream software supports it: the role MUST configure OIDC against [web-app-keycloak](../../../../../roles/web-app-keycloak/) when an OIDC client adapter exists upstream, and MUST configure LDAP against [svc-db-openldap](../../../../../roles/svc-db-openldap/) when an LDAP adapter exists upstream. If a role offers both, it MUST default to OIDC and MAY expose LDAP behind a service flag. Roles whose upstream ships neither MUST document the exception in their `README.md`.
- The role does NOT carry "known broken" warnings in its `README.md`.

### rc 🚦

Release candidate.
The role meets every `beta` criterion AND has gone through at least one full `full_cycle=true` matrix run plus an external review pass without regression.
This stage exists so a role can be flagged "we intend to call this stable in the next release" without committing to it yet.

A role tagged `rc`:

- MUST be deployed on the public [infinito.nexus](https://infinito.nexus/) production instance and serving real traffic. The [infinito.nexus](https://infinito.nexus/) deploy is the project's burn-in environment for release-candidate roles; coverage gaps that only surface against real users get caught here before the role graduates to `stable`.

### stable 🟢

Production-grade.
The role meets every `rc` criterion AND has shipped in at least one tagged release without a hot-fix to its own `tasks/`, `templates/`, or `files/` tree.

### maintenance 🛠️

The role is feature-frozen.
Bug fixes and security patches still land, but new features go to a successor role or behind a feature flag.
Same test coverage as `stable`.

### deprecated ⚠️

The role still ships and still passes its tests, but operators MUST migrate away from it.

A `deprecated` role:

- MUST be tagged with a "Deprecated" banner in its `README.md` pointing at the successor.
- MUST keep working until removed (the test suite still covers it).
- SHOULD be removed within a small number of releases.

### eol 🪦

The role has reached end of life: it still ships in `roles/` for now but the project does NOT commit to testing or maintaining it (retired prototypes, proprietary products, superseded apps).

A role tagged `eol`:

- MUST clearly state in its `README.md` that the project does not maintain or test it and that operators use it at their own risk. The banner is a single blockquote line, the first non-blank line under the H1, opening with `> **End of life.**` and carrying both the `neither maintains nor tests` and the `at your own risk` wording. `test_eol_readme_banner.py` enforces exactly those three things: the position, the opening, and both clauses.
- SHOULD link to the upstream project / vendor for support. The link is not mechanical and `test_eol_readme_banner.py` does not check it.
- MUST store `enabled: false` as a literal on its own primary entity in `meta/services.yml`. A `"{{ '<role>' in group_names }}"` flag turns true the moment the role joins an inventory. `shared` stays at the value the role needs, normally `true`: it is what registers the entity in the service registry, and that registration is what makes `disable=<role-id>` resolve to the service key at all and what keeps the role in the `sys-service-loader` preload order. The literal forces two collateral suppressions, and a demotion that skips them hits two unrelated red lints: the own primary's key needs `# nocheck: playwright-service-flag` on the line above it, because a service stored off carries no `<NAME>_SERVICE_ENABLED=` line in `templates/playwright.env.j2`, and every consumer's literal flag needs `# nocheck: dynamic-flag` on its own line (or one marker in the comment block above the key, which covers both flags at once), because a literal where the dynamic form is the house shape is precisely what `dynamic-flag` reports.
- MUST NOT be pinned truthy by any variant in any `meta/variants.yml`, its own included, neither under `services:` nor under `addons:`. A variant pin re-enables the role for that round alone, which is the one place where neither the banner nor the stored flag is in view.
- MUST NOT be enabled as a dependency of a role that is not itself EOL: no `meta/services.yml` block, no variant pin, and no `meta/addons/*.yml` whose `bridges:` list names it. One EOL role MAY name another, because both leave together. The `eol-dependency` rule enforces all three, and `INFINITO_LIFECYCLES` is why: the envelope drops an EOL role from every CI round under the default envelope, so the dependency binds a partner no test deploys and first surfaces on a production host as an unreachable integration. An explicit `lifecycles: eol` workflow dispatch deploys the role standalone, and the literal flags keep every partner unbound even in that round.
- MUST NOT block any release. CI MAY skip its deploy matrix entry entirely.
- MAY be removed without a deprecation cycle.

An addon that stays in the tree while its partner is EOL gates on exactly `{{ lookup('config', '<own-role>', 'services.<eol-key>.enabled') | bool }}`, which the stored literal holds at `false`; the rule matches that expression anchored over the whole value, accepting either quote character and whitespace after `lookup(` and around its commas, because a gate that merely mentions the lookup can still render true. An addon reaching an external SaaS provider through `lookup('api_enabled', …)` declares no `bridges:` and is not a dependency on the in-repo role at all.

The generated integration matrix (`roles/web-app-docs/files/python/infinito_docs/generators/integrations.py`) reads this `lifecycle` value and marks every edge whose target is `eol` with `(end of life)` on all three of its pages, so a declared integration with a dead partner does not read as a live one.

## The tested envelope 🧪

Stages `alpha`, `beta`, `rc`, `stable`, and `maintenance` form the **tested envelope**.
The matrix-deploy + Playwright pipeline (see [variants.md](../../variants.md) and [inventory.md](../../inventory.md)) MUST exercise every role tagged with one of these values.
A regression in any tested-envelope role blocks the merge that introduced it.

Stages outside the envelope (`planned`, `pre-alpha`, `deprecated`, `eol`) MAY skip the matrix-deploy gate.
CI MAY still exercise them on a best-effort basis but failures MUST NOT block unrelated work.

Promotion from `eol` back into the tested envelope is allowed but requires meeting the `alpha` criteria from scratch.
Promoting also reverses the storage steps, in this order: change `lifecycle`, set the primary entity's `enabled` and `shared` to the values the role needs, restore the `bond` the primary carried before (`test_disabled_service_bond` is what required dropping it, because the resource model never reads a key on an entry stored off, so the number described a cost nobody paid), restore the consumer flags from their literal `false` to the dynamic form and drop the `# nocheck: dynamic-flag` markers that literal needed, re-add the variant pins the EOL ban removed, then re-run the matrix-deploy.
The consumer blocks themselves were never removed, only pinned off, so there is nothing to re-create; the step is the flag value and its marker.
Taking the `lifecycle` value off `eol` without the flags leaves the role in the envelope and off on every host, and the deploy matrix picks up a role no inventory enables.
Demoting to `eol` runs the same list the other way round: set the primary's `enabled` to a literal `false` and add `# nocheck: playwright-service-flag` above its key, drop the primary's `bond` in the same edit because `test_disabled_service_bond` rejects a weight on an entry stored off, pin every consumer flag to a literal `false` with `# nocheck: dynamic-flag`, remove the variant pins, and add the README banner.
The storage delta on a demoted primary is therefore not the flag alone, and it differs per role: `web-app-minio` went from `enabled: true` to `enabled: false` and lost its `bond: 1` (`test_disabled_service_bond`), `web-app-jira` and `web-app-confluence` gained both a stored `enabled: false` and `shared: true` where their primary declared neither before, and `web-app-phpldapadmin` gained the stored `enabled: false` on its own.
Examples of `eol` roles at the time of writing include `web-app-confluence`, `web-app-jira`, `web-app-minio`, `web-app-phpldapadmin`.

## Setting the value ✏️

Set `lifecycle` on the role's primary entity in `meta/services.yml`.
The exact placement and multi-entity rule live in [layout.md](layout.md#run_after-and-lifecycle-).

```yaml
# roles/web-app-<role>/meta/services.yml
<primary_entity>:
  image: ...
  lifecycle: beta
```

Any value not listed on this page MUST be treated as a typo and rejected by review.
Do NOT introduce new values without amending this page first.
