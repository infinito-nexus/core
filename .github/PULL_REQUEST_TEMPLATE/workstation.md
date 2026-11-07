# Workstation Pull Request

## Summary

Briefly describe the `dsk-*` change and the user workflow it affects.

Examples:

- Add a new desktop application role
- Fix broken workstation setup, launch, or package behavior
- Improve package setup for an existing workstation role
- Extend desktop integration, shell tooling, or user defaults

## Change Type

Intent:

- [ ] **Feature** - Adds or extends workstation functionality
- [ ] **Fix** - Repairs broken or incorrect workstation behavior

Semantic version impact:

- [ ] **Major** - Breaking change
- [ ] **Minor** - New backwards-compatible feature
- [ ] **Patch** - Small improvement or compatible adjustment

## Affected Roles and Platforms

- Primary `dsk-*` role(s):
- Related `dev-*`, `drv-*`, `user-*`, or `sys-*` role(s):
- Distro(s) and desktop environment(s) tested:

## Roles (optional `🧩 Subset` CI scope)

Read only when a maintainer applies the **🧩 Subset** label: CI then deploys exactly these roles instead of the diff-derived set, and each MUST be an existing `roles/<id>` directory. See [pipeline.md](../../docs/contributing/artefact/git/pipeline.md#subset-label-).

```yaml
roles:
  # - dsk-firefox
  # - sys-version
```

## Change Details

Explain what changed and why, covering:

- What user problem does this solve?
- Which package, package source, or integration was added or changed?
- How does this behave on the tested distro(s)?
- Which alternatives were considered?

## Validation

- [ ] Installation tested
- [ ] Application startup tested
- [ ] Basic workflow tested
- [ ] Screenshot attached for user-visible changes
- [ ] The Definition of Done and [CONTRIBUTING.md](../../CONTRIBUTING.md) were applied

### Test Evidence

List the commands that were run and their results.

## Security Impact

- [ ] No relevant security impact
- [ ] Security impact present

If security impact is present, explain:

- Affected permissions, package trust, secrets, or exposed surfaces:
- Risk reduction, new exposure, or compatibility considerations:
- Security-specific validation performed:

## Review Focus

- Highest-risk files, roles, or flows:
- Distro-specific or packaging concerns:
- Specific feedback requested from reviewers:

## Additional Notes

Add any reviewer context for packages, distro-specific behavior, or follow-up work.
