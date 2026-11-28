import importlib.util
import tempfile
from pathlib import Path
from unittest import TestCase, main

from . import PROJECT_ROOT

MODULE = (
    PROJECT_ROOT
    / "roles"
    / "svc-bkp-volume-2-local"
    / "files"
    / "python"
    / "baudolo"
    / "hard_restart.py"
)
SPEC = importlib.util.spec_from_file_location("baudolo_hard_restart", MODULE)
HARD_RESTART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARD_RESTART)
STATE_FILE = ".app-control-state"


class TestWithoutHardRestart(TestCase):
    def test_it_drops_hard_restart_and_its_values(self):
        command = [
            "baudolo",
            "--only-sql",
            "--hard-restart-projects",
            "mailu",
            "nextcloud",
            "--backups-dir",
            "/b",
        ]
        self.assertEqual(
            HARD_RESTART.without_hard_restart(command),
            ["baudolo", "--only-sql", "--backups-dir", "/b"],
        )

    def test_it_leaves_a_command_without_hard_restart_alone(self):
        command = ["baudolo", "--only-sql"]
        self.assertEqual(HARD_RESTART.without_hard_restart(command), command)


class TestWithoutPausedProjects(TestCase):
    def test_a_paused_project_is_not_hard_restarted(self):
        with tempfile.TemporaryDirectory() as compose_dir:
            for project, state in (("mailu", "stopped\n"), ("nextcloud", "started\n")):
                (Path(compose_dir) / project).mkdir()
                (Path(compose_dir) / project / STATE_FILE).write_text(state)
            command = [
                "baudolo",
                "--compose-dir",
                compose_dir,
                "--hard-restart-projects",
                "mailu",
                "nextcloud",
                "--only-sql",
            ]
            kept = HARD_RESTART.without_paused_projects(command, STATE_FILE)
        self.assertEqual(
            kept,
            [
                "baudolo",
                "--compose-dir",
                compose_dir,
                "--hard-restart-projects",
                "nextcloud",
                "--only-sql",
            ],
        )

    def test_the_flag_goes_when_every_project_is_paused(self):
        with tempfile.TemporaryDirectory() as compose_dir:
            (Path(compose_dir) / "mailu").mkdir()
            (Path(compose_dir) / "mailu" / STATE_FILE).write_text("stopped\n")
            command = [
                "baudolo",
                "--compose-dir",
                compose_dir,
                "--hard-restart-projects",
                "mailu",
            ]
            kept = HARD_RESTART.without_paused_projects(command, STATE_FILE)
        self.assertEqual(kept, ["baudolo", "--compose-dir", compose_dir])

    def test_a_project_without_a_marker_keeps_its_hard_restart(self):
        with tempfile.TemporaryDirectory() as compose_dir:
            command = [
                "baudolo",
                "--compose-dir",
                compose_dir,
                "--hard-restart-projects",
                "mailu",
            ]
            self.assertEqual(
                HARD_RESTART.without_paused_projects(command, STATE_FILE), command
            )


if __name__ == "__main__":
    main()
