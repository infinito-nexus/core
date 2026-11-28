from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils import infra_tools


class TestAddressable(unittest.TestCase):
    def test_each_tools_project_is_probed_by_name_inside_the_runner(self) -> None:
        seen: list[list[str]] = []

        def output(command: list[str]) -> str | None:
            seen.append(command)
            return "abc123\n" if command[-3] == "ps" and "ollama" in command else ""

        found = infra_tools.addressable(["ollama", "translate"], ["compose"], output)
        self.assertEqual(found, {"ollama": True, "translate": False})
        self.assertEqual(
            seen[0],
            [
                "compose",
                "exec",
                "-T",
                "runner",
                "docker",
                "compose",
                "-p",
                "ollama",
                "ps",
                "--all",
                "--quiet",
            ],
        )

    def test_a_failing_probe_counts_as_unreachable(self) -> None:
        found = infra_tools.addressable(["ollama"], ["compose"], lambda _command: None)
        self.assertEqual(found, {"ollama": False})


class TestIdleTimer(unittest.TestCase):
    def setUp(self) -> None:
        self.units = infra_tools.idle_units(
            Path("/srv/core"),
            "/opt/venvs/infinito/bin/python",
            {"INFINITO_TOOLS_IDLE_GRACE": "2h", "INFINITO_TOOLS_STAMP_DIR": "/c/tools"},
        )

    def test_the_service_runs_stop_if_idle_with_the_tools_stop(self) -> None:
        service = self.units["infinito-tools-idle.service"]
        self.assertIn(
            "ExecStart=/opt/venvs/infinito/bin/python -m utils.inventory.tools_idle "
            "stop-if-idle -- /opt/venvs/infinito/bin/python -m "
            "cli.administration.infra tools-inside stop",
            service,
        )
        self.assertIn("WorkingDirectory=/srv/core", service)
        self.assertIn("Environment=INFINITO_TOOLS_IDLE_GRACE=2h", service)

    def test_the_timer_repeats_and_survives_a_reboot(self) -> None:
        timer = self.units["infinito-tools-idle.timer"]
        self.assertIn("OnUnitActiveSec=5min", timer)
        self.assertIn("WantedBy=timers.target", timer)

    def test_the_timer_is_enabled_inside_the_runner_not_on_the_host(self) -> None:
        installs = infra_tools.timer_installs(["compose"], Path("/c/infra/systemd"))
        for command in installs:
            self.assertEqual(command[:4], ["compose", "exec", "-T", "runner"])
        self.assertEqual(
            installs[-1][-3:],
            ["enable", "--now", "/c/infra/systemd/infinito-tools-idle.timer"],
        )

    def test_written_units_land_below_the_unit_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit_dir = Path(tmp) / "infra" / "systemd"
            infra_tools.write_units(unit_dir, self.units)
            self.assertEqual(
                sorted(p.name for p in unit_dir.iterdir()), sorted(self.units)
            )


class TestToolsCommands(unittest.TestCase):
    def test_outside_each_tools_project_is_reached_through_the_runner(self) -> None:
        commands = infra_tools.tools_commands(
            ["ollama", "translate"], "pause", ["compose"]
        )
        self.assertEqual(
            commands[0],
            [
                "compose",
                "exec",
                "-T",
                "runner",
                "docker",
                "compose",
                "-p",
                "ollama",
                "pause",
            ],
        )
        self.assertEqual(len(commands), 2)

    def test_inside_the_runner_no_outer_call_is_prefixed(self) -> None:
        commands = infra_tools.tools_commands(["ollama"], "stop", [])
        self.assertEqual(commands, [["docker", "compose", "-p", "ollama", "stop"]])

    def test_an_unknown_action_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            infra_tools.tools_commands(["ollama"], "down", [])


if __name__ == "__main__":
    unittest.main()
