# Repository Settings 🔧

See also [branch.md](branch/security.md) for branch protection rules.

## Dependency Management 📦

### Dependency Graph ✅

👉 Dependency insights are available under Insights → Dependency graph

### Dependabot Alerts ✅

👉 Known vulnerabilities in dependencies are reported as Dependabot alerts

### Dependabot Security Updates ✅

👉 Dependabot opens PRs that bump vulnerable dependencies to a fixed release

### Dependabot Version Updates ✅

👉 Dependabot opens upgrade PRs for the ecosystems listed in [dependabot.yml](../../../../.github/dependabot.yml)

---

## Code Scanning (Global) 🔬

### CodeQL ✅

👉 Security issues may be detected automatically

### Copilot Autofix ✅

👉 Suggested fixes may appear

---

## Secret Protection 🔐

For GHCR authentication configuration see [authentication.md](../ghcr/authentication.md).

### Secret Scanning ✅

👉 Committed secrets are detected and reported as secret scanning alerts

### Push Protection ✅

👉 Pushes that contain a detected secret are blocked

---

## Summary for Contributors 📋

You MUST:

- Create a PR (no direct push)
- Get 2 approvals
- Get CODEOWNER approval (if applicable)
- Resolve all comments
- Re-approve after changes
- Pass code scanning & quality checks

You MUST NOT:

- Push directly to main
- Force push
- Merge without approvals

You MAY:

- Create branches freely
- Use merge commits

All rules above are **currently enforced** on `main`.
