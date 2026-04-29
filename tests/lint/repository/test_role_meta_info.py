"""Lint guard: roles/<role>/meta/info.yml conforms to req-011.

Per docs/requirements/011-role-meta-info-migration.md:

  * the file is OPTIONAL (a role with no descriptive metadata does not
    grow the file);
  * file-root convention: the file's content IS the value of
    ``applications.<role>.info`` — there is NO wrapping ``info:`` key;
  * allowed top-level keys: ``logo``, ``homepage``, ``video``, ``display``;
  * ``logo`` is a mapping with at least a string ``class:`` field;
  * ``homepage`` and ``video`` are non-empty strings;
  * ``display`` is a bool;
  * none of these four fields may reappear under
    ``meta/main.yml.galaxy_info``.

Caching: parsed YAML comes through the shared process-wide
``utils.cache.yaml.load_yaml_any`` cache, so multiple lint tests that
read the same ``meta/main.yml`` / ``meta/info.yml`` pay one parse.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml as _yaml

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any


ROLES_DIR = PROJECT_ROOT / "roles"

_ALLOWED_INFO_KEYS: frozenset[str] = frozenset({"logo", "homepage", "video", "display"})

_FORBIDDEN_GALAXY_INFO_KEYS: frozenset[str] = frozenset(
    {"logo", "homepage", "video", "display"}
)


def _meta_main_paths() -> list[Path]:
    if not ROLES_DIR.is_dir():
        return []
    return sorted(
        role_dir / "meta" / "main.yml"
        for role_dir in ROLES_DIR.iterdir()
        if role_dir.is_dir() and (role_dir / "meta" / "main.yml").is_file()
    )


def _meta_info_paths() -> list[Path]:
    if not ROLES_DIR.is_dir():
        return []
    return sorted(
        role_dir / "meta" / "info.yml"
        for role_dir in ROLES_DIR.iterdir()
        if role_dir.is_dir() and (role_dir / "meta" / "info.yml").is_file()
    )


def _validate_meta_info(path: Path) -> list[str]:
    try:
        parsed = load_yaml_any(str(path), default_if_missing={})
    except _yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]
    if parsed in (None, {}):
        return ["file is empty (delete the file or add at least one allowed field)"]
    if not isinstance(parsed, dict):
        return [f"top-level must be a mapping; got {type(parsed).__name__}"]

    problems: list[str] = []

    if "info" in parsed and isinstance(parsed.get("info"), dict):
        problems.append(
            "file uses an `info:` wrapper key — req-011 mandates the file-root "
            "convention (the file's content IS applications.<role>.info)"
        )

    unknown = sorted(set(parsed.keys()) - _ALLOWED_INFO_KEYS)
    if unknown:
        problems.append(
            "non-allowlisted top-level key(s): "
            + ", ".join(unknown)
            + f"; allowed: {sorted(_ALLOWED_INFO_KEYS)}"
        )

    if "logo" in parsed:
        logo = parsed["logo"]
        if not isinstance(logo, dict):
            problems.append("`logo` must be a mapping")
        elif "class" in logo and not isinstance(logo["class"], str):
            # Empty strings are intentionally allowed — several roles use
            # `class: ''` as a placeholder for "no icon yet"; the dashboard
            # consumer falls back to a default when the string is empty.
            problems.append("`logo.class`, when present, must be a string")

    for str_field in ("homepage", "video"):
        if str_field in parsed:
            value = parsed[str_field]
            if not isinstance(value, str) or not value.strip():
                problems.append(f"`{str_field}` must be a non-empty string")

    if "display" in parsed and not isinstance(parsed["display"], bool):
        problems.append("`display` must be a bool (true/false)")

    return problems


def _validate_meta_main_no_forbidden(path: Path) -> list[str]:
    try:
        parsed = load_yaml_any(str(path), default_if_missing={})
    except _yaml.YAMLError:
        return []  # main-galaxy-schema lint reports parse errors separately
    if not isinstance(parsed, dict):
        return []
    galaxy_info = parsed.get("galaxy_info")
    if not isinstance(galaxy_info, dict):
        return []
    found = sorted(_FORBIDDEN_GALAXY_INFO_KEYS.intersection(galaxy_info.keys()))
    if not found:
        return []
    return [
        "post-req-011 forbidden key(s) under galaxy_info: "
        + ", ".join(found)
        + " (move them to meta/info.yml)"
    ]


class TestMetaInfoShape(unittest.TestCase):
    """Enforce the meta/info.yml schema per req-011."""

    def test_meta_info_files_are_well_shaped(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _meta_info_paths():
            problems = _validate_meta_info(path)
            if problems:
                offenders[path] = problems

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [f"{len(offenders)} meta/info.yml file(s) violate req-011:"]
        for path, problems in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            for problem in problems:
                lines.append(f"      * {problem}")
        self.fail("\n".join(lines))


class TestMetaMainHasNoMigratedFields(unittest.TestCase):
    """galaxy_info MUST NOT carry the four fields after req-011."""

    def test_no_forbidden_keys_in_galaxy_info(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _meta_main_paths():
            problems = _validate_meta_main_no_forbidden(path)
            if problems:
                offenders[path] = problems

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} meta/main.yml file(s) still carry post-req-011 "
            f"forbidden keys under galaxy_info:"
        ]
        for path, problems in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            for problem in problems:
                lines.append(f"      * {problem}")
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
