"""The mesh CLI as the swarm routine invokes it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.mesh.__main__ import main

from .test_write import (
    BACKUP_INVENTORY,
    CLUSTER_INVENTORY,
    GROUP_VARS,
    HOSTS,
    VAULT_PASSWORD,
)


class TestMeshCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.host_vars = root / "host_vars"
        self.host_vars.mkdir()
        for host in HOSTS:
            (self.host_vars / f"{host}.yml").write_text("---\n", encoding="utf-8")
        self.cluster = root / "devices.yml"
        self.cluster.write_text(CLUSTER_INVENTORY, encoding="utf-8")
        self.backup = root / "backup.yml"
        self.backup.write_text(BACKUP_INVENTORY, encoding="utf-8")
        self.vault_file = root / ".password"
        self.vault_file.write_text(VAULT_PASSWORD, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _text(self, host: str) -> str:
        path = self.host_vars / f"{host}.yml"
        return path.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read  tempdir fixture rewritten between reads in one test

    def _argv(self, *extra: str) -> list[str]:
        return [
            "--inventory",
            str(self.cluster),
            "--inventory",
            str(self.backup),
            "--host-vars-dir",
            str(self.host_vars),
            "--vault-password-file",
            str(self.vault_file),
            "--group-vars-file",
            str(GROUP_VARS),
            *extra,
        ]

    def test_one_invocation_writes_every_member(self):
        self.assertEqual(main(self._argv()), 0)
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertIn("$ANSIBLE_VAULT", self._text(host))

    def test_a_missing_host_vars_dir_fails_rather_than_writing_nothing(self):
        argv = self._argv()
        argv[argv.index("--host-vars-dir") + 1] = str(self.host_vars / "absent")
        self.assertEqual(main(argv), 1)

    def test_an_unknown_mesh_name_fails(self):
        self.assertEqual(main(self._argv("--mesh", "no-such-mesh")), 1)

    def test_restricting_to_one_mesh_leaves_the_other_unwritten(self):
        self.assertEqual(main(self._argv("--mesh", "swarm")), 0)
        self.assertNotIn("data:", self._text("nfs-server"))

    def test_a_rerun_is_a_no_op(self):
        self.assertEqual(main(self._argv()), 0)
        before = {host: self._text(host) for host in HOSTS}
        self.assertEqual(main(self._argv()), 0)
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self._text(host), before[host])
