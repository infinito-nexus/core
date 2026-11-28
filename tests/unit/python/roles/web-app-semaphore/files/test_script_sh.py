from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from ._semaphore_fake import SCRIPTS_DIR

DISPATCHER = read_text(str(SCRIPTS_DIR / "script.sh"))
PROBE = 'echo "cwd=${PWD}"\nprintf "arg=%s\\n" "$@"\n'


def dispatch(dispatcher, script):
    """Args:
    dispatcher: the text of ``script.sh`` to run.
    script: the playbook the template names.

    Returns:
        ``(returncode, stdout, stderr, checkout)`` of the dispatcher run in a
        checkout directory with ``script`` and the arguments ``a`` and ``b c``,
        beside ``lib.sh`` and a probe script ``probe.sh``.
    """
    with tempfile.TemporaryDirectory() as root:
        scripts, checkout = Path(root, "scripts"), Path(root, "checkout")
        scripts.mkdir()
        checkout.mkdir()
        (scripts / "script.sh").write_text(dispatcher, encoding="utf-8")
        (scripts / "lib.sh").write_text(
            read_text(str(SCRIPTS_DIR / "lib.sh")), encoding="utf-8"
        )
        (scripts / "probe.sh").write_text(PROBE, encoding="utf-8")
        run = subprocess.run(
            ["bash", str(scripts / "script.sh"), script.format(root=root), "a", "b c"],
            capture_output=True,
            check=False,
            cwd=checkout,
            text=True,
            timeout=30,
        )
        return run.returncode, run.stdout, run.stderr, str(checkout)


def escape_findings(dispatcher):
    """Args:
    dispatcher: the text of ``script.sh`` to check.

    Returns:
        Every playbook outside the script directory the dispatcher runs.
    """
    return [
        script
        for script in ("{root}/scripts/probe.sh", "../scripts/probe.sh")
        if dispatch(dispatcher, script)[0] == 0
    ]


class TestScriptDispatcher(unittest.TestCase):
    def test_it_runs_a_script_of_its_directory_in_the_checkout(self):
        code, stdout, _, checkout = dispatch(DISPATCHER, "probe.sh")
        self.assertEqual(code, 0)
        self.assertEqual(stdout.splitlines(), [f"cwd={checkout}", "arg=a", "arg=b c"])

    def test_it_refuses_a_path_and_a_missing_script(self):
        self.assertEqual(escape_findings(DISPATCHER), [])
        code, _, stderr, _ = dispatch(DISPATCHER, "missing.sh")
        self.assertEqual(code, 2)
        self.assertIn("script.sh: missing.sh is no script of", stderr)

    def test_negative_control_a_dispatcher_without_the_name_check_escapes(self):
        check = next(
            line for line in DISPATCHER.splitlines() if "is no script name" in line
        )
        planted = DISPATCHER.replace(f"{check}\n", "")
        self.assertNotEqual(planted, DISPATCHER)
        self.assertEqual(escape_findings(planted), ["../scripts/probe.sh"])


if __name__ == "__main__":
    unittest.main()
