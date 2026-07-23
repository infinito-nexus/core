"""Unit tests for roles/svc-bkp-secrets-2-local/files/recover.py: the domain
+ target map, and the ``main()`` flow that restores only the subtrees present
in a snapshot, runs the pre-recover backup unit at most once, and gates the
node-identity restore behind --restore-node-identity."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.paths import DIR_SECRETS

from . import PROJECT_ROOT

RECOVER = PROJECT_ROOT / "roles" / "svc-bkp-secrets-2-local" / "files" / "recover.py"


def _load():
    spec = importlib.util.spec_from_file_location("secrets_recover", RECOVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SecretsRecoverTests(unittest.TestCase):
    def test_unit_pattern(self):
        self.assertEqual(
            _load().SecretsRecovery.unit_pattern, "svc-bkp-secrets-2-local*.service"
        )

    def test_software_domain_is_lowercased_nonempty(self):
        domain = _load()._software_domain()
        self.assertTrue(domain)
        self.assertEqual(domain, domain.lower())

    def test_targets_map_uses_domain_for_ca(self):
        targets = _load()._targets("example")
        self.assertEqual(targets["secrets"], str(DIR_SECRETS))
        self.assertEqual(targets["ca"], "/etc/example/ca")
        self.assertEqual(targets["acme"], "/etc/letsencrypt")
        self.assertEqual(targets["certbot"], "/etc/certbot")

    def _tmp_targets(self, td: str) -> dict[str, str]:
        return {
            name: str(Path(td) / f"target_{name}")
            for name in ("secrets", "ca", "acme", "certbot")
        }

    def test_main_restores_only_present_subtrees(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            files_dir = Path(td) / "files"
            (files_dir / "secrets").mkdir(parents=True)
            targets = self._tmp_targets(td)
            with (
                mock.patch.object(mod, "SecretsRecovery") as mock_sec,
                mock.patch.object(mod, "_software_domain", return_value="example"),
                mock.patch.object(mod, "_targets", return_value=targets),
                mock.patch.object(
                    sys, "argv", ["recover.py", str(files_dir), "--no-safety-backup"]
                ),
            ):
                mock_sec.return_value.service_backup = False
                self.assertEqual(mod.main(), 0)
                mock_sec.assert_called_once_with(
                    str(files_dir / "secrets"),
                    targets["secrets"],
                    service_backup=False,
                )
                mock_sec.return_value.restore.assert_called_once_with()
                mock_sec.return_value.backup_target.assert_not_called()

    def test_main_runs_backup_unit_once_across_subtrees(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            files_dir = Path(td) / "files"
            (files_dir / "secrets").mkdir(parents=True)
            (files_dir / "acme").mkdir(parents=True)
            with (
                mock.patch.object(mod, "SecretsRecovery") as mock_sec,
                mock.patch.object(mod, "_software_domain", return_value="example"),
                mock.patch.object(mod, "_targets", return_value=self._tmp_targets(td)),
                mock.patch.object(sys, "argv", ["recover.py", str(files_dir)]),
            ):
                mock_sec.return_value.service_backup = True
                self.assertEqual(mod.main(), 0)
                self.assertEqual(mock_sec.return_value.backup_target.call_count, 1)
                self.assertEqual(mock_sec.return_value.restore.call_count, 2)

    def test_main_refuses_when_no_subtree_present(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            files_dir = Path(td) / "files"
            files_dir.mkdir()
            with (
                mock.patch.object(mod, "_software_domain", return_value="example"),
                mock.patch.object(sys, "argv", ["recover.py", str(files_dir)]),
                self.assertRaises(SystemExit),
            ):
                mod.main()

    def test_main_node_identity_is_gated(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            files_dir = Path(td) / "files"
            (files_dir / "secrets").mkdir(parents=True)
            (files_dir / "node").mkdir(parents=True)
            for argv, expect in (
                (["recover.py", str(files_dir), "--no-safety-backup"], False),
                (
                    [
                        "recover.py",
                        str(files_dir),
                        "--no-safety-backup",
                        "--restore-node-identity",
                    ],
                    True,
                ),
            ):
                with (
                    mock.patch.object(mod, "SecretsRecovery") as mock_sec,
                    mock.patch.object(mod, "_software_domain", return_value="example"),
                    mock.patch.object(
                        mod, "_targets", return_value=self._tmp_targets(td)
                    ),
                    mock.patch.object(mod, "_restore_node_identity") as restore_node,
                    mock.patch.object(sys, "argv", argv),
                ):
                    mock_sec.return_value.service_backup = False
                    self.assertEqual(mod.main(), 0)
                    self.assertEqual(restore_node.called, expect)


if __name__ == "__main__":
    unittest.main()
