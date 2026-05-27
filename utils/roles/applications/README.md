# Application Utilities (`utils/roles/applications/`) 🧩

This package contains shared Python helpers that operate on the central `applications` configuration dictionary.

## Purpose 🎯

Modules in `utils/roles/applications/` MUST provide reusable helpers for reading, resolving, and validating application configuration.
Helpers MUST stay independent of Ansible plugin entrypoints so the same code can be imported from filter plugins, lookup plugins, and library modules.

## Example Import ✍️

```python
from utils.roles.applications import config

value = config.get(
    applications,
    application_id,
    "features.oidc",
    strict=False,
    default=False,
)
```

## Design Guidelines 📐

- Helpers SHOULD be focused, composable, and free of side effects during import.
- Helpers MUST NOT depend on Ansible plugin loader behavior at import time.
- Helpers SHOULD raise typed exceptions (e.g. `AppConfigKeyError`) so callers can react to missing keys in strict mode.
- Public functions SHOULD use concise names (e.g. `get`) and rely on module-qualified access at call sites (`config.get(...)`) for clarity.

## What Does Not Belong Here 🚫

- Standalone executable modules MUST live in `library/`.
- Ansible plugin entrypoints MUST live under `plugins/*`.
- Cross-cutting helpers that are not application-specific SHOULD live in the parent `utils/` package instead.
