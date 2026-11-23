from __future__ import annotations

import contextlib
import os
import tempfile
import unittest.mock
from pathlib import Path

from .test_spec_secrets_helper import (
    SENTINEL,
    aged,
    load_helper,
    mine,
    run_helper,
    split_rendered,
)

PER_RUN = (
    (
        "            try:\n"
        "                shutil.rmtree(name, dir_fd=top)\n"
        "            except OSError as error:\n"
        '                print(f"spec secrets prune skipped {name}: {error.strerror}")\n'
        "                continue\n"
    ),
    "            shutil.rmtree(name, dir_fd=top)\n",
)
PER_PARENT = (
    (
        "        except OSError as error:\n"
        '            print(f"spec secrets prune skipped {parent(uid)}: {error.strerror}")\n'
    ),
    "",
)
ODD_DIGIT = "\N{SUPERSCRIPT TWO}"
UNICODE_DIGITS = (
    (
        "uid = int(suffix) if NUMBER.fullmatch(suffix) else -1",
        "uid = int(suffix) if suffix.isdigit() else -1",
    ),
    ("filter(NUMBER.fullmatch, suffixes)", "filter(str.isdigit, suffixes)"),
)


def stuck_prune(module) -> tuple[int, str, list[str]]:
    """Prune a killed run and one holding a file in a directory it cannot write.

    Args:
        module: the loaded helper.

    Returns:
        The exit code, everything printed and the names left below the
        parent, with ``stuck`` for the run that cannot be removed, as a
        container's root leaves it in a non-root rerun.
    """
    with tempfile.TemporaryDirectory() as tmp:
        module.PARENT = Path(tmp) / "spec-secrets"
        killed, _, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
        stuck, _, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
        locked = stuck / "reports"
        locked.mkdir()
        (locked / "report.xml").write_text("ok")
        locked.chmod(0o500)
        aged(killed, stuck)
        try:
            code, printed = run_helper(module, "prune")
        finally:
            locked.chmod(0o700)
        names = {stuck.name: "stuck", killed.name: "killed"}
        left = sorted(names.get(name, name) for name in os.listdir(mine(module)))
        return code, printed.replace(stuck.name, "stuck"), left


def odd_suffix(module) -> list[str]:
    """Hand a root prune and ``run_owner`` a parent whose uid is a superscript digit.

    Args:
        module: the loaded helper.

    Returns:
        One message per call that neither ignored nor refused that parent;
        ``str.isdigit`` takes the digit, ``int`` does not.
    """
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        module.PARENT = Path(tmp) / "spec-secrets"
        odd = Path(tmp) / f"spec-secrets-{ODD_DIGIT}"
        odd.mkdir(mode=0o700)
        with unittest.mock.patch.object(module.os, "geteuid", return_value=0):
            try:
                if module.users() != [0]:
                    problems.append("a root prune lists the odd parent")
            except ValueError:
                problems.append("a root prune fails on the odd parent")
            with contextlib.suppress(module.SpecSecretsError):
                try:
                    module.run_owner(odd / "run.odd")
                    problems.append("run_owner takes the odd parent")
                except ValueError:
                    problems.append("run_owner fails on the odd parent")
    return problems


class TestSpecSecretsParentNames(unittest.TestCase):
    def test_a_parent_named_with_another_digit_is_ignored_or_refused(self) -> None:
        self.assertEqual(odd_suffix(load_helper()), [])


class TestSpecSecretsParentNamesNegativeControls(unittest.TestCase):
    def test_a_uid_check_that_takes_any_unicode_digit_is_caught(self) -> None:
        self.assertEqual(
            odd_suffix(load_helper(*UNICODE_DIGITS)),
            [
                "a root prune fails on the odd parent",
                "run_owner fails on the odd parent",
            ],
        )


@unittest.skipIf(os.geteuid() == 0, "root removes a run whatever its modes")
class TestSpecSecretsPrune(unittest.TestCase):
    def test_a_run_that_cannot_be_removed_is_named_and_the_prune_goes_on(
        self,
    ) -> None:
        code, printed, left = stuck_prune(load_helper())
        self.assertEqual((code, left), (0, ["stuck"]))
        self.assertIn("spec secrets prune skipped stuck: ", printed)


@unittest.skipIf(os.geteuid() == 0, "root removes a run whatever its modes")
class TestSpecSecretsPruneNegativeControls(unittest.TestCase):
    def test_a_prune_that_gives_up_the_parent_on_one_run_is_caught(self) -> None:
        code, printed, _left = stuck_prune(load_helper(PER_RUN))
        self.assertEqual(code, 0)
        self.assertNotIn("skipped stuck", printed)

    def test_a_prune_that_aborts_on_one_run_is_caught(self) -> None:
        code, printed, _left = stuck_prune(load_helper(PER_RUN, PER_PARENT))
        self.assertEqual(code, 1)
        self.assertIn("spec secrets failed: ", printed)


if __name__ == "__main__":
    unittest.main()
