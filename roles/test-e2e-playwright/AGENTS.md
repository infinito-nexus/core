# Agent Instructions: test-e2e-playwright

This role is the **shared Playwright runner** for all end-to-end tests in the repository.
Changes here affect every application role that uses it.

## General Rules

- You MUST keep all changes to this role minimal and non-invasive.
- Before modifying any file in this role, you MUST explain to the user why the change is necessary and ask for explicit confirmation.
- You MUST NOT introduce new override mechanisms (e.g. per-role variable mappings) that bypass the existing environment-variable interface.
- Application roles MUST use the existing variables (`TEST_E2E_PLAYWRIGHT_IMAGE`, `TEST_E2E_PLAYWRIGHT_COMMAND`, etc.) for customisation instead of adding new indirection inside this role.

## File-Specific Rules

### `tasks/02_run_one.yml`

- You MUST NOT add new `set_fact` variables that shadow or wrap existing `TEST_E2E_PLAYWRIGHT_*` variables.
- You MUST NOT read from role `vars/main.yml` mappings of consuming roles (e.g. `test_e2e_playwright.*`) to override runner behaviour.
- Any change to the task flow MUST leave all existing call sites unaffected.

### `defaults/main.yml`

- New variables MUST follow the `TEST_E2E_PLAYWRIGHT_` prefix convention.
- Default values MUST be safe to use without any per-role override.

### `README.md`

- Document only variables and behaviour that are actually implemented in the role.
- Do NOT document patterns or extension points that do not exist in the code.
