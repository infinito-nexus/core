# Ansible Variable Lints 🪪

Lint tests that enforce variable-lifecycle invariants across the Ansible tree: every name a role declares MUST be consumed somewhere, and every name a role passes MUST be referenced by the play / template stack that receives it.

Tests in this directory MUST only cover variable definition / consumption checks. Four orthogonal scopes live here:

- `test_role_and_group_vars_used.py` scans top-level keys of `roles/<role>/{vars,defaults}/main.yml` and `group_vars/**/*.yml` against every project `.yml` / `.yaml` / `.j2` file. The suppression rule key is `unused-var` (see [suppression.md](../../../../docs/contributing/actions/testing/suppression.md)).
- `test_vars_usage_in_yaml.py` scans task-level `vars:` blocks against the same consumer set. The two scanners never overlap because their declaration shapes differ.
- `test_no_jinja_default_on_spot_path.py` forbids `| default(...)` on Jinja expressions whose path resolves via `group_vars/all/*.yml`. Those keys are loaded unconditionally, so the default is dead code at best and silent SPOT decoupling at worst. Per-line suppression: `# nocheck: spot-default`.
- `test_dotted_path_keys_exist.py` validates that every Jinja dotted path (`FOO.BAR.BAZ`) whose head is in `group_vars/all/` or the consuming role's own `vars`/`defaults` resolves to an existing key in that dict tree, catching typos / renamed / removed sub-keys. Per-line suppression: `# nocheck: dotted-path`.

Both tests route every read through the project caches (`utils.cache.files`, `utils.cache.yaml`); contributors adding a new variable scanner MUST do the same instead of calling `yaml.safe_load*` or `open()` directly.

For framework, directory layout, and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
