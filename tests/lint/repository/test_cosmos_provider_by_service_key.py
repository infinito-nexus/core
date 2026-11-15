from __future__ import annotations

import os
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT, iter_non_ignored_files, read_text
from utils.design.cosmos import SERVICE_KEY
from utils.roles.custom import MARKER_FILE, PREFIX
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

RULE = "cosmos-provider-by-service-key"
PROVIDER = f"{PREFIX}{SERVICE_KEY}"
EXEMPT_FILES = frozenset({"eslint.config.js", "meta/custom_roles.yml"})
EXEMPT_TREES = ("docs/requirements/", "tests/", f"roles/{PROVIDER}/")


def naming(entries: Iterable[tuple[str, str]]) -> list[str]:
    """
    Args:
        entries: ``(repository-relative POSIX path, content)`` of every file to check.

    Returns:
        The sorted paths outside the exempt files and trees whose content names
        the cosmos provider role. The provider's own tree is exempt, since a
        role names itself; every other role, pulled or in-tree, is checked.
    """
    return sorted(
        rel
        for rel, content in entries
        if rel not in EXEMPT_FILES
        and not rel.startswith(EXEMPT_TREES)
        and PROVIDER in content
    )


def repository() -> Iterator[tuple[str, str]]:
    """
    Returns:
        ``(repository-relative POSIX path, content)`` of every text file the
        project-tree scans read, placed custom roles included.
    """
    for path in iter_non_ignored_files():
        try:
            content = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        yield os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/"), content


class TestCosmosProviderByServiceKey(unittest.TestCase):
    def test_no_core_file_names_the_provider_role(self) -> None:
        offenders = naming(repository())
        self.assertEqual(
            offenders,
            [],
            f"[{RULE}] core reaches the cosmos provider only through the service "
            f"key '{SERVICE_KEY}' and the service registry, so it keeps working "
            f"with any role that registers the key and without one; these files "
            f"name '{PROVIDER}' instead: {', '.join(offenders)}",
        )

    def test_the_rule_flags_a_core_file_and_spares_the_exempt_ones(self) -> None:
        planted = f"src: /roles/{PROVIDER}/latest/js/cosmos.js"
        entries = [
            ("roles/web-svc-html/templates/head.j2", planted),
            ("eslint.config.js", planted),
            ("meta/custom_roles.yml", planted),
            (f"{EXEMPT_TREES[0]}cosmos.md", planted),
            ("tests/unit/python/utils/design/test_cosmos.py", planted),
            (f"roles/{PROVIDER}/{MARKER_FILE}", planted),
            (f"roles/{PROVIDER}/{ROLE_FILE_VARS_MAIN}", planted),
            (f"roles/{PREFIX}team/{ROLE_FILE_VARS_MAIN}", planted),
            (f"roles/web-app-{SERVICE_KEY}/{ROLE_FILE_VARS_MAIN}", planted),
            (
                f"roles/web-svc-design/{ROLE_FILE_META_SERVICES}",
                "cosmos:\n  enabled: true\n",
            ),
        ]
        self.assertEqual(
            naming(entries),
            [
                f"roles/web-app-{SERVICE_KEY}/{ROLE_FILE_VARS_MAIN}",
                f"roles/{PREFIX}team/{ROLE_FILE_VARS_MAIN}",
                "roles/web-svc-html/templates/head.j2",
            ],
        )


if __name__ == "__main__":
    unittest.main()
