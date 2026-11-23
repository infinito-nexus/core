from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ._spec_secrets_fakes import MASKER, VALUE, install, make_run, scratch_text
from ._spec_secrets_wiring import GUARD, SECRETS_DIR, render_argv, run_argv

FAKE_MASKER = (
    "import json, pathlib, sys\n"
    "pathlib.Path(sys.argv[-1]).write_text(json.dumps(sys.argv[1:]))\n"
)
GUARD_EXPRESSION = (
    "['python3', '-I', '-B', TEST_E2E_PLAYWRIGHT_TOOLS_DIR ~ '/spec_secrets.py',"
    " 'guard']"
)
PREFIX_CHECK = (
    '    if argv[:5] != [*PYTHON, masker, "mask"] or argv[7:8] != ["--"]:\n',
    "    if False:\n",
)
RUN_CHECK = ("    os.close(open_run(Path(argv[5])))\n", "")
PYTHON = ["python3", "-I", "-B"]
CASES = (
    "accepted",
    "masker off",
    "foreign masker",
    "scrub",
    "no separator",
    "foreign run",
)


def guarded(*replacements: tuple[str, str]) -> dict[str, tuple[int, list[str] | None]]:
    """Hand each case's command to ``spec_secrets.py guard``, its masker a probe.

    Args:
        *replacements: changes to the helper, for a negative control.

    Returns:
        Per name of ``CASES``, the guard's exit code and the arguments the
        command it replaced itself with got, or None when none ran, and
        under ``accepted argv`` what the accepted case should show.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root)
        source = scratch_text(helper)
        for old, new in replacements:
            if source.count(old) != 1:
                raise AssertionError(f"the helper no longer holds {old!r} once")
            source = source.replace(old, new)
        helper.write_text(source, encoding="utf-8")
        masker, foreign = root / "bin" / MASKER.name, root / "foreign.py"
        for script in (masker, foreign):
            script.write_text(FAKE_MASKER, encoding="utf-8")
        tools = root / "tools"
        tools.mkdir()
        (tools / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        (tools / "python3").chmod(0o755)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        elsewhere = root / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        reports, probe = str(root / "reports"), str(root / "probe.json")
        tail = ["container", "run", "image", "--", probe]
        commands = {
            "accepted": [*PYTHON, str(masker), "mask", str(directory), reports, "--"],
            "masker off": [],
            "foreign masker": [
                *PYTHON,
                str(foreign),
                "mask",
                str(directory),
                reports,
                "--",
            ],
            "scrub": [*PYTHON, str(masker), "scrub", str(directory), reports, "--"],
            "no separator": [*PYTHON, str(masker), "mask", str(directory), reports],
            "foreign run": [
                *PYTHON,
                str(masker),
                "mask",
                str(elsewhere),
                reports,
                "--",
            ],
        }
        found = {}
        for name in CASES:
            Path(probe).unlink(missing_ok=True)
            result = subprocess.run(
                [sys.executable, str(helper), "guard", *commands[name], *tail],
                capture_output=True,
                check=False,
                env={**os.environ, "PATH": f"{tools}:{os.environ['PATH']}"},
            )
            ran = (
                json.loads(scratch_text(Path(probe))) if Path(probe).exists() else None
            )
            found[name] = (result.returncode, ran)
        found["accepted argv"] = (0, [*commands["accepted"][4:], *tail])
        return found


def guard_violations(expression: str) -> list[str]:
    """Check that a run with the template starts with the guard whatever the mask argv.

    Args:
        expression: the container ``argv`` expression.

    Returns:
        One message per run that a ``TEST_E2E_PLAYWRIGHT_MASK_ARGV`` extra var
        could turn unmasked without the guard refusing it.
    """
    problems = []
    for override in (None, [], [*PYTHON, "/elsewhere/mask.py", "mask"]):
        argv = render_argv(expression, True, SECRETS_DIR, mask_argv=override)
        if argv[: len(GUARD)] != GUARD:
            problems.append(f"the run with mask argv {override} is not guarded")
    if render_argv(expression, False, SECRETS_DIR)[:2] != ["container", "run"]:
        problems.append("a run without the template is guarded")
    return problems


class TestSpecSecretsGuard(unittest.TestCase):
    def test_the_guard_runs_only_the_masker_shipped_next_to_it(self) -> None:
        found = guarded()
        self.assertEqual(found["accepted"], found["accepted argv"])
        for name in CASES[1:]:
            with self.subTest(case=name):
                self.assertEqual(found[name], (1, None))

    def test_a_run_with_the_template_is_guarded_whatever_the_mask_argv(self) -> None:
        self.assertEqual(guard_violations(run_argv()), [])


class TestSpecSecretsGuardNegativeControls(unittest.TestCase):
    def test_a_guard_that_skips_the_masker_or_the_run_check_is_caught(self) -> None:
        self.assertEqual(guarded(PREFIX_CHECK)["foreign masker"][0], 0)
        self.assertEqual(guarded(RUN_CHECK)["foreign run"][0], 0)

    def test_a_run_whose_guard_a_variable_can_drop_is_caught(self) -> None:
        self.assertEqual(run_argv().count(GUARD_EXPRESSION), 1)
        unguarded = run_argv().replace(GUARD_EXPRESSION, "[]")
        self.assertNotEqual(guard_violations(unguarded), [])


if __name__ == "__main__":
    unittest.main()
