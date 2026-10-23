"""Unit tests for the tools lane's address handoff.

The host resolves the runner's address and writes it down; a container of the
stack reads the file, because it cannot ask docker and the compose service
name resolves nowhere behind the stack's own CoreDNS.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.inventory import tools
from utils.inventory.tools import ADDRESS, LANE_SERVICE, lane_address, lane_ip

NETWORKS = {
    "infinito-nexus-core_default": {"IPAddress": "172.30.0.9"},
    "store-i18n_default": {"IPAddress": "172.30.5.2"},
}


def _completed(returncode: int, stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


class TestLaneIp(unittest.TestCase):
    def _run(self, found, env=None) -> str:
        environment = {"INFINITO_SUBNET": "172.30.5.0/24", "INFINITO_CONTAINER": "c"}
        with (
            patch.object(tools.subprocess, "run", return_value=found),
            patch(
                "utils.i18n.libretranslate.environment", return_value=env or environment
            ),
        ):
            return lane_ip(Path("/nowhere"))

    def test_the_address_inside_the_stack_subnet_wins(self) -> None:
        self.assertEqual(self._run(_completed(0, json.dumps(NETWORKS))), "172.30.5.2")

    def test_a_runner_docker_cannot_describe_answers_empty(self) -> None:
        self.assertEqual(self._run(_completed(1, "")), "")

    def test_output_that_is_not_json_answers_empty(self) -> None:
        self.assertEqual(self._run(_completed(0, "no such object")), "")

    def test_no_address_in_the_subnet_answers_empty(self) -> None:
        other = {"bridge": {"IPAddress": "172.17.0.2"}}
        self.assertEqual(self._run(_completed(0, json.dumps(other))), "")

    def test_a_missing_subnet_answers_empty(self) -> None:
        self.assertEqual(
            self._run(
                _completed(0, json.dumps(NETWORKS)), env={"INFINITO_CONTAINER": "c"}
            ),
            "",
        )


class TestLaneAddress(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ADDRESS).parent.mkdir(parents=True)

    def _write(self, body: str) -> None:
        (self.root / ADDRESS).write_text(body, encoding="utf-8")

    def test_a_written_address_is_read_back(self) -> None:
        self._write("172.30.5.2\n")
        self.assertEqual(lane_address(self.root), "172.30.5.2")

    def test_a_missing_file_falls_back_to_the_service_name(self) -> None:
        self.assertEqual(lane_address(self.root), LANE_SERVICE)

    def test_an_empty_file_falls_back_to_the_service_name(self) -> None:
        self._write("\n")
        self.assertEqual(lane_address(self.root), LANE_SERVICE)

    def test_remembering_an_unresolvable_address_writes_nothing(self) -> None:
        with patch.object(tools, "lane_ip", return_value=""):
            tools._remember_address(self.root)
        self.assertFalse((self.root / ADDRESS).exists())

    def test_remembering_a_resolved_address_makes_it_readable(self) -> None:
        with patch.object(tools, "lane_ip", return_value="172.30.5.2"):
            tools._remember_address(self.root)
        self.assertEqual(lane_address(self.root), "172.30.5.2")


if __name__ == "__main__":
    unittest.main()
