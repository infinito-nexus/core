from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.infra import __main__ as cli
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.pin import write, write_applied
from utils.cache.yaml import load_yaml
from utils.env.handlers.infinito.cache.pin import KEY as PIN_FILE_KEY
from utils.env.handlers.infinito.cache.pin import ROOT_KEY as PIN_ROOT_KEY
from utils.infra import RUNNER_CONTAINER_KEY
from utils.infra_inventory import CACHE_SERVICES
from utils.roles.mapping import ROLE_FILE_META_SERVICES

APPLY = Path("scripts") / "system" / "cache" / "apply.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"
RUNNER = "infinito-infra-runner"


def _done(code: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code)


class _PinStep(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        pin = self.state / "cache.ref"
        write(pin, SHA)
        write_applied(pin, SHA)
        self.records = self._snapshot()
        environ = patch.dict(
            os.environ,
            {PIN_FILE_KEY: str(pin), PIN_ROOT_KEY: str(self.state / "pins")},
        )
        environ.start()
        self.addCleanup(environ.stop)

    def _snapshot(self) -> dict[str, str]:
        return {
            path.name: path.read_text(encoding="utf-8")  # nocheck: cache-read
            for path in sorted(self.state.iterdir())
        }

    def _step(self, step: str, code: int = 0) -> tuple[list[str], str]:
        """Args:
            step: ``prepare`` or ``apply``.
            code: the exit code apply.sh answers with.

        Returns:
            The argv of every apply.sh call and the stderr of the step.
        """
        stderr = io.StringIO()
        with (
            patch("sys.stderr", stderr),
            patch.object(cli.subprocess, "run", return_value=_done(code)) as run,
        ):
            getattr(cli, f"_pin_{step}")()
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], PROJECT_ROOT)
        return [list(call.args[0]) for call in run.call_args_list], stderr.getvalue()


class TestEveryCallApplies(_PinStep):
    def test_a_record_that_names_the_pin_never_skips_the_apply(self) -> None:
        calls, _stderr = self._step("apply")
        self.assertEqual(calls, [["bash", str(APPLY)]])

    def test_the_pin_steps_never_touch_the_records(self) -> None:
        self._step("prepare")
        self._step("apply")
        self.assertEqual(self._snapshot(), self.records)


class TestThePinSteps(_PinStep):
    def test_the_prepare_installs_the_pin_through_apply_sh(self) -> None:
        calls, _stderr = self._step("prepare")
        self.assertEqual(calls, [["bash", str(APPLY), "prepare"]])

    def test_without_a_pin_the_prepare_stops_naming_dotenv_and_the_declarer(
        self,
    ) -> None:
        with self.assertRaises(SystemExit) as stopped:
            self._step("prepare", code=3)
        message = str(stopped.exception.code)
        for part in (
            "does not start without its pin",
            "make dotenv",
            "make cache-declare ref=<commit>",
            cli.CACHE_PIN_DOC,
        ):
            self.assertIn(part, message)

    def test_a_failed_apply_warns_and_never_stops_the_call(self) -> None:
        _calls, stderr = self._step("apply", code=1)
        self.assertIn("WARNING", stderr)
        self.assertIn("rc=1", stderr)
        self.assertNotIn("outside the pin root", stderr)

    def test_a_failed_apply_leaves_the_fix_to_the_message_of_apply_sh(self) -> None:
        _calls, stderr = self._step("apply", code=1)
        self.assertNotIn("make ", stderr)
        self.assertIn(
            "is not running; start it with make infra-update",
            read_text(str(PROJECT_ROOT / APPLY)),
        )

    def test_a_frontend_on_a_foreign_map_is_sent_to_infra_update(self) -> None:
        _calls, stderr = self._step("apply", code=cli.FOREIGN_MAP)
        self.assertIn("WARNING", stderr)
        self.assertIn("outside the pin root", stderr)
        self.assertIn("make infra-update", stderr)
        self.assertNotIn("make cache-apply", stderr)

    def test_only_the_map_outside_the_pin_root_returns_that_code(self) -> None:
        pin_sh = read_text(str(PROJECT_ROOT / APPLY.with_name("pin.sh")))
        self.assertEqual(pin_sh.count(f"return {cli.FOREIGN_MAP}"), 1)
        self.assertIn(
            "cache_pin_frontend_map || exit $?", read_text(str(PROJECT_ROOT / APPLY))
        )


