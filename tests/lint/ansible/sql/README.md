# SQL Lints 💾

Lint tests that enforce safe inline-SQL practices inside Ansible task definitions.

Tests in this directory MUST only cover SQL-shape rules inside Ansible tasks.

- `test_no_inline_multiline_sql.py` caps inline multi-line SQL in Ansible tasks at three lines. Larger statements MUST live in a dedicated `.sql` file under the role's `files/` directory and be loaded explicitly so linters, formatters, and database tooling can operate on them.

For framework, directory layout, and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
