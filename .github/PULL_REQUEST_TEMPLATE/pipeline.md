# Pipeline Pull Request

## Summary

Briefly describe the CI/CD or pipeline change and the expected effect.

Examples:

- Add a new workflow or reusable workflow
- Fix flaky CI, release, or image automation behavior
- Improve workflow permissions, observability, or execution flow

## Change Type

Intent:

- [ ] **Feature** - Adds or extends CI/CD functionality
- [ ] **Fix** - Repairs broken or incorrect CI/CD behavior

Semantic version impact:

- [ ] **Major** - Breaking change
- [ ] **Minor** - New backwards-compatible feature
- [ ] **Patch** - Small improvement or compatible adjustment

## Affected Components

- Workflow file(s):
- Related scripts, actions, jobs, or images:
- Fork, PR, release, or scheduled paths affected:

## Roles (optional `🧩 Subset` CI scope)

Read only when a maintainer applies the **🧩 Subset** label: CI then deploys exactly these roles instead of the diff-derived set, and each MUST be an existing `roles/<id>` directory. See [pipeline.md](../../docs/contributing/artefact/git/pipeline.md#subset-label-).

```yaml
roles:
  # - web-app-nextcloud
  # - sys-version
```

## Change Details

Explain what changed and why, covering:

- What pipeline problem or capability does this address?
- How do triggers, permissions, concurrency, or artifacts behave after this change?
- Are fork, secret, or release paths affected?
- Which alternatives were considered?

## Validation

- [ ] Local or targeted script validation performed
- [ ] Workflow run in fork or equivalent validation
- [ ] Relevant logs or run links attached
- [ ] Failure-path or retry behavior checked
- [ ] The Definition of Done and [CONTRIBUTING.md](../../CONTRIBUTING.md) were applied

### Test Evidence

List the commands that were run and their results.

## Security Impact

- [ ] No relevant security impact
- [ ] Security impact present

If security impact is present, explain:

- Affected permissions, secrets, tokens, artifacts, or release surfaces:
- Risk reduction, new exposure, fork-safety, or compatibility considerations:
- Security-specific validation performed:

## Review Focus

- Highest-risk workflows, jobs, or scripts:
- Permissions, fork-safety, release, or security-sensitive concerns:
- Specific feedback requested from reviewers:

## Additional Notes

Add any reviewer context for rollout, fork behavior, release impact, or follow-up work.
