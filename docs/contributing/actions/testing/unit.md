# Unit Tests 🧪

This page covers unit testing requirements, framework, and structure.
Run unit tests with `make test-unit`.

## Framework 🧰

- You MUST use Python `unittest` as the test framework.
- Tests MUST live under `tests/unit/`.
- Mirror the source tree: a file at `plugins/lookup/service.py` gets its tests at `tests/unit/plugins/lookup/test_service.py`.

## Requirements 📋

- You MUST add or update unit tests for every `*.py` file you touch.
- Each test MUST cover one isolated behavior. Do not test multiple concerns in a single test method.
- You MUST NOT write tests that only assert a file contains a string.
- You MUST NOT write tests for non-executable files such as `.yml` or `.j2`. Test the code that consumes them instead.
- You SHOULD name test methods after the behavior they verify, not the function name alone (e.g. `test_needed_false_when_disabled`).
- You SHOULD cover edge cases: empty inputs, missing keys, and boundary values, not only the happy path.
- You MAY use `unittest.mock` to isolate the unit under test from Ansible internals or external state.

## How to Create 🛠️

1. Identify the module under test (e.g. `plugins/lookup/service.py`).
2. Create the matching test file under `tests/unit/` if it does not exist.
3. Subclass `unittest.TestCase`.
4. Write one method per behavior. Build hypotheses before writing assertions.
5. Run `make test-unit` and verify all tests pass.

## Running Specific Tests 🏃

Use `INFINITO_TEST_PATTERN` to scope the test run to a single file or a glob:

```bash
# Run a single test file
make test-unit INFINITO_TEST_PATTERN=test_my_module.py

# Run all files matching a prefix
make test-unit INFINITO_TEST_PATTERN=test_applications*.py
```
