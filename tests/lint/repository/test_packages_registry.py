"""Lint: the package registry is a single point of truth.

Declarations live in the repository-root ``meta/packages.yml`` when more
than one role or an inventory bundle installs them, and in a role's own
``meta/packages.yml`` when only that role does. Six rules hold that split
together:

* a logical package id is declared exactly once repository-wide;
* one concrete distro package name belongs to exactly one id;
* a role installs only its own ids or shared ones;
* every id resolves for all five default distributions;
* an empty mapping carries a ``nocheck`` justification;
* every id an inventory lists in ``PACKAGES`` is actually declared.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path

from utils.cache.files import iter_project_files, read_text
from utils.packages.registry import (
    build_registry,
    iter_inventory_package_lists,
    iter_package_files,
    load_declarations,
    resolve,
)
from utils.packages.schema import DISTRO_FAMILY, INVENTORY_PACKAGES_VAR

from . import PROJECT_ROOT

_EMPTY_ENTRY_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_.-]+):\s*\[\s*\]\s*(?P<rest>.*)$")
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*(?P<reason>\S.*)$")
_ID_RE = re.compile(
    r"^\s*(?:id:\s*(?P<inline>[A-Za-z0-9_.-]+)|-\s*(?P<item>[A-Za-z0-9_.-]+))\s*$"
)


def _role_task_files() -> list[Path]:
    roles = str(PROJECT_ROOT / "roles")
    return [
        Path(path)
        for path in iter_project_files(extensions=(".yml",))
        if str(path).startswith(roles)
        and ("/tasks/" in str(path) or "/handlers/" in str(path))
    ]


def _installed_ids(path: Path) -> set[str]:
    """Package ids a task file passes to ``package_install``."""
    ids: set[str] = set()
    lines = read_text(str(path)).splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^\s*package_install:\s*$", line):
            continue
        base = len(line) - len(line.lstrip())
        for follower in lines[index + 1 :]:
            if follower.strip() and len(follower) - len(follower.lstrip()) <= base:
                break
            match = _ID_RE.match(follower)
            if match:
                ids.add(match.group("inline") or match.group("item"))
    return ids


class TestPackagesRegistry(unittest.TestCase):
    def test_package_ids_are_declared_once(self) -> None:
        seen: dict[str, list[str]] = defaultdict(list)
        for declaration in load_declarations(PROJECT_ROOT):
            rel = declaration.path.relative_to(PROJECT_ROOT)
            seen[declaration.package_id].append(str(rel))

        offenders = {pid: paths for pid, paths in seen.items() if len(paths) > 1}
        if not offenders:
            return

        lines = [
            (
                f"{len(offenders)} package id(s) are declared in more than one "
                "meta/packages.yml. That is a missing SPOT: declare the package "
                "once, in the root meta/packages.yml when more than one role "
                "needs it."
            )
        ]
        for pid, paths in sorted(offenders.items()):
            lines.append(f"  - {pid}:")
            lines.extend(f"      * {path}" for path in sorted(paths))
        self.fail("\n".join(lines))

    def test_one_distro_package_belongs_to_one_id(self) -> None:
        owners: dict[tuple[str, str], set[str]] = defaultdict(set)
        for package_id, declaration in build_registry(PROJECT_ROOT).items():
            for distro in DISTRO_FAMILY:
                spec = resolve(declaration, distro)
                if spec is None:
                    continue
                for name in spec.names:
                    owners[(distro, name)].add(f"{package_id} ({declaration.owner})")

        offenders = {key: ids for key, ids in owners.items() if len(ids) > 1}
        if not offenders:
            return

        lines = [
            (
                f"{len(offenders)} distro package(s) are declared under more than "
                "one id. Two ids installing the same package means one of them is "
                "redundant: keep a single id and reference it from both places."
            )
        ]
        for (distro, name), ids in sorted(offenders.items()):
            lines.append(f"  - {name} on {distro}: {', '.join(sorted(ids))}")
        self.fail("\n".join(lines))

    def test_roles_only_install_own_or_shared_ids(self) -> None:
        registry = build_registry(PROJECT_ROOT)
        offenders: list[str] = []

        for path in _role_task_files():
            role = path.relative_to(PROJECT_ROOT / "roles").parts[0]
            for package_id in _installed_ids(path):
                declaration = registry.get(package_id)
                if declaration is None or declaration.shared:
                    continue
                if declaration.role == role:
                    continue
                rel = path.relative_to(PROJECT_ROOT)
                offenders.append(
                    f"{rel}: installs '{package_id}', which {declaration.role} declares"
                )

        if not offenders:
            return

        self.fail(
            f"{len(offenders)} task(s) install an id another role owns. A role "
            "installs only ids from its own meta/packages.yml or from the shared "
            "root meta/packages.yml. Move the package to the root file when more "
            "than one role needs it:\n" + "\n".join(f"  - {o}" for o in offenders)
        )

    def test_every_package_covers_all_default_distros(self) -> None:
        offenders: dict[str, list[str]] = {}
        for package_id, declaration in sorted(build_registry(PROJECT_ROOT).items()):
            missing = [
                distro
                for distro in sorted(DISTRO_FAMILY)
                if resolve(declaration, distro) is None
            ]
            if missing:
                rel = declaration.path.relative_to(PROJECT_ROOT)
                offenders[f"{package_id} ({rel})"] = missing

        if not offenders:
            return

        lines = [
            (
                f"{len(offenders)} package(s) do not resolve for every default "
                f"distribution ({', '.join(sorted(DISTRO_FAMILY))}). Add the "
                "missing os_family key, or an empty list with a nocheck "
                "justification when nothing is installed there."
            )
        ]
        for entry, missing in sorted(offenders.items()):
            lines.append(f"  - {entry}: missing {', '.join(missing)}")
        self.fail("\n".join(lines))

    def test_empty_entries_carry_a_nocheck_reason(self) -> None:
        offenders: list[str] = []
        for _role, path in iter_package_files(PROJECT_ROOT):
            rel = path.relative_to(PROJECT_ROOT)
            for number, line in enumerate(read_text(str(path)).splitlines(), start=1):
                match = _EMPTY_ENTRY_RE.match(line)
                if not match:
                    continue
                reason = _NOCHECK_RE.search(match.group("rest") or "")
                if reason is None or not reason.group("reason").strip():
                    offenders.append(
                        f"{rel}:{number}: '{match.group('key')}' is empty without "
                        "a '# nocheck: <reason>' justification"
                    )

        if offenders:
            self.fail(
                f"{len(offenders)} empty package mapping(s) are unjustified. An "
                "empty list means 'deliberately nothing to install here' and MUST "
                "say why:\n" + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_inventory_packages_are_declared_ids(self) -> None:
        registry = build_registry(PROJECT_ROOT)
        offenders: list[str] = []
        for path, package_ids in iter_inventory_package_lists(PROJECT_ROOT):
            rel = path.relative_to(PROJECT_ROOT)
            offenders.extend(
                f"{rel}: '{package_id}' is declared nowhere"
                for package_id in package_ids
                if package_id not in registry
            )

        if offenders:
            self.fail(
                f"{len(offenders)} {INVENTORY_PACKAGES_VAR} entr(ies) name no "
                "declared package id, so the deploy would fail on them. Every "
                "entry must be an id from the root meta/packages.yml or from a "
                "role's meta/packages.yml:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
