# Role lifecycle 🌱

This page enumerates the values the `meta/services.yml.<entity>.lifecycle` key MAY take and what each value commits the project to.
The on-disk shape of `lifecycle` itself is documented in [layout.md](layout.md); this page is the semantic counterpart.

For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../../../documentation.md).

## Overview 🗺️

A role's lifecycle value sits on a single linear axis from `planned` (no code yet) to `eol` (removed).
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
eol           (removed in the next release)
```

Outside this axis, [a separate `unsupported` tier](#the-unsupported-tier-) exists for roles the project ships but explicitly does NOT commit to test or maintain.

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

The role has been removed from `roles/`.
The `lifecycle: eol` value is documented for traceability in changelogs but a role with this value MUST NOT exist on disk at the same time the value is set; the value is a release-note marker, not a live state.

## The tested envelope 🧪

Stages `alpha`, `beta`, `rc`, `stable`, and `maintenance` form the **tested envelope**.
The matrix-deploy + Playwright pipeline (see [variants.md](../../variants.md) and [inventory.md](../../inventory.md)) MUST exercise every role tagged with one of these values.
A regression in any tested-envelope role blocks the merge that introduced it.

Stages outside the envelope (`planned`, `pre-alpha`, `deprecated`, `eol`) MAY skip the matrix-deploy gate.
CI MAY still exercise them on a best-effort basis but failures MUST NOT block unrelated work.

## The `unsupported` tier 🧷

Some roles ship for convenience or to demonstrate that a deployment shape is possible (proprietary products, demo apps, retired prototypes) but the project does NOT commit to maintaining or testing them.
Use the lifecycle value `unsupported` for those.

A role tagged `unsupported`:

- MUST clearly state in its `README.md` that the project does not maintain or test it and that operators use it at their own risk.
- SHOULD link to the upstream project / vendor for support.
- MUST NOT block any release. CI MAY skip its deploy matrix entry entirely.
- MAY be removed without a deprecation cycle.

`unsupported` sits OFF the linear lifecycle axis above.
It is not a stage a role passes through; it is a parallel track for roles that never claim project-grade support.
Examples at the time of writing include `web-app-confluence`, `web-app-jira`, `web-app-magento`, `web-app-roulette-wheel`.
Promotion from `unsupported` into the tested envelope is allowed but requires meeting the `alpha` criteria from scratch.

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
