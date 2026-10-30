"""The roundtrip gate: its drill-completion contract and the network its swarm step pins."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

DRILL = (
    PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm" / "routine" / "00_one.sh"
)
GATE = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "roundtrip.sh"
MARKER = "==> swarm drill complete: app="
APP = "svc-db-postgres"
PYTHON_STUB = (
    "#!/usr/bin/env bash\n"
    'if [ "$1" = -m ]; then exit "${STUB_MULTI_RC}"; fi\n'
    'exec "${REAL_PYTHON}" "$@"\n'
)
MAKE_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$*" >>"${STUB_LOG}"\n'
    'echo "==> swarm drill complete: app=${STUB_APP}"\n'
)


def swarm_network(disable: str, *, multi_accepted: bool) -> str:
    """Run the roundtrip's swarm step against stubs and return the network it pins.

    Args:
        disable: the ``disable`` env the roundtrip runs with.
        multi_accepted: whether the stubbed validator accepts the role's
            ``multi`` row.

    Returns:
        The ``network=`` value the roundtrip hands to ``swarm-zombie``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        script = root / "scripts" / "tests" / "deploy" / "roundtrip.sh"
        script.parent.mkdir(parents=True)
        script.symlink_to(GATE)
        loader = root / "scripts" / "meta" / "env" / "load.sh"
        loader.parent.mkdir(parents=True)
        loader.write_text("")
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        for name, body in (("python", PYTHON_STUB), ("make", MAKE_STUB)):
            stub = bin_dir / name
            stub.write_text(body)
            stub.chmod(0o755)
        log = Path(tmp) / "make.log"
        log.touch()
        env = {k: v for k, v in os.environ.items() if k != "BASH_ENV"}
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            PYTHON=str(bin_dir / "python"),
            REAL_PYTHON=sys.executable,
            PYTHONPATH=str(PROJECT_ROOT),
            TMPDIR=tmp,
            STUB_LOG=str(log),
            STUB_APP=APP,
            STUB_MULTI_RC="0" if multi_accepted else "1",
            apps=APP,
            modes="swarm",
            keep="true",
            disable=disable,
        )
        done = subprocess.run(
            ["bash", str(script)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise AssertionError(f"roundtrip failed: {done.stderr}")
        calls = log.read_text().splitlines()  # nocheck: cache-read  stub call log
    zombie = next(call for call in calls if " swarm-zombie " in call)
    return re.search(r"(?:^| )network=(\S*)", zombie).group(1)


class TestRoundtripMarker(unittest.TestCase):
    def setUp(self) -> None:
        self.drill = read_text(str(DRILL))
        self.gate = read_text(str(GATE))

    def test_the_drill_emits_the_marker(self) -> None:
        self.assertIn(MARKER, self.drill)

    def test_the_gate_looks_for_the_same_literal(self) -> None:
        self.assertIn(MARKER, self.gate)

    def test_the_marker_carries_the_app_id(self) -> None:
        emitted = re.search(rf'echo "{re.escape(MARKER)}(\S+)', self.drill)
        self.assertIsNotNone(emitted)
        self.assertEqual(emitted.group(1), "${APP_ID}")

    def test_the_app_id_is_guarded_against_being_empty(self) -> None:
        self.assertIn(': "${APP_ID:?', self.drill)

    def test_the_marker_is_emitted_after_the_state_assertion(self) -> None:
        assertion = self.drill.index("07_assert_state.sh")
        self.assertGreater(self.drill.index(MARKER), assertion)

    def test_the_gate_matches_the_marker_as_a_fixed_string(self) -> None:
        self.assertIn("grep -qF", self.gate)

    def test_the_gate_no_longer_matches_a_workflow_step_name(self) -> None:
        self.assertNotIn("provision/deploy/e2e/verify per round", self.gate)


class TestRoundtripSwarmNetwork(unittest.TestCase):
    def test_a_role_that_takes_multi_is_pinned_to_multi(self) -> None:
        self.assertEqual(
            swarm_network("matomo,dashboard", multi_accepted=True), "multi"
        )

    def test_a_role_refused_multi_keeps_the_rotation(self) -> None:
        self.assertEqual(swarm_network("", multi_accepted=False), "")

    def test_a_disabled_tor_provider_pins_clearnet(self) -> None:
        self.assertEqual(
            swarm_network("matomo,tor,zammad", multi_accepted=True), "clearnet"
        )

    def test_a_disabled_tor_provider_pins_clearnet_over_the_rotation(self) -> None:
        self.assertEqual(swarm_network("tor", multi_accepted=False), "clearnet")

    def test_a_space_separated_tor_key_pins_clearnet(self) -> None:
        self.assertEqual(swarm_network("matomo tor", multi_accepted=True), "clearnet")

    def test_a_key_that_only_starts_with_tor_keeps_multi(self) -> None:
        self.assertEqual(swarm_network("tor-smtp", multi_accepted=True), "multi")


if __name__ == "__main__":
    unittest.main()
