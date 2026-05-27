# Regression Guards 🛡️

This page covers regression-guard rules in tests.
For general integration-test requirements and structure, see [Integration Tests](integration.md).

## Rules 📏

- You MUST NOT add regression tests that only verify that code, YAML, Jinja, or other source text is still present.
- Tests that only assert that a file contains a string, task name, variable name, or template fragment are not allowed.
- If the only purpose of a test is to prevent removal of a specific code path, you SHOULD document that directly at the relevant code location with a short comment explaining why it must not be removed.
- Prefer behavior-based tests that verify the actual runtime effect of the protected code path.

## Preferred Approach ✅

Instead of adding a text-presence regression test:

1. Add a short comment at the sensitive code path.
2. Explain what would break if that code were removed.
3. Add or keep a behavior-level test only when the behavior can be verified meaningfully.

## Examples 💡

- Good: a test that verifies a bootstrap path creates the expected runtime artifact or unblocks a dependent service.
- Bad: a test that only checks whether a task still contains `migrate:fresh`.
- Bad: a test that only checks whether a template still contains a specific lookup expression.
