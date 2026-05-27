# Repository Settings 🔧

See also [branch.md](branch/security.md) for branch protection rules.

## Dependency Management 📦

### Dependency Graph ❌

👉 Contributors may not have access to full dependency insights

### Dependabot Alerts ❌

👉 Vulnerabilities may go unnoticed

### Dependabot Security Updates ❌

👉 Contributors MUST update dependencies manually

### Dependabot Version Updates ❌

👉 No automatic upgrade PRs

---

## Code Scanning (Global) 🔬

### CodeQL ✅

👉 Security issues may be detected automatically

### Copilot Autofix ✅

👉 Suggested fixes may appear

---

## Secret Protection 🔐

For GHCR authentication configuration see [authentication.md](../ghcr/authentication.md).

### Secret Scanning ❌

👉 Secrets may accidentally be committed

### Push Protection ❌

👉 Commits with secrets are NOT blocked

---

## Summary for Contributors 📋

Once enabled, you MUST:

* Create a PR (no direct push)
* Get 2 approvals
* Get CODEOWNER approval (if applicable)
* Resolve all comments
* Re-approve after changes
* Keep branch up-to-date
* Use signed commits
* Pass code scanning & quality checks

You MUST NOT:

* Push directly to main
* Force push
* Merge without approvals

You MAY:

* Create branches freely
* Use merge commits

All rules above are **currently enforced** on `main`.
