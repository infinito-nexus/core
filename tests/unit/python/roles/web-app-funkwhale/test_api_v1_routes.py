from __future__ import annotations

import os
import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator

ROLE = PROJECT_ROOT / "roles" / "web-app-funkwhale"
FUNKWHALE_2_V1_ROUTES = frozenset({"channels", "instance", "listen", "oauth"})
V1_ROUTE = re.compile(r"api/v1/([A-Za-z0-9_-]+)")


def _role_texts() -> Iterator[tuple[str, str]]:
    """
    Returns:
        (absolute path, content) of every UTF-8 file the role ships; only the
        role's own files are read.
    """
    prefix = str(ROLE) + os.sep
    for path in iter_project_files(exclude_tests=True):
        if not path.startswith(prefix):
            continue
        try:
            yield path, read_text(path)
        except (OSError, UnicodeDecodeError):
            continue


def _v1_references() -> list[tuple[str, str]]:
    """
    Returns:
        (role-relative path, first path segment) of every api/v1/ reference the role ships.
    """
    return [
        (os.path.relpath(path, ROLE), route)
        for path, content in _role_texts()
        for route in V1_ROUTE.findall(content)
    ]


class TestApiV1Routes(unittest.TestCase):
    def test_the_scan_sees_the_api_healthcheck_path(self) -> None:  # nocheck: test.text-presence -- non-vacuity check of the role-wide api/v1 route scan  # fmt: skip
        self.assertIn(
            (ROLE_FILE_META_SERVICES, "instance"),
            _v1_references(),
        )

    def test_every_v1_reference_names_a_route_funkwhale_2_still_serves(
        self,
    ) -> None:
        stale = sorted(
            f"{path}: api/v1/{route}/"
            for path, route in _v1_references()
            if route not in FUNKWHALE_2_V1_ROUTES
        )
        self.assertEqual([], stale)


if __name__ == "__main__":
    unittest.main()
