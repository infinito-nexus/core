# Shared Utilities (`utils/`)

This directory contains shared Python helpers used by custom modules and plugins.

## Purpose

Use `utils/` for reusable code that should not be duplicated across:

- `library/` modules,
- `plugins/action/`,
- `plugins/filter/`,
- `plugins/lookup/`.

Typical shared utilities:

- API clients,
- validation/conversion helpers,
- path and configuration helpers,
- cross-plugin/module domain logic.
- Shared HTTP(S) connection handler for multiple modules.
- Common validation or transformation functions for user input.
- Utility functions for interacting with Docker, LDAP, etc.
- Grouped helper packages such as `utils/domains/` for related domain logic.

## Design Guidelines

- Keep helpers focused and composable.
- Avoid side effects during import.
- Prefer explicit function/class APIs over implicit globals.
- Keep dependencies minimal so modules/plugins stay lightweight.

## Example Import

```python
from utils.domains.primary_domain import get_primary_domain
```

## What Does Not Belong Here

- Standalone executable modules (put in `library/`).
- Ansible plugin entrypoints (put in `plugins/*`).

## References

- Module utilities: <https://docs.ansible.com/ansible/latest/dev_guide/developing_module_utilities.html>
- Plugin development: <https://docs.ansible.com/ansible/latest/dev_guide/developing_plugins.html>
