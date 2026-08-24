"""Schema lint for the unified addon contract: ``roles/*/meta/addons/*.yml``.

The unified addon contract promotes role-level extensions (``addon`` /
``plugin`` / ``mu_plugin`` / ``extension`` / ``module`` / ``bridge``) to a
first-class, directory-rooted topic: one ``meta/addons/<addon_id>.yml`` file
per addon, whose file root IS the addon spec (no wrapping key; the filename
stem is the addon id).

This is a hard lint: a malformed entry fails the test. It rejects:

* an invalid ``mechanism`` (outside the allowed set),
* an invalid ``source``,
* a missing required field (``mechanism`` / ``source``),
* a non-boolean ``required``,
* ``required: true`` combined with ``enabled: false``,
* an empty ``bridges: []`` (omit the key instead),
* a non-string ``version`` (a pin MUST be quoted),
* a non-string ``group``,
* an invalid ``update.catalog`` (outside the supported-adapter set),
* a non-mapping ``config``,
* an unknown top-level key (everything app-specific goes under ``config:``),
* a literal secret inlined under a secret-named ``config`` key.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: addon-schema`` in the head of an ``meta/addons/<id>.yml`` file
  exempts that whole addon from the schema checks.
* ``# nocheck: addon-secret`` on (or directly above) a ``config`` leaf line
  exempts that single value from the inlined-secret heuristic. Use it for
  legitimate non-secret literals under a secret-named key
  (e.g. ``token_lifetime: 3600``).
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS
from utils.update.addons import (
    ADDON_KEYS,
    MECHANISMS,
    SOURCES,
    SUPPORTED_CATALOGS,
    UPDATE_KEYS,
    secret_key_matches,
    value_is_templated,
)

from . import PROJECT_ROOT

_SCHEMA_RULE = "addon-schema"
_SECRET_RULE = "addon-secret"


def _iter_secret_leaves(node: object, path: tuple[str, ...] = ()):
    """Yield ``(key, value)`` for every scalar leaf whose key looks secret."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_str = str(key)
            if isinstance(value, (Mapping, list)):
                yield from _iter_secret_leaves(value, (*path, key_str))
            elif secret_key_matches(key_str):
                yield key_str, value
    elif isinstance(node, list):
        for item in node:
            yield from _iter_secret_leaves(item, path)


def _locate_leaf_line(lines: list[str], key: str, used: set[int]) -> int | None:
    """Return the first unused line whose stripped form starts ``<key>:``."""
    needle = f"{key}:"
    for idx, raw in enumerate(lines, start=1):
        if idx in used:
            continue
        if raw.strip().startswith(needle):
            return idx
    return None


