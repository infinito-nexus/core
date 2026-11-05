"""Audit: the unified addon syntax Current State Audit matches every role's addons.

Every role under ``roles/`` is classified by the ``mechanism`` values of its
``meta/addons/`` files, as ``db-extension`` when a ``meta/services.yml`` block
carries an engine ``extensions:`` list, or as ``none``. Each table row must
reproduce its role's mechanisms, addon count, required count and bridged
services, and the out-of-scope bullets must list exactly the db-extension roles.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.cache.addons import load_addons_dir
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

REQUIREMENT = PROJECT_ROOT / "docs" / "requirements" / "026-unified-addon-syntax.md"
_ROW = re.compile(r"^\| \[([^\]]+)\]\([^)]*\) \|(.*)\|\s*$")
_BULLET = re.compile(r"^- \[([^\]]+)\]\(")


def audit(roles_dir: Path) -> dict[str, dict]:
    """Returns, per role, its addons as id -> (mechanism, required, bridges) and its classes.

    Args:
        roles_dir: the repository's ``roles`` directory.
    """
    result: dict[str, dict] = {}
    for role_dir in sorted(path for path in roles_dir.iterdir() if path.is_dir()):
        addons = {
            addon_id: (
                str(spec.get("mechanism")),
                bool(spec.get("required")),
                tuple(spec.get("bridges") or ()),
            )
            for addon_id, spec in load_addons_dir(role_dir / "meta").items()
        }
        services = (
            load_yaml_any(
                str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
            )
            or {}
        )
        db_extension = any(
            isinstance(block, Mapping) and "extensions" in block
            for block in services.values()
        )
        classes = {mechanism for mechanism, _, _ in addons.values()} | (
            {"db-extension"} if db_extension else set()
        )
        result[role_dir.name] = {"addons": addons, "classes": classes or {"none"}}
    return result


def _ticked(cell: str) -> list[str]:
    return sorted(re.findall(r"`([^`]+)`", cell))


def table_problems(text: str, roles_dir: Path) -> list[str]:
    """Returns one line per audit row or out-of-scope bullet that the roles contradict.

    Args:
        text: the requirement's markdown.
        roles_dir: the repository's ``roles`` directory.
    """
    found = audit(roles_dir)
    section = text.split("## Current State Audit", 1)[1].split(
        "## Cross-Role Integration Matrix", 1
    )[0]
    audit_part, out_of_scope = section.split("### Out of scope", 1)
    problems: list[str] = []
    listed: set[str] = set()
    for match in filter(None, map(_ROW.match, audit_part.splitlines())):
        role = match.group(1)
        listed.add(role)
        if role not in found:
            problems.append(f"{role}: row names a role absent from roles/")
            continue
        addons = found[role]["addons"].values()
        expected = [
            sorted({mechanism for mechanism, _, _ in addons}),
            str(len(addons)),
            str(sum(required for _, required, _ in addons)),
            sorted({bridge for _, _, bridges in addons for bridge in bridges}),
        ]
        mechanisms, count, required, bridged = (
            cell.strip() for cell in match.group(2).split("|")
        )
        actual = [_ticked(mechanisms), count, required, _ticked(bridged)]
        if actual != expected:
            problems.append(f"{role}: row says {actual}, roles/ says {expected}")
    for role, entry in found.items():
        if entry["addons"] and role not in listed:
            problems.append(f"{role}: declares addons but has no audit row")
    bullets = {m.group(1) for m in map(_BULLET.match, out_of_scope.splitlines()) if m}
    db_roles = {
        role for role, entry in found.items() if "db-extension" in entry["classes"]
    }
    problems += [
        f"{role}: db-extension role missing from the out-of-scope list"
        for role in sorted(db_roles - bullets)
    ]
    problems += [
        f"{role}: listed out of scope but declares no extensions"
        for role in sorted(bullets - db_roles)
    ]
    return problems


class TestAddonsAudit(unittest.TestCase):
    def test_the_requirement_audit_reproduces_from_the_roles(self) -> None:
        problems = table_problems(read_text(str(REQUIREMENT)), PROJECT_ROOT / "roles")
        self.assertEqual([], problems, "\n".join(problems))

    def test_every_role_is_classified(self) -> None:
        found = audit(PROJECT_ROOT / "roles")
        self.assertEqual({"none"}, found["dsk-gnome-extensions"]["classes"])
        self.assertEqual(
            {"plugin", "theme", "db-extension"}, found["web-app-discourse"]["classes"]
        )
        self.assertIn("bridge", found["web-app-matrix"]["classes"])

    def test_a_stale_row_and_a_missing_role_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            addons_dir = roles_dir / "web-app-a" / ROLE_DIR_META_ADDONS
            addons_dir.mkdir(parents=True)
            (addons_dir / "x.yml").write_text(
                "mechanism: plugin\nrequired: true\nbridges: [sso]\n", encoding="utf-8"
            )
            services_file = roles_dir / "web-app-b" / ROLE_FILE_META_SERVICES
            services_file.parent.mkdir(parents=True)
            services_file.write_text(
                "postgres:\n  extensions: [pg_trgm]\n", encoding="utf-8"
            )
            text = (
                "## Current State Audit\n\n| Role | M | A | R | B |\n|---|---|---|---|---|\n"
                "| [web-app-a](x) | `plugin` | 1 | 0 | `sso` |\n"
                "| [web-app-gone](x) | none | 0 | 0 | none |\n\n"
                "### Out of scope\n\n- [web-app-c](x): stale.\n\n## Cross-Role Integration Matrix\n"
            )
            problems = table_problems(text, roles_dir)
        self.assertEqual(4, len(problems), problems)
        self.assertTrue(any(p.startswith("web-app-a: row says") for p in problems))
        self.assertTrue(any(p.startswith("web-app-gone:") for p in problems))
        self.assertTrue(any(p.startswith("web-app-b: db-extension") for p in problems))
        self.assertTrue(any(p.startswith("web-app-c: listed") for p in problems))


if __name__ == "__main__":
    unittest.main()
