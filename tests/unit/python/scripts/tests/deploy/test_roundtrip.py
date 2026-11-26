"""The roundtrip gate: its drill-completion contract, the network its swarm step
pins and the variant each entry deploys in both modes."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import NamedTuple

from cli.meta.ci import roundtrip as entry_check
from utils.cache.applications import get_variants
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.display import display_names

DRILL = (
    PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm" / "routine" / "00_one.sh"
)
GATE = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "roundtrip.sh"
MARKER = "==> swarm drill complete: app="
APP = "svc-db-postgres"
VARIANT_APP = "web-app-nextcloud"
PYTHON_STUB = (
    "#!/usr/bin/env bash\n"
    'if [ "$1" = -m ] && [ "$2" = cli.meta.ci.roundtrip ]; then\n'
    '\tprintf "%s\\n" "$*" >>"${STUB_PY_LOG}"\n'
    '\tif [ "${STUB_ENTRIES_RC}" = 0 ]; then printf "%s\\n" "${STUB_ENTRIES}"; '
    'else printf "%s\\n" "${STUB_ENTRIES}" >&2; fi\n'
    '\texit "${STUB_ENTRIES_RC}"\n'
    "fi\n"
    'if [ "$1" = -m ]; then\n'
    '\tprintf "%s\\n" "$*" >>"${STUB_PY_LOG}"\n'
    '\tcase " $* " in *" --require-discovery "*) exit "${STUB_MULTI_RC}" ;; esac\n'
    "\texit 0\n"
    "fi\n"
    'exec "${REAL_PYTHON}" "$@"\n'
)
MAKE_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$*" >>"${STUB_LOG}"\n'
    'for arg in "$@"; do\n'
    '\tcase "$arg" in app=*) echo "==> swarm drill complete: ${arg}" ;; esac\n'
    "done\n"
)


class Run(NamedTuple):
    """What one stubbed roundtrip did.

    Attributes:
        returncode: the roundtrip's exit status.
        stderr: what it printed to stderr.
        make: the argument lines the stubbed ``make`` received, in order.
        python: the argument lines of every stubbed ``python -m`` call.
        logs: the names of the per-mode log files it wrote.
    """

    returncode: int
    stderr: str
    make: list[str]
    python: list[str]
    logs: list[str]


def roundtrip(
    apps: str,
    *,
    modes: str,
    disable: str,
    multi_accepted: bool,
    keep: str,
    preflight: str,
) -> Run:
    """Run the roundtrip against stubbed ``make`` and ``python -m`` calls; the
    entry check answers as :mod:`cli.meta.ci.roundtrip` answers in-process.

    Args:
        apps: the ``apps`` env the roundtrip runs with.
        modes: the ``modes`` env the roundtrip runs with.
        disable: the ``disable`` env the roundtrip runs with.
        multi_accepted: whether the stubbed validator accepts the role's
            ``multi`` row; like the real one for a row it never discovers, it
            refuses only under ``--require-discovery``.
        keep: the ``keep`` env the roundtrip runs with.
        preflight: the ``preflight`` env the roundtrip runs with.

    Returns:
        The exit status, stderr, both call logs and the log files written.
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
        logs_dir = Path(tmp) / "logs"
        logs_dir.mkdir()
        make_log = Path(tmp) / "make.log"
        make_log.touch()
        python_log = Path(tmp) / "python.log"
        python_log.touch()
        try:
            entries = "\n".join(
                f"{app} {variant}"
                for app, variant in entry_check.entries(
                    apps.split(), get_variants(readonly=True)
                )
            )
            entries_rc = "0"
        except SystemExit as refused:
            entries, entries_rc = str(refused), "1"
        env = {k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "variant")}
        env.update(
            STUB_ENTRIES=entries,
            STUB_ENTRIES_RC=entries_rc,
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            PYTHON=str(bin_dir / "python"),
            REAL_PYTHON=sys.executable,
            PYTHONPATH=str(PROJECT_ROOT),
            TMPDIR=str(logs_dir),
            STUB_LOG=str(make_log),
            STUB_PY_LOG=str(python_log),
            STUB_MULTI_RC="0" if multi_accepted else "1",
            apps=apps,
            modes=modes,
            keep=keep,
            disable=disable,
            preflight=preflight,
        )
        done = subprocess.run(
            ["bash", str(script)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return Run(
            done.returncode,
            done.stderr,
            read_text(str(make_log)).splitlines(),
            read_text(str(python_log)).splitlines(),
            sorted(path.name for path in logs_dir.iterdir()),
        )


def swarm_network(disable: str, *, multi_accepted: bool) -> str:
    """Run the roundtrip's swarm step against stubs and return the network it pins.

    Args:
        disable: the ``disable`` env the roundtrip runs with.
        multi_accepted: whether the stubbed validator accepts the role's
            ``multi`` row; like the real one for a row it never discovers, it
            refuses only under ``--require-discovery``.

    Returns:
        The ``network=`` value the roundtrip hands to ``swarm-zombie``.
    """
    calls = swarm_make_calls(
        disable, multi_accepted=multi_accepted, keep="true", preflight=""
    )
    zombie = next(call for call in calls if " swarm-zombie " in call)
    return re.search(r"(?:^| )network=(\S*)", zombie).group(1)


def swarm_make_calls(
    disable: str, *, multi_accepted: bool, keep: str, preflight: str
) -> list[str]:
    """Run the roundtrip's swarm step against stubs and return every make call.

    Args:
        disable: the ``disable`` env the roundtrip runs with.
        multi_accepted: whether the stubbed validator accepts the role's
            ``multi`` row; like the real one for a row it never discovers, it
            refuses only under ``--require-discovery``.
        keep: the ``keep`` env the roundtrip runs with.
        preflight: the ``preflight`` env the roundtrip runs with.

    Returns:
        The argument lines the stubbed ``make`` received, in order.
    """
    run = roundtrip(
        APP,
        modes="swarm",
        disable=disable,
        multi_accepted=multi_accepted,
        keep=keep,
        preflight=preflight,
    )
    if run.returncode != 0:
        raise AssertionError(f"roundtrip failed: {run.stderr}")
    return run.make


def both_modes(apps: str) -> Run:
    """Run the roundtrip through compose and swarm for *apps* against stubs.

    Args:
        apps: the ``apps`` env the roundtrip runs with.

    Returns:
        What the stubbed run did.
    """
    return roundtrip(
        apps,
        modes="compose swarm",
        disable="",
        multi_accepted=True,
        keep="",
        preflight="",
    )


def pinned_variant(call: str) -> str:
    """The ``variant=`` a make call carries, or ``""`` when it carries none."""
    found = re.search(r"(?:^| )variant=(\S*)", call)
    return found.group(1) if found else ""


def drill_tail(assert_rc: int) -> subprocess.CompletedProcess:
    """
    Args:
        assert_rc: the exit status of the stubbed state assertion.

    Returns:
        The run of the drill from its state assertion to its end.
    """
    lines = read_text(str(DRILL)).splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line.endswith('/07_assert_state.sh"')
    )
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "07_assert_state.sh").write_text(
            f"echo asserted\nexit {assert_rc}\n", encoding="utf-8"
        )
        return subprocess.run(
            ["bash", "-c", "\n".join(["set -euo pipefail", *lines[start:]])],
            env={
                "PATH": os.environ["PATH"],
                "SCRIPT_DIR": tmp,
                "APP_ID": APP,
                "INFINITO_DISTRO": "arch",
            },
            capture_output=True,
            text=True,
            check=False,
        )


