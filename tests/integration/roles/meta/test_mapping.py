"""Generalist lint guard for the role-mapping SPOT.

For every role under ``roles/`` and every entry in
:data:`utils.roles.mapping.ROLE_FILES`, this test cross-checks the
schema's ``mandatory`` / ``allowed`` policy against what the role
actually ships on disk:

* **Forbidden file present.** The role's type set is not permitted to
  carry the file. Either declare a marker that legitimises the file
  (e.g. add ``application_id`` to ``vars/main.yml``) or remove the
  file.
* **Mandatory file missing.** At least one of the role's types
  requires the file. Create the file or change the role's type by
  removing the marker that pulls the type in.
* **Forbidden entry present.** The dotted path is set in the file but
  no type the role belongs to permits it.
* **Mandatory entry missing.** A type the role belongs to requires
  the dotted path, but it is absent or empty in the file.

A role MAY carry several types simultaneously; the role's effective
policy is the UNION over its types: a file/entry is required when ANY
type requires it, allowed when ANY type allows it, and forbidden only
when no type allows it.

Policy resolution per (file, role_type):

1. an explicit type entry overrides everything else;
2. otherwise the :data:`utils.roles.mapping.ROLE_TYPE_ALL` wildcard
   acts as the fallback;
3. otherwise the file/entry is implicitly forbidden for that type.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILES, ROLE_TYPE_ALL
from utils.roles.type import get_role_types

from . import PROJECT_ROOT

_ROLES_DIR = PROJECT_ROOT / "roles"


def _entry_for_type(file_entry: dict, role_type: str) -> dict | None:
    """Return the type-scoping entry that applies to *role_type*.

    Concrete-type entries override the wildcard fallback; when neither
    matches the file is implicitly forbidden for that type.
    """
    types = file_entry.get("types") or []
    wildcard: dict | None = None
    for entry in types:
        if not isinstance(entry, dict):
            continue
        t = entry.get("type")
        if t == role_type:
            return entry
        if t == ROLE_TYPE_ALL and wildcard is None:
            wildcard = entry
    return wildcard


def _aggregate_policy(
    file_entry: dict, role_types: frozenset[str]
) -> tuple[bool, bool, dict[str, dict[str, bool]]]:
    """Return ``(file_allowed, file_mandatory, entries)`` aggregated
    across every role type the role belongs to.

    *entries* maps each declared dotted path to ``{"allowed": bool,
    "mandatory": bool}``. A path counts as allowed when any type that
    lists it permits it, and as mandatory when any type that lists it
    requires it.
    """
    file_allowed = False
    file_mandatory = False
    entries: dict[str, dict[str, bool]] = {}

    for role_type in role_types:
        type_entry = _entry_for_type(file_entry, role_type)
        if type_entry is None:
            continue
        if bool(type_entry.get("allowed", True)):
            file_allowed = True
        if bool(type_entry.get("mandatory", False)):
            file_mandatory = True
        for sub in type_entry.get("entries") or []:
            if not isinstance(sub, dict):
                continue
            path = sub.get("path")
            if not isinstance(path, str) or not path:
                continue
            slot = entries.setdefault(path, {"allowed": False, "mandatory": False})
            if bool(sub.get("allowed", True)):
                slot["allowed"] = True
            if bool(sub.get("mandatory", False)):
                slot["mandatory"] = True

    return file_allowed, file_mandatory, entries


def _resolve_dotted(data: object, dotted: str) -> object:
    """Walk *dotted* (``a.b.c``) into *data*. Return ``None`` whenever a
    segment is missing or *data* turns into a non-mapping mid-walk.
    """
    cursor: object = data
    for segment in dotted.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(segment)
    return cursor


def _value_present(value: object) -> bool:
    """Return ``True`` when *value* counts as a real, non-empty entry.

    ``None``, empty strings, whitespace-only strings, empty lists, and
    empty mappings all count as absent so a key declared without a
    value does not satisfy a ``mandatory: True`` requirement.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


class TestRoleMapping(unittest.TestCase):
    def test_role_files_match_mapping_spot(self):
        forbidden_files: list[str] = []
        missing_files: list[str] = []
        forbidden_entries: list[str] = []
        missing_entries: list[str] = []

        for role_dir in sorted(
            p
            for p in _ROLES_DIR.iterdir()
            if p.is_dir() and not p.name.startswith("__")
        ):
            role_types = get_role_types(role_dir)
            type_label = ", ".join(sorted(role_types))

            for file_rel_path, file_entry in ROLE_FILES.items():
                rel_meta = role_dir.relative_to(PROJECT_ROOT) / file_rel_path
                meta_file = role_dir / file_rel_path
                present = meta_file.is_file()

                file_allowed, file_mandatory, entry_rules = _aggregate_policy(
                    file_entry, role_types
                )

                if present and not file_allowed:
                    forbidden_files.append(f"{rel_meta} (role types: {type_label})")
                if not present and file_mandatory:
                    missing_files.append(f"{rel_meta} (role types: {type_label})")

                if not present or not entry_rules:
                    continue

                data = load_yaml_any(str(meta_file), default_if_missing={})
                if not isinstance(data, dict):
                    continue

                for path, rules in sorted(entry_rules.items()):
                    value = _resolve_dotted(data, path)
                    has_value = _value_present(value)
                    if rules["mandatory"] and not has_value:
                        missing_entries.append(
                            f"{rel_meta}:{path} (role types: {type_label})"
                        )
                    if not rules["allowed"] and has_value:
                        forbidden_entries.append(
                            f"{rel_meta}:{path} (role types: {type_label})"
                        )

        sections: list[str] = []

        def _add(title: str, items: list[str]) -> None:
            if not items:
                return
            sections.append(f"{title} ({len(items)}):")
            sections.extend(f"  - {item}" for item in items)

        _add("Forbidden file(s) present", forbidden_files)
        _add("Mandatory file(s) missing", missing_files)
        _add("Forbidden entr(y|ies) present", forbidden_entries)
        _add("Mandatory entr(y|ies) missing", missing_entries)

        if sections:
            self.fail(
                "Role mapping violations vs. utils/roles/mapping.py:\n"
                + "\n".join(sections)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
