"""The nested MDAD daemon bounds every container's open-files limit.

containerd inside the matrix-mdad runner runs with LimitNOFILE=infinity, so a
container without its own ``--ulimit`` inherits 2147483584 open files. Anything
that sizes a table from that limit, as uwsgi did in CI run 42239638356, pins
gigabytes; dockerd also refuses to start on a non-integer limit.
"""

from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_VARS_MAIN = PROJECT_ROOT / "roles/web-app-matrix" / ROLE_FILE_VARS_MAIN
_FLOOR = 65536
_CEILING = 1 << 20


class TestMdadDaemonNofile(unittest.TestCase):
    def test_every_nested_container_gets_a_bounded_integer_limit(self) -> None:
        nofile = load_yaml(_VARS_MAIN)["MATRIX_MDAD_DAEMON_JSON"]["default-ulimits"][
            "nofile"
        ]
        self.assertEqual(nofile["Name"], "nofile")
        for key in ("Soft", "Hard"):
            with self.subTest(key=key):
                self.assertIs(type(nofile[key]), int)
                self.assertGreaterEqual(nofile[key], _FLOOR)
                self.assertLessEqual(nofile[key], _CEILING)
        self.assertLessEqual(nofile["Soft"], nofile["Hard"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
