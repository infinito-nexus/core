# Category Tests 🗂️

Integration tests that validate `roles/categories.yml`: every declared category path MUST correspond to an existing directory under `roles/`, and `invokable: true` MUST NOT appear on any descendant of an already-invokable ancestor.

Tests in this directory MUST only cover the category hierarchy itself. Tests for `application_id` classification driven by `invokable_paths.py` MUST live under `tests/integration/roles/applications/id/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
