# GitHub Workflow Tests ⚙️

Integration tests for `.github/workflows/*.yml` and supporting scripts: PR scope/branch-prefix resolvers, PR-run cancellation, Dependabot coverage of every ecosystem in the repo, and CodeQL security-workflow coverage.

Tests in this directory MUST only cover GitHub-side CI/CD artefacts (workflows, Dependabot, PR helpers). Tests for local `make` targets, role logic, or non-CI scripts MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
