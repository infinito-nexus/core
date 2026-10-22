from __future__ import annotations

import argparse
import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development import recreate

_CONFIG = json.dumps(
    {"name": "infinito-nexus-core", "networks": {"default": {"name": "core_default"}}}
)
_ROWS = (
    "infinito_nexus_debian\tinfinito-nexus-core\n"
    "infinito_nexus_fix_a\tfix-a\n"
    "infinito-coredns\tinfinito-nexus-core\n"
    "infinito_nexus_feature_b\tfeature-b\n"
)


class TestForeignEndpoints(unittest.TestCase):
    def test_keeps_only_other_projects(self) -> None:
        self.assertEqual(
            ["infinito_nexus_fix_a", "infinito_nexus_feature_b"],
            recreate.foreign_endpoints(_ROWS, "infinito-nexus-core"),
        )


class TestHandler(unittest.TestCase):
    def _run(self, up_rc: int) -> tuple[int, list[tuple[str, ...]]]:
        calls: list[tuple[str, ...]] = []
        compose = MagicMock()

        def compose_run(args, **_kwargs):
            calls.append(("compose", *args))
            return subprocess.CompletedProcess(args, 0, stdout=_CONFIG)

        def docker(*args, capture=False):
            calls.append(("docker", *args))
            return _ROWS if capture else ""

        def up(_args):
            calls.append(("up",))
            return up_rc

        compose.run.side_effect = compose_run
        with (
            patch.object(recreate, "make_compose", return_value=compose),
            patch.object(recreate, "_docker", side_effect=docker),
            patch.object(recreate, "up_handler", side_effect=up),
        ):
            rc = recreate.handler(argparse.Namespace())
        return rc, calls

    def test_detaches_recreates_without_volumes_and_reattaches(self) -> None:
        rc, calls = self._run(up_rc=0)

        self.assertEqual(0, rc)
        self.assertEqual(
            [
                (
                    "docker",
                    "network",
                    "disconnect",
                    "core_default",
                    "infinito_nexus_fix_a",
                ),
                (
                    "docker",
                    "network",
                    "disconnect",
                    "core_default",
                    "infinito_nexus_feature_b",
                ),
                ("compose", "down", "--remove-orphans"),
                ("up",),
                (
                    "docker",
                    "network",
                    "connect",
                    "core_default",
                    "infinito_nexus_fix_a",
                ),
                (
                    "docker",
                    "network",
                    "connect",
                    "core_default",
                    "infinito_nexus_feature_b",
                ),
            ],
            [
                c
                for c in calls
                if c[:2] != ("compose", "config") and c[:2] != ("docker", "ps")
            ],
        )

    def test_failed_up_leaves_foreign_stacks_detached_and_reports(self) -> None:
        rc, calls = self._run(up_rc=3)

        self.assertEqual(3, rc)
        self.assertNotIn(
            "connect", [c[2] for c in calls if c[:2] == ("docker", "network")]
        )


if __name__ == "__main__":
    unittest.main()
