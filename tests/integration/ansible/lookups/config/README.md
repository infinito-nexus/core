# `lookup('config', …)` Path Validation 🔎

Integration tests that statically validate every `lookup('config', application_id, …)` (and quoted-app variants) found in role YAML and Jinja templates against the role's effective configuration.

Tests in this directory MUST only cover the four classifications of a single project-wide match stream: literal-app calls (`test_literal_paths.py`), variable-app calls with an existing literal path (`test_variable_paths.py`), `~`-concatenated path expressions (`test_wildcard_paths.py`), and the strict per-role pass for `lookup('config', application_id, …)` calls inside `roles/<role>/...` (`test_role_local_paths.py`). Pure unit coverage of the lookup plugin's return values MUST live under `tests/unit/plugins/lookup/`.

The match stream is built once per process by `_scan.iter_matches` and shared across the four test classes; the repo-derived context (application defaults, user defaults, per-role schemas, `application_id`-declaring role set) comes from `_scan.get_context`. Validation helpers live in `_validate.py`. Suppression is wired through the project's `noqa` / `nocheck` grammar; the rule key is `lookup-config-path` (see [suppression.md](../../../../../docs/contributing/actions/testing/suppression.md)).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../docs/contributing/actions/testing/integration.md).
