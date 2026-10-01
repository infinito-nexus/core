# Pull Request

🙏 Thank you for your contribution to [Infinito.Nexus](https://Infinito.Nexus).

Fill this in for any change. A specialised template carries extra prompts for its
area; to open one, append its `template=` parameter to the pull request creation
URL, for example `?quick_pull=1&template=server.md`.

* [Server](PULL_REQUEST_TEMPLATE/server.md) - `web-*` roles
* [Workstation](PULL_REQUEST_TEMPLATE/workstation.md) - `dsk-*` roles
* [System](PULL_REQUEST_TEMPLATE/system.md) - `sys-*`, `svc-*`, `dev-*`, `drv-*`
* [Pipeline](PULL_REQUEST_TEMPLATE/pipeline.md) - CI/CD
* [Agents](PULL_REQUEST_TEMPLATE/agents.md) - agent instruction files
* [Documentation](PULL_REQUEST_TEMPLATE/documentation.md) - docs only

---

## Summary

Briefly describe the change and the effect it has.

---

## Affected Components

List what this change touches.

* Primary role(s), module(s) or file(s):
* Related services, timers, packages, inventories, or workflows:

---

## Roles (optional `🧩 Subset` CI scope)

Optional. Ignored unless a maintainer applies the **🧩 Subset** label; without the label CI uses the diff-derived role set as usual. When the label is set, CI deploys **only** the roles listed here — each must be an existing `roles/<id>` directory, or the run fails. See [pipeline.md](../docs/contributing/artefact/git/pipeline.md#subset-label-).

```yaml
roles:
  # - sys-version
  # - svc-db-postgres
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

* What problem does this solve?
* How does it integrate with the existing stack?
* Were variables, defaults, and shared logic kept DRY?
* Are there migration or compatibility implications?
* Which alternatives were considered?

---

## Local Validation

Describe how the change was validated locally.

* [ ] Fresh deploy or targeted rerun tested
* [ ] Idempotency verified
* [ ] Relevant tests or lints run

---

## Security Impact

Indicate whether this change has security implications.

* [ ] No relevant security impact
* [ ] Security impact present

If security impact is present, explain:

* Affected auth, TLS, permissions, secrets, services, or exposed surfaces:
* Risk reduction, new exposure, migration, or compatibility considerations:
* Security-specific validation performed:

---

## Review Focus

Help reviewers focus on the riskiest parts of this PR.
For repository-wide contribution and review expectations, see [CONTRIBUTING.md](../CONTRIBUTING.md).

* Highest-risk files, roles, or flows:
* Idempotency, compatibility, or rollout concerns:
* Specific feedback requested from reviewers:

---

## Definition of Done (DoD)

* [ ] The implementation follows the Definition of Done, and the contribution guidelines in [CONTRIBUTING.md](../CONTRIBUTING.md) were considered and applied during implementation.

---

## Need Help?

💬 [Support and Contact](../SUPPORT.md) · Hub: <https://hub.infinito.nexus/> · Matrix: `#public:infinito.nexus`
