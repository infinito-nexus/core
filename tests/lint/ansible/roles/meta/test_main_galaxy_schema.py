"""Lint guard: roles/<role>/meta/main.yml MUST conform to the Ansible Galaxy
schema AND to the project's canonical exact-values for ``company`` and
``platforms``.

Background
==========

`meta/main.yml` is the only file under ``meta/`` that Ansible auto-loads. Per
the Galaxy spec (https://docs.ansible.com/ansible/latest/galaxy/dev_guide.html
and https://galaxy.ansible.com/docs/contributing/creating_role.html) it has a
fixed set of allowed top-level keys (``galaxy_info``, ``dependencies``,
``collections``, ``argument_specs``, ``allow_duplicates``) and a fixed set of
allowed sub-keys under ``galaxy_info``.

Galaxy silently ignores unknown keys, which historically tempted us to bury
project-internal metadata (``run_after`` / ``lifecycle``, plus ``logo`` /
``video`` / ``homepage`` / ``repository`` / ``documentation`` /
``license_url``) under ``galaxy_info:``. Those non-Galaxy fields belong in
project-owned files (``meta/services.yml.<entity>``), not in the Galaxy slot.

On top of the generic schema this lint also enforces two project-wide
canonical exact-values to stop drift: ``galaxy_info.company`` is one
specific block-scalar string (Kevin Veen-Birkenbach /
https://www.veen.world) and ``galaxy_info.platforms`` is one specific
5-distro list (ArchLinux/Debian/EL/Fedora/Ubuntu, each ``versions:
[all]``). Both fields had accumulated ~10 variants each (quoting style,
Unicode hyphen, typos, ``Linux``/``GenericLinux``/``Any`` platform names)
before standardisation. The two-line company form keeps the parsed value
under Galaxy's 50-character limit on ``company`` so galaxy-importer
accepts it.

This lint fails as soon as any role's ``meta/main.yml`` carries a key the
Galaxy schema does not define, omits a required field, or drifts from one
of the two canonical exact-values.

Caching
=======

YAML parsing is the bottleneck on a 250+ role tree. Parses go through
the shared process-wide ``utils.cache.yaml.load_yaml_any`` cache so
multiple lint tests that touch the same ``meta/main.yml`` file pay one
parse.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

import yaml as _yaml

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"


_ALLOWED_TOPLEVEL: frozenset[str] = frozenset(
    {
        "galaxy_info",
        "dependencies",
        "collections",
        "argument_specs",
        "allow_duplicates",
    }
)

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

_REQUIRED_GALAXY_INFO: frozenset[str] = frozenset(
    {
        "author",
        "description",
        "license",
        "min_ansible_version",
        "platforms",
    }
)

_CANONICAL_COMPANY: str = "Kevin Veen-Birkenbach\nhttps://www.veen.world\n"

_CANONICAL_PLATFORMS: list[dict[str, Any]] = [
    {"name": "ArchLinux", "versions": ["all"]},
    {"name": "Debian", "versions": ["all"]},
    {"name": "EL", "versions": ["all"]},
    {"name": "Fedora", "versions": ["all"]},
    {"name": "Ubuntu", "versions": ["all"]},
]


def _meta_main_paths() -> list[Path]:
    if not ROLES_DIR.is_dir():
        return []
    return sorted(
        role_dir / ROLE_FILE_META_MAIN
        for role_dir in ROLES_DIR.iterdir()
        if role_dir.is_dir() and (role_dir / ROLE_FILE_META_MAIN).is_file()
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

    if "platforms" in galaxy_info:
        platforms_val = galaxy_info["platforms"]
        problems.extend(_validate_platforms(platforms_val))
        if platforms_val != _CANONICAL_PLATFORMS:
            problems.append(
                "galaxy_info.platforms differs from canonical 5-distro list "
                "(ArchLinux/Debian/EL/Fedora/Ubuntu, each versions: [all]); "
                f"got {platforms_val!r}"
            )

    if "company" in galaxy_info and galaxy_info["company"] != _CANONICAL_COMPANY:
        problems.append(
            "galaxy_info.company differs from canonical block-scalar value "
            "(Kevin Veen-Birkenbach / "
            f"https://www.veen.world); got {galaxy_info['company']!r}"
        )

    if "galaxy_tags" in galaxy_info:
        problems.extend(_validate_galaxy_tags(galaxy_info["galaxy_tags"]))

    problems.extend(
        f"galaxy_info.{str_field} must be a string"
        for str_field in ("author", "description", "license", "company")
        if str_field in galaxy_info and (not isinstance(galaxy_info[str_field], str))
    )

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
            (
                f"{len(offenders)} role meta/main.yml file(s) violate the Ansible "
                f"Galaxy schema:"
            ),
        ]
        for path, problems in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            lines.extend(f"      * {problem}" for problem in problems)
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
