"""Lint: a task file installing packages stays inside its declaring role.

``package_install`` resolves the id against the *including* role, not the role
that owns the file. So when role A includes a task file from role B, every id
B installs must be declared by A or in the shared root registry — otherwise
the ownership guard in ``plugins/action/package_install.py`` aborts the play,
and it does so at deploy time rather than here.

That is exactly how ``web-app-mailu`` broke: it includes
``sys-svc-mail-smtp/tasks/disable.yml`` to drop postfix when external SMTP is
configured, while only ``sys-svc-mail-smtp`` declared the id. The fix is to
move such an id into the root ``meta/packages.yml``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_PACKAGE_ID_RE = re.compile(
    r"package_install:\s*\n\s+id:\s*[\"']?(?P<id>[A-Za-z0-9_.+-]+)"
)
_CROSS_ROLE_INCLUDE_RE = re.compile(
    r"roles/(?P<role>[a-z0-9-]+)/(?:tasks|handlers)/(?P<rel>[\w/.-]+\.yml)"
)


def _role_of(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT / "roles").parts[0]


def _role_files() -> list[Path]:
    return [
        Path(candidate)
        for candidate in iter_project_files(extensions=(".yml",))
        if str(candidate).startswith(str(PROJECT_ROOT / "roles"))
        and ("/tasks/" in str(candidate) or "/handlers/" in str(candidate))
    ]


def _shared_ids() -> set[str]:
    shared = load_yaml_any(str(PROJECT_ROOT / "meta" / "packages.yml")) or {}
    return set(shared) if isinstance(shared, dict) else set()


def _installed_ids_by_file(files: list[Path]) -> dict[Path, set[str]]:
    installed: dict[Path, set[str]] = {}
    for path in files:
        ids = {m.group("id") for m in _PACKAGE_ID_RE.finditer(read_text(str(path)))}
        if ids:
            installed[path] = ids
    return installed


def _declared_ids_by_role() -> dict[str, set[str]]:
    declared: dict[str, set[str]] = {}
    for candidate in iter_project_files(extensions=(".yml",)):
        path = Path(candidate)
        if path.name != "packages.yml" or "/meta/" not in str(path):
            continue
        if not str(path).startswith(str(PROJECT_ROOT / "roles")):
            continue
        content = load_yaml_any(str(path)) or {}
        if isinstance(content, dict):
            declared[_role_of(path)] = set(content)
    return declared


class TestPackageCrossRoleInclude(unittest.TestCase):
    def test_included_task_files_only_install_reachable_ids(self) -> None:
        files = _role_files()
        installed = _installed_ids_by_file(files)
        declared = _declared_ids_by_role()
        shared = _shared_ids()

        offenders: list[str] = []
        for path in files:
            including_role = _role_of(path)
            text = read_text(str(path))
            for match in _CROSS_ROLE_INCLUDE_RE.finditer(text):
                target_role = match.group("role")
                if target_role == including_role:
                    continue
                target = (
                    PROJECT_ROOT / "roles" / target_role / "tasks" / match.group("rel")
                )
                ids = installed.get(target)
                if not ids:
                    target = (
                        PROJECT_ROOT
                        / "roles"
                        / target_role
                        / "handlers"
                        / match.group("rel")
                    )
                    ids = installed.get(target)
                if not ids:
                    continue
                unreachable = sorted(
                    i
                    for i in ids
                    if i not in shared and i not in declared.get(including_role, set())
                )
                if unreachable:
                    rel = path.relative_to(PROJECT_ROOT)
                    offenders.append(
                        f"{rel}: includes {target_role}'s task file, which installs "
                        f"{', '.join(unreachable)}"
                    )

        if not offenders:
            return

        self.fail(
            f"{len(offenders)} cross-role include(s) install a package id the "
            "including role cannot reach. package_install resolves ids against "
            "the including role, so move the id into the root meta/packages.yml "
            "when more than one role needs it:\n"
            + "\n".join(f"  - {o}" for o in offenders)
        )


if __name__ == "__main__":
    unittest.main()
