# Role Utilities 🧩

Helpers under `utils/roles/` operate on Ansible role artefacts and the dictionaries that mirror them at runtime.

## Scope 📋

Modules in `utils/roles/` MUST stay focused on data that originates from `roles/<role>/` (`meta/services.yml`, `meta/main.yml`, `vars/`, `defaults/`) or the runtime dictionary that mirrors those files (`applications`).

Modules in `utils/roles/` MUST NOT depend on Ansible plugin loader internals at import time so the same code can be imported from filter plugins, lookup plugins, library modules, the CLI, and tests.

## Subpackages 📦

- [applications/](applications/README.md) helpers around the central `applications` dict and the role config that feeds it.
