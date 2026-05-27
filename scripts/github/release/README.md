# Release Gates 🛡️

Shell helpers that gate version releases.

## Scope 📋

This directory contains gating helpers that decide whether a tagged commit is eligible for release. The current gate enforces that the version-tag commit is contained in `origin/main`, so version tags pushed from feature branches cannot trigger a release. Helpers MUST be invoked from release-related workflows only and MUST NOT be treated as a substitute for branch protection; the gate is an additional check on top of, not a replacement for, the repository's branch-protection rules.

For the workflow catalog see [workflows.md](../../../docs/contributing/tools/github/actions/workflows.md). For the contributor-facing release procedure see [release.md](../../../docs/contributing/actions/release.md).
