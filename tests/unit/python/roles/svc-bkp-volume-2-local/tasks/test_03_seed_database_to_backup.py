from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from baudolo.databases import read_rows
from baudolo.seed import __main__ as seed_cli
from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.baudolo_seed import FilterModule, baudolo_seeded
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = (
    PROJECT_ROOT / "roles/svc-bkp-volume-2-local/tasks/03_seed-database-to-backup.yml"
)
COMPARE = "🧮 Compare the database definition with the seeded one"
SEED = "🌱 Seed database definition via baudolo-seed (system binary)"
PASSWORDS = ("S3cr3t with space", "pa;ss\"q'uote", "ends in a newline\n")


def _task(name: str) -> dict:
    for task in load_yaml_any(str(TASKS)) or []:
        if task.get("name") == name:
            return task
    raise AssertionError(f"{TASKS} has no task '{name}'")


def _render(password: str, csv: Path) -> tuple[list[str], str, dict]:
    """
    Args:
        password: the consumer's ``database_password``.
        csv: stands in for ``FILE_DATABASE_SECRETS``.

    Returns:
        The command module's argv, the stdin it writes (with the newline
        ``stdin_add_newline`` appends), and the facts the compare task sets.
    """
    context = {
        "FILE_DATABASE_SECRETS": str(csv),
        "database_instance": "central-postgres",
        "database_name": "zammad",
        "database_username": "zammad",
        "database_password": password,
        "svc_bkp_volume_2_local_seeded": baudolo_seeded(""),
    }
    text = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    native = NativeEnvironment(undefined=StrictUndefined)
    native.filters.update(FilterModule().filters())
    compare = _task(COMPARE)
    for key, values in compare["vars"].items():
        context[key] = [text.from_string(value).render(context) for value in values]
    facts = {
        key: native.from_string(value).render(context)
        for key, value in compare["ansible.builtin.set_fact"].items()
    }
    context.update(facts)
    command = _task(SEED)["ansible.builtin.command"]
    argv = native.from_string(command["argv"]).render(context)
    stdin = text.from_string(command["stdin"]).render(context)
    if command.get("stdin_add_newline", True):
        stdin += "\n"
    return argv, stdin, facts


def _seed(argv: list[str], stdin: str) -> str:
    """
    Args:
        argv: the baudolo-seed call.
        stdin: text the call reads from stdin.

    Returns:
        The call's stderr.
    """
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch.object(sys, "stdin", io.StringIO(stdin)),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()) as stderr,
    ):
        seed_cli.main()
    return stderr.getvalue()


class TestSeedPasswordTransport(unittest.TestCase):
    def test_the_password_is_on_no_argv(self) -> None:
        for password in PASSWORDS:
            with self.subTest(password=password):
                argv, _stdin, _facts = _render(password, Path("/x/databases.csv"))
                self.assertEqual(argv[0], "baudolo-seed")
                self.assertEqual(argv[-1], "--password-stdin")
                self.assertFalse(any(password.strip() in part for part in argv))

    def test_baudolo_seed_stores_the_password_from_stdin(self) -> None:
        for password in PASSWORDS:
            with self.subTest(password=password), tempfile.TemporaryDirectory() as tmp:
                csv = Path(tmp) / "databases.csv"
                argv, stdin, facts = _render(password, csv)
                self.assertNotIn("WARNING", _seed(argv, stdin))
                rows = read_rows(str(csv))
                self.assertEqual([row.password for row in rows], [password])
                self.assertFalse(facts["svc_bkp_volume_2_local_seed_current"])
                self.assertEqual(
                    facts["svc_bkp_volume_2_local_seeded"]["rows"],
                    [list(row) for row in rows],
                    "the play's view of databases.csv must match what baudolo wrote",
                )

    def test_negative_control_without_stdin_the_row_holds_no_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "databases.csv"
            argv, _stdin, _facts = _render(PASSWORDS[0], csv)
            _seed(argv, "")
            self.assertEqual([row.password for row in read_rows(str(csv))], [""])


if __name__ == "__main__":
    unittest.main()
