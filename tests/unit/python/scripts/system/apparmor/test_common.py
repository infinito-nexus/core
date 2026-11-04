"""The AppArmor teardown must keep docker-default loaded.

Run 39332343490 lost 39 swarm jobs: the runner's teardown unloaded every
profile, and BuildKit then failed each node image RUN step with
`apparmor failed to apply profile: write .../attr/apparmor/exec: no such file`.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

COMMON = PROJECT_ROOT / "scripts" / "system" / "apparmor" / "common.sh"

PROFILES = """wg-quick (enforce)
wg-quick//ip (enforce)
docker-default (enforce)
/usr/bin/man (enforce)
unprivileged_userns (unconfined)
docker-defaults (complain)
"""


class TestRemovableProfiles(unittest.TestCase):
    def test_keeps_docker_default_and_child_profiles(self) -> None:
        result = subprocess.run(
            ["bash", "-c", f'source "{COMMON}"; apparmor_removable_profiles'],
            input=PROFILES,
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(
            [
                "wg-quick",
                "/usr/bin/man",
                "unprivileged_userns",
                "docker-defaults",
            ],
            result.stdout.splitlines(),
        )


def _call(function: str, sysctl: Path, state: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "bash",
            "-c",
            f'source "{COMMON}"; {function} "$1" "$2"',
            "-",
            str(sysctl),
            str(state),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _value(path: Path) -> str:
    return path.read_text().strip()  # nocheck: cache-read - per-test temp file


class TestUnconfinedRestriction(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sysctl = Path(self._tmp.name) / "apparmor_restrict_unprivileged_unconfined"
        self.state = Path(self._tmp.name) / "run" / "infinito" / "restriction"

    def test_lifting_turns_the_restriction_off(self) -> None:
        self.sysctl.write_text("1\n")
        result = _call("apparmor_lift_unconfined_restriction", self.sysctl, self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_value(self.sysctl), "0")

    def test_lifting_records_the_previous_value(self) -> None:
        self.sysctl.write_text("1\n")
        _call("apparmor_lift_unconfined_restriction", self.sysctl, self.state)
        self.assertEqual(_value(self.state), "1")

    def test_lifting_an_already_lifted_restriction_records_nothing(self) -> None:
        self.sysctl.write_text("0\n")
        result = _call("apparmor_lift_unconfined_restriction", self.sysctl, self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.state.exists())

    def test_a_kernel_without_the_sysctl_is_left_alone(self) -> None:
        result = _call("apparmor_lift_unconfined_restriction", self.sysctl, self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.sysctl.exists())
        self.assertFalse(self.state.exists())

    def test_reinstating_restores_the_recorded_value(self) -> None:
        self.sysctl.write_text("1\n")
        _call("apparmor_lift_unconfined_restriction", self.sysctl, self.state)
        result = _call(
            "apparmor_reinstate_unconfined_restriction", self.sysctl, self.state
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_value(self.sysctl), "1")
        self.assertFalse(self.state.exists())

    def test_reinstating_without_a_record_changes_nothing(self) -> None:
        self.sysctl.write_text("0\n")
        result = _call(
            "apparmor_reinstate_unconfined_restriction", self.sysctl, self.state
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_value(self.sysctl), "0")


if __name__ == "__main__":
    unittest.main()
