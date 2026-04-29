# Cache Helpers 💾

This package contains the in-process cache layers Infinito.Nexus uses to keep CLI tools, lookup plugins, and Ansible filters fast without re-reading or re-merging the same data multiple times per Python process.

## Modules 🧭

| Module | Caches |
|---|---|
| [yaml.py](yaml.py) | A single YAML file's parsed root, keyed by absolute path. Every other module routes its YAML reads through here so each file is parsed at most once per process. |
| [files.py](files.py) | The project tree's full path list (one walk per process) and per-file UTF-8 contents (`read_text`). Used by lint/integration tests and CLI tools that scan the repo. |
| [base.py](base.py) | Cross-cutting helpers: filesystem constants (`PROJECT_ROOT`, `ROLES_DIR`, `DEFAULT_TOKENS_FILE`), `_deep_merge`, cache-key + content-fingerprint signatures, the cross-domain re-entry guard, and the templar-render machinery. The only ansible-coupled symbol is `_render_with_templar`, which lazy-imports its dependency. |
| [applications.py](applications.py) | Per-app variants + defaults + `get_merged_applications`. **Strictly ansible-free at import time** so the GitHub Actions runner-host CLI path (`cli.deploy.development.init` → `plan_dev_inventory_matrix` → `get_variants`) keeps working without ansible installed. |
| [users.py](users.py) | User definitions, token store hydration, alias materialization, `get_user_defaults`, `get_merged_users`. |
| [domains.py](domains.py) | Canonical-domains map derived from the merged applications view: `get_merged_domains`. |
| [`__init__.py`](__init__.py) | Owns the package-level `_reset_cache_for_tests()` orchestrator that clears every cache plus the shared fingerprint memo in one call. |

## When To Use Which 🎯

- Use `utils.cache.yaml.load_yaml(path)` (or `load_yaml_any(path)` when the YAML root is a list or scalar) whenever a CLI tool, filter, or library reads individual YAML files where the same path MAY be touched repeatedly within a single invocation.
- Import the cached getters directly from the domain module that owns them: `utils.cache.applications` for `get_application_defaults` / `get_variants` / `get_merged_applications`, `utils.cache.users` for `get_user_defaults` / `get_merged_users`, and `utils.cache.domains` for `get_merged_domains`. The package's `_reset_cache_for_tests` is exposed at `from utils.cache import _reset_cache_for_tests`.

The layers are orthogonal: `yaml.py` caches "this file's parsed root", the `applications`/`users`/`domains` modules cache "this aggregated, rendered payload". They do not invalidate each other and MAY both be active at the same time.

## Lifetime 🕒

Both layers are process-wide in-process caches. They intentionally do NOT track on-disk file mtimes; CLI tools are short-lived and the assumption "the on-disk file does not change while my process runs" holds. The single exception is `utils.cache.yaml.dump_yaml`, which writes through and evicts the cached entry for the path it just wrote so a tool that edits a file mid-run sees the new content on the next read.

## Test-Only Helpers 🧪

Each module owns a private `_reset()` that clears its own cache dicts. The package-level `utils.cache._reset_cache_for_tests()` orchestrates all six (`base`, `applications`, `users`, `domains`, `yaml`, `files`) plus the shared fingerprint memo. Unit tests that exercise the cached paths MUST call it in `setUp` to guarantee clean state across test cases.

## Design Guidelines 📐

- You MUST NOT introduce a third parallel cache for the same concern. If you need to cache a derived shape, add a getter to the appropriate domain module (`applications`, `users`, or `domains`) that builds on the existing primitives.
- You SHOULD prefer the explicit cached getter over re-implementing the same memoisation in a calling module.
- You MUST NOT mutate values returned by `utils.cache.yaml.load_yaml`. The same dict instance is returned to every caller; callers that need to mutate MUST `copy.deepcopy()` the result first. Each domain getter documents whether it returns a fresh deep copy or the cached instance; respect that contract.
- You MUST keep dependencies inside this package minimal. Cache primitives MUST remain importable from filter plugins, lookup plugins, and CLI tools without dragging in heavy dependencies. **Specifically: `applications.py` MUST stay ansible-free at import time.** See CI runs 24934007615 / 24935979190 for the regression that motivated the split. Tests in `tests/unit/utils/cache/test_data.py::TestImportableWithoutAnsible` pin both the import-time and call-time invariants.

## Example Imports ✍️

```python
from utils.cache.yaml import load_yaml, load_yaml_any

from utils.cache.applications import (
    get_application_defaults,
    get_merged_applications,
    get_variants,
)
from utils.cache.users import get_merged_users, get_user_defaults
from utils.cache.domains import get_merged_domains

# Tests
from utils.cache import _reset_cache_for_tests
```
