## Summary

Briefly describe the `desk-*` change and the user workflow it affects.

Examples:

* Add a new desktop application role
* Fix broken workstation setup, launch, or package behavior
* Improve package setup for an existing workstation role
* Extend desktop integration, shell tooling, or user defaults

---

## Template Type

Select the primary intent of this PR:

* [ ] **Feature** - Adds or extends workstation functionality
* [ ] **Fix** - Repairs broken or incorrect workstation behavior

---

## Affected Roles and Platforms

List the impacted roles and workstation context.

* Primary `desk-*` role(s):
* Related `dev-*`, `drv-*`, `user-*`, or `sys-*` role(s):
* Distro(s) and desktop environment(s) tested:

---

## Roles (optional `🧩 Subset` CI scope)

Optional. Ignored unless a maintainer applies the **🧩 Subset** label; without the label CI uses the diff-derived role set as usual. When the label is set, CI deploys **only** the roles listed here — each must be an existing `roles/<id>` directory, or the run fails. See [pipeline.md](../../docs/contributing/artefact/git/pipeline.md#subset-label-).

```yaml
roles:
  # - desk-firefox
  # - sys-version
```

---

## Change Type

Select the semantic version impact of this change:

* [ ] **Major** - Breaking change
* [ ] **Minor** - New backwards-compatible feature
* [ ] **Patch** - Small improvement or compatible adjustment

---

## Change Details

Explain what changed and why.

Key points:

* What user problem does this solve?
* Which package, package source, or integration was added or changed?
* How does this behave on the tested distro(s)?
* Which alternatives were considered?

---

## Local Validation

Describe how the change was validated locally.

* [ ] Installation tested
* [ ] Application startup tested
* [ ] Basic workflow tested
* [ ] Screenshot attached for user-visible changes

---

## Security Impact

Indicate whether this change has security implications.

* [ ] No relevant security impact
* [ ] Security impact present

If security impact is present, explain:

* Affected permissions, package trust, secrets, or exposed surfaces:
* Risk reduction, new exposure, or compatibility considerations:
* Security-specific validation performed:

---

## Review Focus

Help reviewers focus on the riskiest parts of this PR.
For repository-wide contribution and review expectations, see [CONTRIBUTING.md](../../CONTRIBUTING.md).

* Highest-risk files, roles, or flows:
* Distro-specific or packaging concerns:
* Specific feedback requested from reviewers:

---

## Definition of Done (DoD)

* [ ] The implementation follows the Definition of Done, and the contribution guidelines in [CONTRIBUTING.md](../../CONTRIBUTING.md) were considered and applied during implementation.

---

## Additional Notes

Add any reviewer context for packages, distro-specific behavior, or follow-up work.
