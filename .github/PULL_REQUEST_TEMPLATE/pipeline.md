## Summary

Briefly describe the CI/CD or pipeline change and the expected effect.

Examples:

* Add a new workflow or reusable workflow
* Fix flaky CI, release, or image automation behavior
* Improve workflow permissions, observability, or execution flow

---

## Template Type

Select the primary intent of this PR:

* [ ] **Feature** - Adds or extends CI/CD functionality
* [ ] **Fix** - Repairs broken or incorrect CI/CD behavior

---

## Affected Components

List the impacted workflows and related automation.

* Workflow file(s):
* Related scripts, actions, jobs, or images:
* Fork, PR, release, or scheduled paths affected:

---

## Roles (optional `🧩 Subset` CI scope)

Optional. Ignored unless a maintainer applies the **🧩 Subset** label; without the label CI uses the diff-derived role set as usual. When the label is set, CI deploys **only** the roles listed here — each must be an existing `roles/<id>` directory, or the run fails. See [pipeline.md](../../docs/contributing/artefact/git/pipeline.md#subset-label-).

```yaml
roles:
  # - web-app-nextcloud
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

* What pipeline problem or capability does this address?
* How do triggers, permissions, concurrency, or artifacts behave after this change?
* Are fork, secret, or release paths affected?
* Which alternatives were considered?

---

## Validation

Describe how the pipeline change was validated.

* [ ] Local or targeted script validation performed
* [ ] Workflow run in fork or equivalent validation
* [ ] Relevant logs or run links attached
* [ ] Failure-path or retry behavior checked

---

## Security Impact

Indicate whether this change has security implications.

* [ ] No relevant security impact
* [ ] Security impact present

If security impact is present, explain:

* Affected permissions, secrets, tokens, artifacts, or release surfaces:
* Risk reduction, new exposure, fork-safety, or compatibility considerations:
* Security-specific validation performed:

---

## Review Focus

Help reviewers focus on the riskiest parts of this PR.
For repository-wide contribution and review expectations, see [CONTRIBUTING.md](../../CONTRIBUTING.md).

* Highest-risk workflows, jobs, or scripts:
* Permissions, fork-safety, release, or security-sensitive concerns:
* Specific feedback requested from reviewers:

---

## Definition of Done (DoD)

* [ ] The implementation follows the Definition of Done, and the contribution guidelines in [CONTRIBUTING.md](../../CONTRIBUTING.md) were considered and applied during implementation.

---

## Additional Notes

Add any reviewer context for rollout, fork behavior, release impact, or follow-up work.
