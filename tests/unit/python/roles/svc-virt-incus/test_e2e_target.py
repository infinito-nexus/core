from __future__ import annotations

import argparse
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from cli.administration.deploy.development.deploy import handler
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VARIANTS
from utils.roles.meta_lookup import get_role_requires_devices

ROLE = "svc-virt-incus"
DEVICE = "/dev/kvm"
CLI = "cli.administration.deploy.development.deploy.cli"
PROBE = ["test", "-c", DEVICE]
VARIANTS = load_yaml_any(
    str(PROJECT_ROOT / "roles" / ROLE / ROLE_FILE_META_VARIANTS), default_if_missing=[]
)


def _plan(inventory_dir: str) -> list[tuple]:
    """Args:
        inventory_dir: the base inventory folder of the lane.

    Returns:
        One round per variant of the role, the role alone in each.
    """
    return [
        (index, f"{inventory_dir}-{index}", {ROLE: index}, (ROLE,), (ROLE,))
        for index in range(len(VARIANTS))
    ]


class _Target:
    """Args:
    devices: the character devices the deploy target carries.
    """

    def __init__(self, devices: set[str]) -> None:
        self.devices = devices
        self.repo_root = PROJECT_ROOT
        self.probes: list[list[str]] = []

    def exec(
        self, cmd: list[str], *, check: bool, capture: bool, tty: bool
    ) -> subprocess.CompletedProcess:
        self.probes.append(cmd)
        found = cmd[:2] == ["test", "-c"] and cmd[2] in self.devices
        return subprocess.CompletedProcess(cmd, 0 if found else 1, "", "")


@dataclass
class _Lane:
    rc: int
    target: _Target
    deploys: list[list[str]]
    resets: list[object]
    out: str
    summary: str


def _run_lane(devices: set[str]) -> _Lane:
    """Args:
        devices: the character devices the deploy target carries.

    Returns:
        What the e2e lane of the role did on that target.
    """
    target = _Target(devices)
    deploys: list[list[str]] = []
    resets: list[object] = []
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        summary = Path(tmp) / "summary.md"
        summary.touch()
        inventory_dir = str(Path(tmp) / "inventory")
        stack.enter_context(
            patch(
                f"{CLI}.plan_dev_inventory_matrix",
                return_value=_plan(inventory_dir),
            )
        )
        stack.enter_context(patch(f"{CLI}.make_compose", return_value=target))
        stack.enter_context(patch(f"{CLI}.resolve_container", return_value=ROLE))
        stack.enter_context(
            patch(f"{CLI}.reset_stack_target", side_effect=resets.append)
        )
        stack.enter_context(patch(f"{CLI}._purge_app_entities"))
        stack.enter_context(
            patch(
                f"{CLI}._run_deploy",
                side_effect=lambda _compose, **kw: (
                    deploys.append(kw["deploy_ids"]) or 0
                ),
            )
        )
        stack.enter_context(
            patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)})
        )
        os.environ.pop("disable", None)
        os.environ.pop("guide_host", None)
        stack.enter_context(redirect_stdout(out))
        rc = handler(
            argparse.Namespace(
                inventory_dir=inventory_dir,
                apps=None,
                id=[ROLE],
                debug=False,
                variant=None,
                full_cycle=False,
                ansible_args=[],
            )
        )
        report = summary.read_text()  # nocheck: cache-read tempdir
        return _Lane(rc, target, deploys, resets, out.getvalue(), report)


class TestE2eTarget(unittest.TestCase):
    def test_the_role_declares_the_device_it_needs(self) -> None:
        self.assertEqual(get_role_requires_devices(ROLE), [DEVICE])

    def test_the_lane_stops_without_kvm(self) -> None:
        lane = _run_lane(devices=set())

        self.assertEqual(
            lane.rc, 0, "a missing device declines the lane, it does not fail it"
        )
        self.assertIn(PROBE, lane.target.probes)
        self.assertEqual(lane.deploys, [])
        self.assertEqual(lane.resets, [])
        self.assertRegex(
            lane.out,
            rf"requires-devices: status=declined device={DEVICE} roles={ROLE} round=1/\d+ ",
        )
        self.assertIn(f"`{ROLE}` round 1/", lane.summary)
        self.assertIn("**not run** (declined)", lane.summary)
        self.assertIn(f"`{DEVICE}`", lane.summary)

    def test_the_lane_runs_with_kvm(self) -> None:
        lane = _run_lane(devices={DEVICE})

        self.assertEqual(lane.rc, 0)
        self.assertTrue(lane.deploys)
        self.assertEqual(len(lane.resets), len(lane.deploys))
        for deploy_ids in lane.deploys:
            self.assertIn(ROLE, deploy_ids)
        self.assertEqual(lane.target.probes, [PROBE] * len(lane.deploys))
        self.assertNotIn("requires-devices", lane.out)
        self.assertEqual(lane.summary, "")


if __name__ == "__main__":
    unittest.main()