class TestRoundtripMarker(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = read_text(str(GATE))

    def test_the_drill_completes_with_the_marker_after_the_state_assertion(
        self,
    ) -> None:
        done = drill_tail(0)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            done.stdout.splitlines(), ["asserted", f"{MARKER}{APP} distro=arch"]
        )

    def test_a_failed_state_assertion_emits_no_marker(self) -> None:
        done = drill_tail(1)
        self.assertEqual(done.returncode, 1)
        self.assertNotIn(MARKER, done.stdout)

    def test_the_gate_passes_only_on_what_the_drill_emits(self) -> None:
        for printed, code in ((drill_tail(0).stdout, 0), ("asserted\n", 1)):
            stub = (
                "#!/usr/bin/env bash\n"
                'printf "%s\\n" "$*" >>"${STUB_LOG}"\n'
                f"printf %s {shlex.quote(printed)}\n"
            )
            with (
                self.subTest(printed=printed),
                unittest.mock.patch.object(sys.modules[__name__], "MAKE_STUB", stub),
            ):
                run = roundtrip(
                    APP,
                    modes="swarm",
                    disable="",
                    multi_accepted=True,
                    keep="",
                    preflight="",
                )
                self.assertEqual(run.returncode, code, run.stderr)

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


class TestRoundtripSwarmRelease(unittest.TestCase):
    def test_an_empty_keep_reaches_swarm_zombie_which_releases(self) -> None:
        calls = swarm_make_calls("", multi_accepted=False, keep="", preflight="")
        zombie = next(call for call in calls if " swarm-zombie " in call)
        self.assertRegex(zombie, r"(?:^| )keep=(?: |$)")

    def test_keep_true_reaches_swarm_zombie(self) -> None:
        calls = swarm_make_calls("", multi_accepted=False, keep="true", preflight="")
        zombie = next(call for call in calls if " swarm-zombie " in call)
        self.assertRegex(zombie, r"(?:^| )keep=true(?: |$)")

    def test_the_roundtrip_runs_no_release_of_its_own(self) -> None:
        calls = swarm_make_calls("", multi_accepted=False, keep="", preflight="")
        self.assertFalse([call for call in calls if " swarm-down " in call], calls)


class TestRoundtripSwarmPreflight(unittest.TestCase):
    def test_preflight_false_reaches_swarm_zombie(self) -> None:
        calls = swarm_make_calls("", multi_accepted=False, keep="", preflight="false")
        zombie = next(call for call in calls if " swarm-zombie " in call)
        self.assertRegex(zombie, r"(?:^| )preflight=false(?: |$)")

    def test_an_empty_preflight_lets_swarm_zombie_run_it(self) -> None:
        calls = swarm_make_calls("", multi_accepted=False, keep="", preflight="")
        zombie = next(call for call in calls if " swarm-zombie " in call)
        self.assertRegex(zombie, r"(?:^| )preflight=(?: |$)")


