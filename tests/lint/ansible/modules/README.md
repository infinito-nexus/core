# Ansible Module Lints 🔧

Lint tests that enforce correct Ansible module usage and task-level invariants.
Each test catches a class of silent or confusing failure that the runtime would otherwise tolerate or surface far from its cause.

Tests in this directory MUST only cover Ansible module / task usage rules.

- `test_network_create_via_util.py` requires that role tasks creating Docker networks route through the shared utility, never inline `community.docker.docker_network` calls.
- `test_no_legacy_get_url_module_usage.py` forbids the unqualified `get_url:` module name; tasks MUST use `ansible.builtin.get_url`.
- `test_no_legacy_uri_module_usage.py` forbids the unqualified `uri:` module name; tasks MUST use `ansible.builtin.uri`.
- `test_no_literal_no_log.py` forbids literal `no_log: true` / `no_log: false`; every gate MUST flow through the `MASK_CREDENTIALS_IN_LOGS` variable.
- `test_no_redundant_default_on_module_io.py` forbids `| default(...)` on a task's own `register:` output or input arguments inside its own conditionals, where the value is provably set.
- `test_run_once_tags.py` requires that every `set_fact` marked `run_once: true` carries the canonical run-once tags so re-runs and `--tags` filters keep the fact populated.

Shell-pipeline rules and SQL formatting rules live in sibling directories; see `../shell/` and `../sql/`.

For framework, directory layout, and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
