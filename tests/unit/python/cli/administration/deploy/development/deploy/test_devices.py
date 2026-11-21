from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.deploy.devices import (
    SUMMARY_KEY,
    decline,
    missing_devices,
    required_devices,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _role(roles_dir: Path, role: str, body: str) -> None:
    """Args:
    roles_dir: the fixture ``roles`` directory.
    role: the role to create.
    body: its ``meta/services.yml``.
    """
    (roles_dir / role / "meta").mkdir(parents=True)
    (roles_dir / role / ROLE_FILE_META_SERVICES).write_text(body, encoding="utf-8")


class TestRequiredDevices(unittest.TestCase):
    def test_every_device_names_every_role_of_the_round_that_needs_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(
                roles_dir, "svc-virt-alpha", "alpha:\n  requires_devices: [/dev/kvm]\n"
            )
            _role(
                roles_dir,
                "svc-virt-beta",
                "beta:\n  requires_devices: [/dev/net/tun, /dev/kvm]\n",
            )
            _role(roles_dir, "svc-virt-gamma", "gamma:\n  lifecycle: alpha\n")
            needs = required_devices(
                roles_dir, ["svc-virt-alpha", "svc-virt-gamma", "svc-virt-beta"]
            )

        self.assertEqual(
            needs,
            {
                "/dev/kvm": ["svc-virt-alpha", "svc-virt-beta"],
                "/dev/net/tun": ["svc-virt-beta"],
            },
        )

    def test_a_round_of_roles_without_a_declaration_needs_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(required_devices(Path(tmp), ["web-app-absent"]), {})


class TestMissingDevices(unittest.TestCase):
    def test_each_device_is_probed_on_the_deploy_target(self) -> None:
        compose = MagicMock()
        compose.exec.side_effect = lambda cmd, **_kw: subprocess.CompletedProcess(
            cmd, 0 if cmd[2] == "/dev/net/tun" else 1
        )

        self.assertEqual(
            missing_devices(compose, ["/dev/kvm", "/dev/net/tun"]), ["/dev/kvm"]
        )
        self.assertEqual(
            [c.args[0] for c in compose.exec.call_args_list],
            [["test", "-c", "/dev/kvm"], ["test", "-c", "/dev/net/tun"]],
        )
        for call in compose.exec.call_args_list:
            self.assertEqual(
                call.kwargs, {"check": False, "capture": True, "tty": False}
            )

    def test_no_device_means_no_probe(self) -> None:
        compose = MagicMock()
        self.assertEqual(missing_devices(compose, []), [])
        compose.exec.assert_not_called()


class TestDecline(unittest.TestCase):
    def test_off_ci_the_verdict_goes_to_stdout_only(self) -> None:
        out = io.StringIO()
        with patch.dict(os.environ, {}), redirect_stdout(out):
            os.environ.pop(SUMMARY_KEY, None)
            decline({"/dev/kvm": ["svc-virt-incus"]}, ["/dev/kvm"], "1/2")

        self.assertIn(
            "requires-devices: status=declined device=/dev/kvm roles=svc-virt-incus"
            " round=1/2 ",
            out.getvalue(),
        )

    def test_the_job_summary_lists_one_line_per_missing_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            with (
                patch.dict(os.environ, {SUMMARY_KEY: str(summary)}),
                redirect_stdout(io.StringIO()),
            ):
                decline(
                    {"/dev/kvm": ["a", "b"], "/dev/net/tun": ["b"]},
                    ["/dev/kvm", "/dev/net/tun"],
                    "2/3",
                )
            report = summary.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
            lines = report.splitlines()

        self.assertEqual(
            lines,
            [
                "- `a,b` round 2/3: **not run** (declined), the deploy target has no `/dev/kvm`",
                "- `b` round 2/3: **not run** (declined), the deploy target has no `/dev/net/tun`",
            ],
        )


if __name__ == "__main__":
    unittest.main()
