# Branch Protection 🔒

See also [repository.md](../repository.md) for repository-wide security settings.

## Enforcement 🔒

- Ruleset is **Enabled (Enforced)**

👉 **Meaning for contributors:**

- All rules in this document are **actively enforced** on the default branch (`main`).
- Contributors MUST comply; violations will block pushes/merges.

---

## Bypass 🚪

- Organization admins and repository admins can always bypass rules

👉 **Meaning for contributors:**

- Normal contributors MUST follow all rules
- Admins MAY merge without approvals or checks

---

## Branch Target 🎯

- Applies to: **`main` (default branch)**

👉 **Meaning for contributors:**

- All rules apply when targeting `main`.
- Feature branches are NOT restricted until a PR targets `main`.

---

## Restrictions 🚫

### Restrict Updates ✅

- Direct pushes are blocked

👉 **Contributor impact:**

- You MUST NOT push directly to `main`
- You MUST use a Pull Request (PR)

---

### Restrict Deletions ✅

- Protected branch cannot be deleted

👉 **Contributor impact:**

- You MUST NOT delete the main branch

---

### Restrict Creations ❌

- Branch creation is allowed

👉 **Contributor impact:**

- You MAY create branches freely

---

## Pull Request Requirements 📋

### Require Pull Request ✅

👉 **Contributor impact:**

- You MUST open a PR to merge into `main`
- Direct commits to `main` are rejected

---

### Required Approvals: 2 ✅

👉 **Contributor impact:**

- You MUST get **2 approvals** before merging
- Self-approval does not count

---

### Dismiss Stale Approvals ✅

👉 **Contributor impact:**

- If you push new commits:

  - Previous approvals are INVALIDATED
- You MUST get approvals again

---

### Require Code Owner Reviews ✅

👉 **Contributor impact:**

- If you modify owned files:

  - A CODEOWNER MUST approve
- PR cannot be merged without them

---

### Require Approval of Most Recent Push ✅

👉 **Contributor impact:**

- After your last commit:

  - Someone ELSE MUST approve again
- You CANNOT approve your own changes

---

### Require Conversation Resolution ✅

👉 **Contributor impact:**

- All review comments MUST be resolved
- Open discussions block merging

---

### Require Review from Specific Teams ❌

👉 **Contributor impact:**

- No fixed team is always required
- Only CODEOWNERS matter

---

## Merge Strategy 🔀

### Allowed Merge Method: Merge ✅

👉 **Contributor impact:**

- PRs are merged using merge commits
- History MAY become non-linear

---

### Require Linear History ❌

👉 **Contributor impact:**

- Merge commits ARE allowed
- You MAY see branching history

---

### Require Merge Queue ❌

👉 **Contributor impact:**

- PRs can be merged immediately after approval
- No automatic queueing

---

## Status Checks (CI/CD) ✅

### Require Status Checks to Pass ✅

👉 **Contributor impact:**

- Your PR MUST pass CI before merging

---

### Required Checks: NONE ⚠️

👉 **Contributor impact:**

- Currently, no checks are enforced
- Effectively: nothing blocks merge here

---

### Require Branch to Be Up-To-Date ✅

👉 **Contributor impact:**

- You MUST update your branch before merging
- Typically via:

  - merge `main`
  - or rebase

---

## Security 🔐

### Require Signed Commits ✅

👉 **Contributor impact:**

- All commits MUST be signed (GPG/SSH)
- Unsigned commits will be rejected

---

### Block Force Pushes ✅

👉 **Contributor impact:**

- You MUST NOT rewrite history on protected branches
- `git push --force` is blocked

---

## Code Scanning 🔬

### Require Code Scanning Results ✅

Configured tools:

- CodeQL (High severity)
- Hadolint (High severity)

👉 **Contributor impact:**

- PR MUST NOT introduce high-severity issues
- Otherwise merge is blocked

---

## Code Quality 🏆

### Require Code Quality Results ✅

- Threshold: Warnings and higher

👉 **Contributor impact:**

- You MUST fix code quality issues before merge

---

## Copilot Review 🤖

### Automatically Request Copilot Review ✅

👉 **Contributor impact:**

- Copilot may automatically review your PR
- It may comment on issues
- It does not replace human approvals
