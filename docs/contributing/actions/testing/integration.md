# Integration Tests 🔗

This page covers integration testing requirements, framework, and structure.
Run integration tests with `make test-integration`.

## Framework 🧰

- You MUST use Python `unittest` as the test framework.
- Tests that verify real runtime component interactions MUST live under `tests/integration/`.
- Tests that statically analyze Ansible config or task YAML files without exercising runtime boundaries MUST live under `tests/lint/ansible/` instead.

## When to Write ✍️

- You MUST add or update integration tests for every `*.py` file you touch when the change affects behavior across module or runtime boundaries.
- Write an integration test when the behavior you are verifying depends on two or more components working together at runtime. For example, verify a lookup plugin reading from real `group_vars` or a filter interacting with an Ansible variable structure.
- Write a lint test under `tests/lint/ansible/` when the check only inspects static YAML structure, config keys, or comment annotations without executing any code.

## Requirements 📋

- You MUST NOT write unit tests for integration test logic. Integration tests verify real runtime boundaries; extracting that logic into unit tests defeats the purpose and duplicates coverage. The integration test itself is the specification.
- You MUST NOT mock collaborators that are part of the integration boundary being tested. The point is to verify real interaction.
- You MUST NOT write tests that only assert a file contains a string.
- You MUST NOT write tests only for non-executable files such as `.yml` or `.j2`. Test the behavior that consumes them.
- You SHOULD keep each test focused on one integration boundary.
- You SHOULD test realistic inputs that match what Ansible would pass at runtime.
- You MAY use `unittest.mock` to stub out external services or filesystem state that is genuinely outside the integration scope.

## How to Create 🛠️

1. Identify the integration boundary (e.g. lookup plugin + `group_vars` variable loading).
2. Decide whether the test exercises a real runtime interaction (`tests/integration/`) or only inspects static YAML structure (`tests/lint/ansible/`).
3. Create the matching test file under the correct directory if it does not exist.
4. Subclass `unittest.TestCase`.
5. Use realistic inputs. Build hypotheses about cross-component behavior before writing assertions.
6. Run `make test-integration` (or `make test-lint` for lint tests) and verify all tests pass.

## Running Specific Tests 🏃

Use `INFINITO_TEST_PATTERN` to scope the test run to a single file or a glob:

```bash
# Run a single integration test file
make test-integration INFINITO_TEST_PATTERN=test_my_module.py

# Run all files matching a prefix
make test-integration INFINITO_TEST_PATTERN=test_applications*.py
```
