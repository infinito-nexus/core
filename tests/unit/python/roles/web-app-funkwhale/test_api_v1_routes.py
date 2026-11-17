from __future__ import annotations

import os
import re
import unittest

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-funkwhale"
FUNKWHALE_2_V1_ROUTES = frozenset({"channels", "instance", "listen", "oauth"})
V1_ROUTE = re.compile(r"api/v1/([A-Za-z0-9_-]+)")


def _v1_references() -> list[tuple[str, str]]:
    """
    Returns:
        (role-relative path, first path segment) of every api/v1/ reference the role ships.
    """
    prefix = str(ROLE) + os.sep
    return [
        (os.path.relpath(path, ROLE), route)
        for path, content in iter_project_files_with_content(exclude_tests=True)
        if path.startswith(prefix)
        for route in V1_ROUTE.findall(content)
    ]


class TestApiV1Routes(unittest.TestCase):
    def test_the_scan_sees_the_api_healthcheck_path(self) -> None:
        self.assertIn(
            ("meta/services.yml", "instance"),
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
