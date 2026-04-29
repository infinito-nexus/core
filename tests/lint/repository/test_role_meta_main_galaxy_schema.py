"""Lint guard: roles/<role>/meta/main.yml MUST conform to the Ansible Galaxy
schema.

Background
==========

`meta/main.yml` is the only file under ``meta/`` that Ansible auto-loads. Per
the Galaxy spec (https://docs.ansible.com/ansible/latest/galaxy/dev_guide.html
and https://galaxy.ansible.com/docs/contributing/creating_role.html) it has a
fixed set of allowed top-level keys (``galaxy_info``, ``dependencies``,
``collections``, ``argument_specs``, ``allow_duplicates``) and a fixed set of
allowed sub-keys under ``galaxy_info``.

Galaxy silently ignores unknown keys, which historically tempted us to bury
project-internal metadata (``run_after`` / ``lifecycle`` — migrated out by
req-010, plus ``logo`` / ``video`` / ``homepage`` / ``repository`` /
``documentation`` / ``license_url``) under ``galaxy_info:``. Those non-Galaxy
fields belong in project-owned files (``meta/services.yml.<entity>``), not in
the Galaxy slot.

This lint fails as soon as any role's ``meta/main.yml`` carries a key the
Galaxy schema does not define.

Caching
=======

YAML parsing is the bottleneck on a 250+ role tree. Parses go through
the shared process-wide ``utils.cache.yaml.load_yaml_any`` cache so
multiple lint tests that touch the same ``meta/main.yml`` file pay one
parse.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml as _yaml

from utils.annotations.message import warning
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any


ROLES_DIR = PROJECT_ROOT / "roles"


# Ansible Galaxy spec — top-level keys allowed in meta/main.yml.
_ALLOWED_TOPLEVEL: frozenset[str] = frozenset(
    {
        "galaxy_info",
        "dependencies",
        "collections",
        "argument_specs",
        "allow_duplicates",
    }
)

# Ansible Galaxy spec — sub-keys allowed under galaxy_info.
_ALLOWED_GALAXY_INFO: frozenset[str] = frozenset(
    {
        "role_name",
        "namespace",
        "author",
        "description",
        "company",
        "license",
        "min_ansible_version",
        "min_ansible_container_version",
        "platforms",
        "galaxy_tags",
        "issue_tracker_url",
        "github_branch",
        "standalone",
    }
)

# Hard-required galaxy_info fields. Missing any of these fails the lint.
# Kept tight on purpose: these three carry documentation value for every
# internal role.
_REQUIRED_GALAXY_INFO: frozenset[str] = frozenset(
    {
        "author",
        "description",
        "license",
    }
)

# Soft-recommended galaxy_info fields. Required by Ansible Galaxy when
# *publishing* a role, but Infinito.Nexus does not publish to Galaxy, so
# missing these is reported as a GitHub Actions ::warning:: annotation
# (via utils.annotations.message) instead of a hard test failure. Roles
# that DO carry the field are still validated for shape via
# `_validate_platforms` / the type checks below.
_RECOMMENDED_GALAXY_INFO: frozenset[str] = frozenset(
    {
        "min_ansible_version",
        "platforms",
    }
)


def _meta_main_paths() -> list[Path]:
    if not ROLES_DIR.is_dir():
        return []
    return sorted(
        role_dir / "meta" / "main.yml"
        for role_dir in ROLES_DIR.iterdir()
        if role_dir.is_dir() and (role_dir / "meta" / "main.yml").is_file()
    )


def _validate_platforms(platforms: Any) -> list[str]:
    """Return a list of human-readable problems with the platforms block."""
    problems: list[str] = []
    if not isinstance(platforms, list) or not platforms:
        return ["platforms must be a non-empty list"]
    for idx, entry in enumerate(platforms):
        if not isinstance(entry, dict):
            problems.append(f"platforms[{idx}] must be a mapping")
            continue
        if "name" not in entry or not isinstance(entry["name"], str):
            problems.append(f"platforms[{idx}] missing string 'name'")
        if "versions" in entry and not isinstance(entry["versions"], list):
            problems.append(f"platforms[{idx}].versions must be a list when present")
    return problems


def _validate_galaxy_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return ["galaxy_tags must be a list of strings"]
    problems: list[str] = []
    for idx, tag in enumerate(tags):
        if not isinstance(tag, str) or not tag.strip():
            problems.append(f"galaxy_tags[{idx}] must be a non-empty string")
    return problems


def _validate_dependencies(deps: Any) -> list[str]:
    if not isinstance(deps, list):
        return ["dependencies must be a list"]
    problems: list[str] = []
    for idx, dep in enumerate(deps):
        if isinstance(dep, str):
            if not dep.strip():
                problems.append(f"dependencies[{idx}] must be a non-empty string")
            continue
        if isinstance(dep, dict):
            if "role" not in dep and "name" not in dep:
                problems.append(
                    f"dependencies[{idx}] mapping must define 'role' or 'name'"
                )
            continue
        problems.append(f"dependencies[{idx}] must be a string or mapping")
    return problems


def _validate_meta_main(path: Path) -> list[str]:
    """Return a list of human-readable problems for one meta/main.yml file."""
    try:
        parsed = load_yaml_any(str(path), default_if_missing={})
    except _yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]
    if parsed in (None, {}):
        return ["file is empty (no galaxy_info block)"]
    if not isinstance(parsed, dict):
        return [f"top-level must be a mapping; got {type(parsed).__name__}"]

    problems: list[str] = []

    unknown_top = sorted(set(parsed.keys()) - _ALLOWED_TOPLEVEL)
    if unknown_top:
        problems.append("non-Galaxy top-level key(s): " + ", ".join(unknown_top))

    galaxy_info = parsed.get("galaxy_info")
    if not isinstance(galaxy_info, dict):
        problems.append("missing or non-mapping 'galaxy_info' block")
        return problems

    unknown_gi = sorted(set(galaxy_info.keys()) - _ALLOWED_GALAXY_INFO)
    if unknown_gi:
        problems.append("non-Galaxy galaxy_info sub-key(s): " + ", ".join(unknown_gi))

    missing_required = sorted(_REQUIRED_GALAXY_INFO - set(galaxy_info.keys()))
    if missing_required:
        problems.append(
            "missing required galaxy_info field(s): " + ", ".join(missing_required)
        )

    missing_recommended = sorted(_RECOMMENDED_GALAXY_INFO - set(galaxy_info.keys()))
    if missing_recommended:
        rel_path = path.relative_to(PROJECT_ROOT)
        warning(
            "missing Galaxy-publishing recommended field(s): "
            + ", ".join(missing_recommended),
            title="meta/main.yml galaxy_info",
            file=str(rel_path),
        )

    if "platforms" in galaxy_info:
        problems.extend(_validate_platforms(galaxy_info["platforms"]))

    if "galaxy_tags" in galaxy_info:
        problems.extend(_validate_galaxy_tags(galaxy_info["galaxy_tags"]))

    for str_field in ("author", "description", "license", "company"):
        if str_field in galaxy_info and not isinstance(galaxy_info[str_field], str):
            problems.append(f"galaxy_info.{str_field} must be a string")

    if "min_ansible_version" in galaxy_info:
        val = galaxy_info["min_ansible_version"]
        if not isinstance(val, (str, float, int)):
            problems.append(
                "galaxy_info.min_ansible_version must be a string or number"
            )

    if "dependencies" in parsed:
        problems.extend(_validate_dependencies(parsed["dependencies"]))

    return problems


class TestRoleMetaMainGalaxySchema(unittest.TestCase):
    """All ``roles/<role>/meta/main.yml`` files MUST conform to Galaxy schema."""

    def test_meta_main_files_are_galaxy_conformant(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _meta_main_paths():
            problems = _validate_meta_main(path)
            if problems:
                offenders[path] = problems

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} role meta/main.yml file(s) violate the Ansible "
            f"Galaxy schema:",
        ]
        for path, problems in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            for problem in problems:
                lines.append(f"      * {problem}")
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