class TestAddonsSchema(unittest.TestCase):
    """Hard lint: every ``meta/addons/<id>.yml`` obeys the unified schema."""

    def test_addons_schema(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        errors: list[str] = []

        for role_dir in sorted(p for p in roles_root.iterdir() if p.is_dir()):
            addons_dir = role_dir / ROLE_DIR_META_ADDONS
            if not addons_dir.is_dir():
                continue
            role = role_dir.name

            for config_path in sorted(addons_dir.glob("*.yml")):
                addon_id = config_path.stem
                rel = config_path.relative_to(PROJECT_ROOT).as_posix()
                lines = read_text(str(config_path)).splitlines()

                if is_suppressed_in_head(lines, _SCHEMA_RULE):
                    continue

                try:
                    spec = load_yaml_any(str(config_path), default_if_missing={}) or {}
                except Exception as exc:
                    errors.append(f"{role}: YAML parse error in {rel}: {exc}")
                    continue

                prefix = f"{role}: addons.{addon_id}"

                if not isinstance(spec, Mapping):
                    errors.append(
                        f"{prefix} file root MUST be the addon spec mapping "
                        f"(no wrapping key). ({rel})"
                    )
                    continue

                unknown = set(spec) - ADDON_KEYS
                if unknown:
                    errors.append(
                        f"{prefix} has unknown key(s) {sorted(unknown)}; "
                        f"app-specific data goes under 'config:'. ({rel})"
                    )

                if "mechanism" not in spec:
                    errors.append(f"{prefix} is missing required 'mechanism'. ({rel})")
                elif spec.get("mechanism") not in MECHANISMS:
                    errors.append(
                        f"{prefix} has invalid mechanism {spec.get('mechanism')!r}; "
                        f"allowed: {sorted(MECHANISMS)}. ({rel})"
                    )

                if "source" not in spec:
                    errors.append(f"{prefix} is missing required 'source'. ({rel})")
                elif spec.get("source") not in SOURCES:
                    errors.append(
                        f"{prefix} has invalid source {spec.get('source')!r}; "
                        f"allowed: {sorted(SOURCES)}. ({rel})"
                    )

                required = spec.get("required")
                if "required" in spec and not isinstance(required, bool):
                    errors.append(
                        f"{prefix} 'required' MUST be a boolean, got "
                        f"{type(required).__name__}. ({rel})"
                    )

                if required is True and spec.get("enabled") is False:
                    errors.append(
                        f"{prefix} sets required: true with enabled: false; a "
                        f"required addon is always installed. ({rel})"
                    )

                if "bridges" in spec:
                    bridges = spec.get("bridges")
                    if not isinstance(bridges, list) or not bridges:
                        errors.append(
                            f"{prefix} 'bridges' MUST be a non-empty list (omit "
                            f"the key when there is no cross-role dependency). "
                            f"({rel})"
                        )
                    elif not all(isinstance(b, str) and b for b in bridges):
                        errors.append(
                            f"{prefix} 'bridges' entries MUST be service-key "
                            f"strings. ({rel})"
                        )

                if "version" in spec and not isinstance(spec.get("version"), str):
                    errors.append(
                        f"{prefix} 'version' MUST be a string (quote the pin so a "
                        f"number is never YAML-coerced). ({rel})"
                    )

                if "group" in spec and not isinstance(spec.get("group"), str):
                    errors.append(f"{prefix} 'group' MUST be a string. ({rel})")

                update = spec.get("update")
                if "update" in spec:
                    if not isinstance(update, Mapping):
                        errors.append(f"{prefix} 'update' MUST be a mapping. ({rel})")
                    else:
                        unknown_update = set(update) - UPDATE_KEYS
                        if unknown_update:
                            errors.append(
                                f"{prefix} 'update' has unknown key(s) "
                                f"{sorted(unknown_update)}; allowed: "
                                f"{sorted(UPDATE_KEYS)}. ({rel})"
                            )
                        catalog = update.get("catalog")
                        if catalog is not None and catalog not in SUPPORTED_CATALOGS:
                            errors.append(
                                f"{prefix} 'update.catalog' {catalog!r} is not a "
                                f"supported adapter; allowed: "
                                f"{sorted(SUPPORTED_CATALOGS)}. ({rel})"
                            )
                        if "monitored" in update and not isinstance(
                            update.get("monitored"), bool
                        ):
                            errors.append(
                                f"{prefix} 'update.monitored' MUST be a boolean. "
                                f"({rel})"
                            )

                config = spec.get("config")
                if "config" in spec and not isinstance(config, Mapping):
                    errors.append(f"{prefix} 'config' MUST be a mapping. ({rel})")
                elif isinstance(config, Mapping):
                    used_secret_lines: set[int] = set()
                    for key, value in _iter_secret_leaves(config):
                        if value_is_templated(value) or value in ("", None):
                            continue
                        leaf_line = _locate_leaf_line(lines, key, used_secret_lines)
                        if leaf_line is not None:
                            used_secret_lines.add(leaf_line)
                            if is_suppressed_at(lines, leaf_line, _SECRET_RULE):
                                continue
                        errors.append(
                            f"{prefix} config.{key} inlines a literal secret "
                            f"{value!r}; use lookup('config', application_id, "
                            f"'secrets.credentials.<name>') instead (or mark "
                            f"'# nocheck: addon-secret' for a non-secret literal). "
                            f"({rel})"
                        )

        if errors:
            self.fail(
                f"meta/addons/*.yml schema violations ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
