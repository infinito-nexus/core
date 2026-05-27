# Infrastructure Integration Tests 🏗️

Integration tests for the deployment substrate that every role shares: Docker Compose templates, Docker image consistency, container networks, the shared service registry, and the backups contract.

Each child directory pins one infrastructure surface; see the per-directory README for scope. Ansible-native artefacts (filters, lookups, playbooks) live under [`ansible/`](../ansible/); IAM concerns under [`iam/`](../iam/); per-role structural rules under [`roles/`](../roles/).

For framework and `make test-integration` usage see [integration.md](../../../docs/contributing/actions/testing/integration.md).
