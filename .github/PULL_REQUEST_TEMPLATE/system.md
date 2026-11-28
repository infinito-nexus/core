# System Pull Request

## Summary

Briefly describe the system-level change.

Examples:

- Add a new `sys-*`, `svc-*`, `dev-*`, `drv-*`, `pkgmgr`, `update-*`, or `user-*` capability
- Fix broken shared infrastructure, package, service, or automation behavior
- Extend a shared service, package, timer, or maintenance workflow
- Introduce a new infrastructure, shared abstraction, or automation building block

## Change Type

Intent:

- [ ] **Feature** - Adds or extends shared system functionality
- [ ] **Fix** - Repairs broken or incorrect shared system behavior

Semantic version impact:

- [ ] **Major** - Breaking change
- [ ] **Minor** - New backwards-compatible feature
- [ ] **Patch** - Small improvement or compatible adjustment

## Affected Components

- Primary role(s) or module(s):
- Related services, timers, packages, inventories, or workflows:
- Distro(s) tested:

## Roles (optional `🧩 Subset` CI scope)

Read only when a maintainer applies the **🧩 Subset** label: CI then deploys exactly these roles instead of the diff-derived set, and each MUST be an existing `roles/<id>` directory. See [pipeline.md](../../docs/contributing/artefact/git/pipeline.md#subset-label-).

```yaml
roles:
  # - sys-version
  # - svc-db-postgres
```

## Change Details

Explain what changed and why, covering:

- What capability was introduced?
- How does this integrate with the existing stack?
- Were variables, defaults, and shared logic kept DRY?
- Are there architecture, migration, or compatibility implications?
- Which alternatives were considered?

## Validation

- [ ] Fresh deploy or targeted rerun tested
- [ ] Idempotency verified
- [ ] Service health, timers, or package behavior verified
- [ ] Cross-distro notes documented
- [ ] The Definition of Done and [CONTRIBUTING.md](../../CONTRIBUTING.md) were applied

### Test Evidence

List the commands that were run and their results.

## Security Impact

- [ ] No relevant security impact
- [ ] Security impact present

If security impact is present, explain:

- Affected auth, TLS, permissions, secrets, services, or exposed surfaces:
- Risk reduction, new exposure, migration, or compatibility considerations:
- Security-specific validation performed:

## Review Focus

- Highest-risk files, roles, or flows:
- Idempotency, compatibility, or rollout concerns:
- Specific feedback requested from reviewers:

## Additional Notes

Add any reviewer context for rollout, compatibility, or operational follow-up.
