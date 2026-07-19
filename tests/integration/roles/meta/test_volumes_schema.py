"""Schema + lookup contract for meta/volumes.yml.

Canonical shape is dict-of-dicts: the top-level YAML key is the semantic
short name (consumed by ``lookup('config', <app>, 'volumes.<key>.<attr>')``)
and the entry body carries ``type``, optional ``name`` (container volume
name, defaults to the key), ``source``, ``mounts``, ``nfs`` etc. The
schema itself is enforced by ``utils.roles.applications.mounts.validate_volumes_meta``;
this test reuses that validator on every role's file and additionally
verifies that lookup callers reference declared attributes.
"""

import re
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mounts import validate_volumes_meta
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

VOLUMES_LOOKUP_PATTERN = re.compile(
    r"""lookup\(\s*['"]config['"]\s*,\s*[^,]+,\s*['"]volumes\.([A-Za-z0-9_.\-]+)['"]"""
)


def _collect_volumes_files() -> list[Path]:
    return sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_VOLUMES}"))


def _allowed_attr_paths(entry: dict) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    if "name" in entry:
        paths.add(("name",))
    if "source" in entry:
        paths.add(("source",))
    if "path" in entry:
        paths.add(("path",))
    nfs = entry.get("nfs")
    if isinstance(nfs, dict):
        paths.add(("nfs",))
        for key in nfs:
            paths.add(("nfs", key))
    elif nfs is not None:
        paths.add(("nfs",))
    return paths


class TestVolumesSchema(unittest.TestCase):
    def test_every_volumes_yml_matches_canonical_dict_schema(self):
        files = _collect_volumes_files()
        self.assertTrue(files, "no meta/volumes.yml files found")
        offenders: list[str] = []
        for path in files:
            rel = path.relative_to(PROJECT_ROOT)
            role_id = path.parent.parent.name
            try:
                data = load_yaml_any(str(path))
            except yaml.YAMLError as exc:
                offenders.append(f"{rel}: invalid YAML ({exc})")
                continue
            if data is None:
                continue
            if not isinstance(data, dict):
                offenders.append(
                    f"{rel}: top-level must be a mapping (dict-of-dicts), "
                    f"got {type(data).__name__}"
                )
                continue
            offenders.extend(
                f"{rel}: {v}" for v in validate_volumes_meta(data, role_id)
            )
        if offenders:
            self.fail(
                "meta/volumes.yml schema violations (canonical dict-of-dicts "
                "shape; per-entry rules enforced by validate_volumes_meta):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestVolumesLookupAttrs(unittest.TestCase):
    def test_every_volumes_lookup_resolves_to_declared_attr(self):
        files = _collect_volumes_files()
        per_role_schema: dict[str, dict[str, dict]] = {}
        for path in files:
            try:
                data = load_yaml_any(str(path))
            except yaml.YAMLError:
                continue
            role_name = path.parent.parent.name
            if isinstance(data, dict):
                per_role_schema[role_name] = {
                    semantic_name: entry
                    for semantic_name, entry in data.items()
                    if isinstance(entry, dict)
                }

        offenders: list[str] = []
        for file_path, content in iter_project_files_with_content(
            extensions=(".yml", ".j2")
        ):
            for match in VOLUMES_LOOKUP_PATTERN.finditer(content):
                path_str = match.group(1)
                parts = path_str.split(".")
                volume_key = parts[0]
                attr_parts = parts[1:]
                if not attr_parts:
                    line = content[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{file_path}:{line}: 'volumes.{path_str}' must "
                        f"reference a sub-attribute (e.g. '.name')"
                    )
                    continue
                consumer_role = _find_role(file_path)
                role_schema = per_role_schema.get(consumer_role, {})
                entry = role_schema.get(volume_key)
                if entry is None:
                    line = content[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{file_path}:{line}: 'volumes.{volume_key}' is not "
                        f"declared in roles/{consumer_role}/"
                        f"{ROLE_FILE_META_VOLUMES}"
                    )
                    continue
                allowed = _allowed_attr_paths(entry)
                # Semantic-name lookups (`.name` defaulting to the dict
                # key when the entry omits an explicit docker name) are
                # always permitted for type: volume entries.
                if entry.get("type", "volume") == "volume":
                    allowed.add(("name",))
                if tuple(attr_parts) not in allowed:
                    line = content[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{file_path}:{line}: 'volumes.{path_str}' is not a "
                        f"declared attribute (allowed: "
                        f"{sorted('.'.join(p) for p in allowed)})"
                    )
        if offenders:
            self.fail(
                "Invalid volumes lookups (consumers reference attributes not "
                "declared in the role's meta/volumes.yml):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


def _find_role(file_path: str) -> str | None:
    p = Path(file_path)
    try:
        rel = p.relative_to(PROJECT_ROOT / "roles")
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    return parts[0]


if __name__ == "__main__":
    unittest.main()