class TestRoundtripVariant(unittest.TestCase):
    def test_a_variant_entry_reaches_the_compose_deploy(self) -> None:
        run = both_modes(f"{VARIANT_APP}#8")
        compose = next(call for call in run.make if " compose-deploy " in call)
        self.assertEqual(pinned_variant(compose), "8")
        self.assertRegex(compose, rf"(?:^| )apps={VARIANT_APP}(?: |$)")

    def test_a_variant_entry_reaches_swarm_zombie(self) -> None:
        run = both_modes(f"{VARIANT_APP}#8")
        zombie = next(call for call in run.make if " swarm-zombie " in call)
        self.assertEqual(pinned_variant(zombie), "8")
        self.assertRegex(zombie, rf"(?:^| )app={VARIANT_APP}(?: |$)")

    def test_the_multi_probe_asks_for_the_entrys_variant(self) -> None:
        run = both_modes(f"{VARIANT_APP}#8")
        probes = [call for call in run.python if "--require-discovery" in call]
        self.assertEqual(len(probes), 1, run.python)
        self.assertIn(f"--whitelist {VARIANT_APP}#8@swarm+multi", probes[0])

    def test_a_bare_role_deploys_variant_zero_in_both_modes(self) -> None:
        run = both_modes(APP)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual([pinned_variant(call) for call in run.make], ["0", "0"])

    def test_two_variants_of_one_role_run_in_order_with_their_own_logs(self) -> None:
        run = both_modes(f"{VARIANT_APP} {VARIANT_APP}#8")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            [(call.split()[2], pinned_variant(call)) for call in run.make],
            [
                ("compose-deploy", "0"),
                ("swarm-zombie", "0"),
                ("compose-deploy", "8"),
                ("swarm-zombie", "8"),
            ],
        )
        self.assertEqual(
            run.logs,
            [
                f"roundtrip-{VARIANT_APP}-compose.log",
                f"roundtrip-{VARIANT_APP}-swarm.log",
                f"roundtrip-{VARIANT_APP}-v8-compose.log",
                f"roundtrip-{VARIANT_APP}-v8-swarm.log",
            ],
        )

    def test_the_swarm_axes_still_reach_swarm_zombie_beside_the_variant(self) -> None:
        run = roundtrip(
            f"{VARIANT_APP}#8",
            modes="swarm",
            disable="matomo,tor",
            multi_accepted=True,
            keep="true",
            preflight="false",
        )
        zombie = next(call for call in run.make if " swarm-zombie " in call)
        for pinned in (
            "variant=8",
            "network=clearnet",
            "disable=matomo,tor",
            "keep=true",
            "preflight=false",
        ):
            self.assertRegex(zombie, rf"(?:^| ){re.escape(pinned)}(?: |$)")

    def test_a_token_pinning_more_than_the_variant_is_refused(self) -> None:
        run = both_modes(f"{VARIANT_APP}#8@swarm")
        self.assertEqual(run.returncode, 2)
        self.assertIn(f"'{VARIANT_APP}#8@swarm'", run.stderr)

    def test_a_non_numeric_variant_is_refused(self) -> None:
        self.assertEqual(both_modes(f"{VARIANT_APP}#x").returncode, 2)

    def test_a_bad_entry_is_refused_before_any_earlier_entry_deploys(self) -> None:
        run = both_modes(f"{APP} {VARIANT_APP}#8@swarm")
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.make, [])

    def test_an_undeclared_variant_is_refused_before_any_deploy(self) -> None:
        run = both_modes(f"{APP} {VARIANT_APP}#80")
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.make, [])
        self.assertIn(f"'{VARIANT_APP}#80'", run.stderr)

    def test_an_unknown_role_is_refused_before_any_deploy(self) -> None:
        run = both_modes(f"{APP} web-app-does-not-exist")
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.make, [])
        self.assertIn("'web-app-does-not-exist'", run.stderr)

    def test_a_display_name_resolves_to_its_role(self) -> None:
        run = both_modes(f"{display_names().encode(VARIANT_APP)}#8")
        self.assertEqual(run.returncode, 0, run.stderr)
        compose = next(call for call in run.make if " compose-deploy " in call)
        self.assertRegex(compose, rf"(?:^| )apps={VARIANT_APP}(?: |$)")

    def test_every_entry_reaches_the_entry_check(self) -> None:
        run = both_modes(f"{APP}\n{VARIANT_APP}#8")
        self.assertIn(f"-m cli.meta.ci.roundtrip {APP} {VARIANT_APP}#8", run.python)

    def test_no_entry_names_a_swarm_cluster_of_its_own(self) -> None:
        run = both_modes(f"{VARIANT_APP} {VARIANT_APP}#8")
        zombies = [call for call in run.make if " swarm-zombie " in call]
        self.assertEqual(len(zombies), 2)
        for call in zombies:
            self.assertNotRegex(call, r"(?:^| )name=")


if __name__ == "__main__":
    unittest.main()
