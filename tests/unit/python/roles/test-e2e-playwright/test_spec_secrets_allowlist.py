from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT
from ._spec_secrets_fakes import scratch_text
from ._spec_secrets_wiring import role_vars
from .test_spec_secrets_helper import load_helper, run_helper

SYNC = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "local" / "sync" / "role.sh"
SYNC_PATH = ("scripts", "tests", "deploy", "local", "sync", "role.sh")
RUNNER_TAIL = ("npx", "--no-install", "playwright", "test")
INJECTED = 'x"], "TEST_E2E_PLAYWRIGHT_RUNNER": ["npx --reporter=html'
PARAMETERS = {
    "role": 'web-app-x"], "TEST_E2E_PLAYWRIGHT_MASK_ARGV": [], "x": ["y',
    "base": '#001f3f", "TEST_E2E_PLAYWRIGHT_MASK_ARGV": [], "x": "y',
    "keep": 'false", "TEST_E2E_PLAYWRIGHT_MASK_ARGV": [], "x": "y',
    "pw": INJECTED,
}
EXPECTED_EXTRA = {
    "APPLICATIONS_WHITELIST": [PARAMETERS["role"]],
    "sync_scope": "role",
    "sync_task": "",
    "DESIGN_BASE_COLOR": PARAMETERS["base"],
    "sync_playwright": True,
    "TEST_E2E_PLAYWRIGHT_ARGUMENTS": shlex.split(INJECTED),
    "test_e2e_playwright_keep": PARAMETERS["keep"],
}
ROLE_PASTE = (
    '{"APPLICATIONS_WHITELIST": [role], ',
    '{**json.loads("{\\"APPLICATIONS_WHITELIST\\": [\\"" + role + "\\"]}"), ',
)
PW_PASTE = (
    'extra["TEST_E2E_PLAYWRIGHT_ARGUMENTS"] = shlex.split(pw)',
    'extra.update(json.loads("{\\"TEST_E2E_PLAYWRIGHT_ARGUMENTS\\": [\\"" + pw + "\\"]}"))',
)
STUBS = {
    ("scripts", "meta", "env", "load.sh"): "INFINITO_INVENTORY_DIR=/inventory\n",
    ("scripts", "tests", "deploy", "local", "exec", "container.sh"): (
        'printf \'%s\' "$cmd" > "$PROBE_FILE"\n'
    ),
}
BYPASS_ARGUMENTS = (
    ("--{reporter=html,trace=on}",),
    ("$OPTS",),
    ("`opts`",),
    ("$(opts)",),
    ("$'--reporter=html'",),
)
ARGUMENTS = (
    ((), 0),
    (("--grep", "talk admin"), 0),
    (("--grep=design:", "--grep-invert", "gallery"), 0),
    (("--retries=2", "--workers=4", "--project=chromium", "playwright.spec.js:12"), 0),
    (("--reporter=html",), 1),
    (("--output=/reports/x",), 1),
    (("--trace=on",), 1),
    (("-c", "x.config.js"), 1),
    (("--config=x.config.js",), 1),
    (("--ui",), 1),
    (("--grep", "$HOME"), 1),
    (("-u",), 1),
    (("--grep",), 1),
    (("--grep", "-u"), 1),
    (("tests/../x.spec.js",), 1),
    *((words, 1) for words in BYPASS_ARGUMENTS),
)
DENYLIST = (
    "elif not SPEC.fullmatch(word):",
    'elif name in ("--reporter", "--output", "--trace", "-c", "--config", "-u"):',
)


def synced_extra(*replacements: tuple[str, str]) -> dict:
    """Run ``role.sh`` with the ``PARAMETERS`` and read the extra vars it hands on.

    Args:
        *replacements: changes to ``role.sh``, for a negative control.

    Returns:
        The first ``-e`` value of the playbook command, parsed as JSON.
    """
    source = read_text(str(SYNC))
    for old, new in replacements:
        if source.count(old) != 1:
            raise AssertionError(f"role.sh no longer holds {old!r} once")
        source = source.replace(old, new)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for parts, text in {SYNC_PATH: source, **STUBS}.items():
            root.joinpath(*parts).parent.mkdir(parents=True, exist_ok=True)
            root.joinpath(*parts).write_text(text, encoding="utf-8")
        (root / "bin").mkdir()
        (root / "bin" / "python3").symlink_to(sys.executable)
        probe = root / "cmd"
        subprocess.run(
            ["bash", str(root.joinpath(*SYNC_PATH))],
            capture_output=True,
            check=True,
            env={
                "PATH": f"{root / 'bin'}:/usr/bin:/bin",
                "HOME": tmp,
                **PARAMETERS,
                "PROBE_FILE": str(probe),
            },
        )
        words = shlex.split(scratch_text(probe))
        return json.loads(words[words.index("-e") + 1])


class TestSpecSecretsAllowlist(unittest.TestCase):
    def test_only_allowed_arguments_pass(self) -> None:
        module = load_helper()
        for words, code in ARGUMENTS:
            with self.subTest(words=words):
                self.assertEqual(run_helper(module, "arguments", *words)[0], code)

    def test_the_command_is_a_constant_that_takes_checked_arguments_only(self) -> None:
        module = load_helper()
        self.assertEqual(tuple(module.RUNNER[-4:]), RUNNER_TAIL)
        self.assertEqual(
            module.playwright(["--grep", "x"]), [*module.RUNNER, "--grep", "x"]
        )
        for words, code in ARGUMENTS:
            if code:
                with (
                    self.subTest(words=words),
                    self.assertRaises(module.SpecSecretsError),
                ):
                    module.playwright(list(words))

    def test_the_default_arguments_pass_and_no_variable_holds_the_runner(self) -> None:
        variables = role_vars()
        defaults = variables["TEST_E2E_PLAYWRIGHT_ARGUMENTS"]
        self.assertIsInstance(defaults, list)
        self.assertEqual(run_helper(load_helper(), "arguments", *defaults)[0], 0)
        self.assertNotIn("TEST_E2E_PLAYWRIGHT_RUNNER", variables)

    def test_the_sync_writes_every_parameter_through_one_json_dumps(self) -> None:
        self.assertEqual(synced_extra(), EXPECTED_EXTRA)


class TestSpecSecretsAllowlistNegativeControls(unittest.TestCase):
    def test_a_denylist_check_is_caught_letting_a_shell_form_through(self) -> None:
        denying = load_helper(DENYLIST)
        for words in BYPASS_ARGUMENTS:
            with self.subTest(words=words):
                self.assertEqual(run_helper(denying, "arguments", *words)[0], 0)

    def test_a_sync_that_pastes_a_parameter_into_the_json_is_caught(self) -> None:
        for paste, injected in (
            (ROLE_PASTE, "TEST_E2E_PLAYWRIGHT_MASK_ARGV"),
            (PW_PASTE, "TEST_E2E_PLAYWRIGHT_RUNNER"),
        ):
            with self.subTest(injected=injected):
                self.assertIn(injected, synced_extra(paste))


if __name__ == "__main__":
    unittest.main()
