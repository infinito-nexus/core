# Shell Pipeline Lints 🐚

Lint tests that enforce safe shell-pipeline patterns inside Ansible `command:` and `shell:` tasks.
Each test catches a Bash default that hides upstream failures, especially when the failure surfaces only on the second or third command of a pipeline.

Tests in this directory MUST only cover shell-invocation correctness inside Ansible tasks.

- `test_no_sh_lc_pipefail.py` requires that every `sh -lc '...'` invocation containing a `|` pipeline starts with `set -o pipefail`, so failures mid-pipeline propagate.
- `test_no_sh_pipefail_in_ansible_tasks.py` requires that Ansible `shell:` tasks stay on Bash and use Bash's `set -o pipefail` form, not the POSIX-`sh` workaround.
- `test_sed_escape.py` requires that any Jinja-templated replacement passed to `sed` flows through the `sed_escape` filter so substitutions with regex metacharacters land literally.

For framework, directory layout, and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
