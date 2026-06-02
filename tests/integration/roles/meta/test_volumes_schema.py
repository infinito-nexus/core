"""Schema + lookup contract for meta/volumes.yml.

Every entry MUST be a mapping with a non-empty ``name`` (the docker volume
name). Optional ``nfs`` block carries ``uid`` / ``gid`` / ``mode`` for the
NFS subdir pre-create in sys-svc-compose. Unknown keys at either level fail
the test so the schema stays the single source of truth.

The companion check sweeps every YAML/Jinja file for
``lookup('config', <app>, 'volumes.<key>.<attr...>')`` calls and verifies
that ``<attr...>`` resolves to a declared field; this catches drift between
volumes.yml and consumers without running a deploy.
"""

import re
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

ALLOWED_ENTRY_KEYS = {"name", "path", "nfs"}
ALLOWED_NFS_KEYS = {"uid", "gid", "mode"}

VOLUMES_LOOKUP_PATTERN = re.compile(
    r"""lookup\(\s*['"]config['"]\s*,\s*[^,]+,\s*['"]volumes\.([A-Za-z0-9_.\-]+)['"]"""
)


def _collect_volumes_files() -> list[Path]:
    return sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_VOLUMES}"))


def _validate_entry(entry: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        errors.append(f"entry must be a mapping, got {type(entry).__name__}")
        return errors
    has_name = "name" in entry
    has_path = "path" in entry
    if not has_name and not has_path:
        errors.append("missing mandatory key 'name' or 'path' (exactly one)")
    if has_name and has_path:
        errors.append("'name' and 'path' are mutually exclusive; declare only one")
    if has_name:
        name = entry["name"]
        if not isinstance(name, str) or not name.strip():
            errors.append(f"'name' must be a non-empty string, got {name!r}")
        elif "/" in name:
            errors.append(
                f"'name' is a docker volume name and MUST NOT contain '/'; "
                f"use 'path' for filesystem paths (got {name!r})"
            )
    if has_path:
        path = entry["path"]
        if not isinstance(path, str) or not path.strip():
            errors.append(f"'path' must be a non-empty string, got {path!r}")
        elif "{{" not in path and "/" not in path:
            errors.append(
                f"'path' is a filesystem path and MUST contain at least one '/'; "
                f"use 'name' for docker volume names (got {path!r})"
            )
    extra = set(entry.keys()) - ALLOWED_ENTRY_KEYS
    if extra:
        errors.append(f"unknown key(s): {sorted(extra)}")
    nfs = entry.get("nfs")
    if nfs is not None:
        if not isinstance(nfs, dict):
            errors.append(f"'nfs' must be a mapping, got {type(nfs).__name__}")
        else:
            extra_nfs = set(nfs.keys()) - ALLOWED_NFS_KEYS
            if extra_nfs:
                errors.append(f"unknown nfs key(s): {sorted(extra_nfs)}")
    return errors


def _resolve_attr_path(spec: dict, parts: list[str]) -> bool:
    cursor: object = spec
    for part in parts:
        if not isinstance(cursor, dict):
            return False
        if part not in cursor:
            return False
        cursor = cursor[part]
    return True


def _allowed_attr_paths(entry: dict) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    if "name" in entry:
        paths.add(("name",))
    if "path" in entry:
        paths.add(("path",))
    nfs = entry.get("nfs")
    if isinstance(nfs, dict):
        paths.add(("nfs",))
        for key in nfs:
            paths.add(("nfs", key))
    return paths


class TestVolumesSchema(unittest.TestCase):
    def test_every_volumes_yml_entry_has_mandatory_name(self):
        files = _collect_volumes_files()
        self.assertTrue(files, "no meta/volumes.yml files found")
        offenders: list[str] = []
        for path in files:
            try:
                data = load_yaml_any(str(path))
            except yaml.YAMLError as exc:
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}: invalid YAML ({exc})"
                )
                continue
            if data is None:
                continue
            if not isinstance(data, dict):
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}: top-level must be a mapping"
                )
                continue
            for key, value in data.items():
                errs = _validate_entry(value)
                offenders.extend(
                    f"{path.relative_to(PROJECT_ROOT)}: volumes.{key}: {err}"
                    for err in errs
                )
        if offenders:
            self.fail(
                "meta/volumes.yml schema violations (every entry MUST be a "
                "mapping with a mandatory 'name' string; optional 'nfs' "
                "mapping accepts only uid/gid/mode):\n"
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
            if isinstance(data, dict):
                role_name = path.parent.parent.name
                per_role_schema[role_name] = {
                    k: v for k, v in data.items() if isinstance(v, dict)
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