class TestRunnerState(unittest.TestCase):
    def _state(self, names: str | None) -> int:
        with (
            patch.dict(os.environ, {RUNNER_CONTAINER_KEY: RUNNER}),
            patch("sys.stderr", io.StringIO()),
            patch.object(cli, "run_command", return_value=names),
        ):
            return cli.main([cli.RUNNING])

    def test_a_running_runner_answers_zero(self) -> None:
        self.assertEqual(self._state(f"other\n{RUNNER}\n"), 0)

    def test_a_stopped_runner_is_told_apart_from_a_failure(self) -> None:
        self.assertEqual(self._state("other\n"), cli.RUNNER_DOWN)
        self.assertEqual(self._state(None), 2)
        self.assertNotIn(cli.RUNNER_DOWN, (0, 1, 2))

    def test_pin_sh_maps_the_stopped_runner_to_a_stopped_frontend(self) -> None:
        pin_sh = read_text(str(PROJECT_ROOT / APPLY.with_name("pin.sh")))
        self.assertIn(f"\t{cli.RUNNER_DOWN}) return 1 ;;", pin_sh)


class TestCachePort(unittest.TestCase):
    def test_the_bootstrap_port_is_the_one_nexus_listens_on(self) -> None:
        role, key = CACHE_SERVICES["package"]
        declared = load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES)
        out = io.StringIO()
        with patch("sys.stdout", out):
            self.assertEqual(cli.main([cli.CACHE_PORT, "package", "http"]), 0)
        self.assertEqual(
            out.getvalue().strip(), str(declared[key]["ports"]["internal"]["http"])
        )


class TestTheInfraRunnerServesThePin(unittest.TestCase):
    def _handed(self, action: list[str]) -> dict[str, object]:
        """Args:
            action: the ``make infra-*`` arguments after ``python -m``.

        Returns:
            The keywords the call hands to ``utils.infra.up``.
        """
        seen: dict[str, object] = {}

        def record(_argv: list[str], **kwargs: object) -> int:
            seen.update(kwargs)
            return 0

        with (
            patch.dict(os.environ, {PIN_ROOT_KEY: "/pins"}),
            patch.object(cli, "Profile") as profile,
            patch.object(cli, "infra_roles", return_value=()),
            patch.object(cli, "_prepare", return_value=([], Path("/srv/core"))),
            patch.object(cli, "base", return_value=Path("/c")),
            patch.object(cli, "machine", return_value=Path("/m")),
            patch.object(cli, "unmounted", return_value=[]),
            patch.object(cli, "run_command", return_value=""),
            patch.object(cli, "up", side_effect=record),
        ):
            profile.return_value.cache_stack_enabled.return_value = True
            profile.return_value.pool_runner.return_value = False
            self.assertEqual(cli.main(action), 0)
        return seen

    def test_infra_up_and_infra_update_run_the_pin_steps(self) -> None:
        for action in (["up"], ["update"]):
            with self.subTest(action=action):
                handed = self._handed(action)
                self.assertIs(handed["prepare"], cli._pin_prepare)
                self.assertIs(handed["apply"], cli._pin_apply)
                self.assertNotIn("refresh", handed)

    def test_the_eviction_is_handed_to_up_to_run_after_the_apply(self) -> None:
        handed = self._handed(["up"])
        self.assertEqual(handed["evict"].args, (cli.EVICT,))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
