from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import ROLE
from .test_spec_secrets_rerun import edited

CONFIG = ROLE / "files" / "playwright.config.js"
DESIGN = ROLE / "files" / "design.js"
SHOW_CONFIG = (
    "const c = require(process.argv[1]); console.log(JSON.stringify({"
    " trace: c.use.trace, screenshot: c.use.screenshot, video: c.use.video,"
    " outputDir: c.outputDir, reporters: c.reporter.map((r) => r[0]),"
    ' left: ["PW_TEST_REPORTER", "DEBUG", "PLAYWRIGHT_JUNIT_OUTPUT_FILE"]'
    ".filter((n) => n in process.env),"
    ' prompt: process.env.PLAYWRIGHT_NO_COPY_PROMPT || "",'
    ' snapshots: c.updateSnapshots || "" }));'
)
CAPTURE_OFF = {
    "trace": "off",
    "screenshot": "off",
    "video": "off",
    "outputDir": "/tmp/test-results",
    "reporters": ["list", "github", "junit"],
    "left": [],
    "prompt": "1",
    "snapshots": "none",
}
KEPT = {
    "trace": "on",
    "screenshot": "on",
    "video": "on",
    "outputDir": "/reports/test-results",
    "reporters": ["list", "github", "junit", "html"],
    "left": ["PW_TEST_REPORTER", "DEBUG", "PLAYWRIGHT_JUNIT_OUTPUT_FILE"],
    "prompt": "",
    "snapshots": "",
}
MOUNT = '"/run/spec-secrets"'
MOUNT_SWITCH = f"fs.existsSync({MOUNT}) ||"
NO_CAPTURE = "INFINITO_PLAYWRIGHT_NO_CAPTURE"  # nocheck: container env
SWITCHES = (
    {"INFINITO_PLAYWRIGHT_KEEP": "true"},
    {"INFINITO_PLAYWRIGHT_KEEP": "true", NO_CAPTURE: "true"},
    {"INFINITO_PLAYWRIGHT_KEEP": "true", NO_CAPTURE: "TRUE"},
    {},
)


def node(script: str, *args: str, **variables: str) -> str:
    """Run a node script with only the given variables beyond PATH.

    Args:
        script: the script.
        *args: its arguments.
        **variables: the environment it sees.

    Returns:
        What it printed.
    """
    env = {"PATH": os.environ["PATH"], **variables}
    return subprocess.run(
        ["node", "-e", script, *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    ).stdout.strip()


def mounted(source: str, mount: str) -> str:
    """Point the spec secrets mount a JS file looks for at another directory.

    Args:
        source: the file's text.
        mount: the directory that stands for the mount.

    Returns:
        The changed text; a file without the mount stays as it is.
    """
    return source.replace(MOUNT, json.dumps(mount))


def config_with(source: str, mount: bool = False, **variables: str) -> dict:
    """Load ``playwright.config.js`` with a stub ``@playwright/test``.

    Args:
        source: the config text.
        mount: whether the spec secrets are mounted.
        **variables: the environment beyond the timeouts it requires and the
            recording and reporter variables it may delete.

    Returns:
        The capture settings, reporters and recording variables it leaves.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "node_modules" / "@playwright" / "test"
        stub.mkdir(parents=True)
        (stub / "index.js").write_text("exports.defineConfig = (config) => config;\n")
        absent = Path(tmp) / "absent"
        (Path(tmp) / CONFIG.name).write_text(
            mounted(source, str(stub if mount else absent))
        )
        timeouts = {
            f"PLAYWRIGHT_{name}_TIMEOUT": "1"
            for name in ("TEST", "EXPECT", "NAVIGATION", "ACTION")
        }
        shown = node(
            SHOW_CONFIG,
            str(Path(tmp) / CONFIG.name),
            **timeouts,
            PW_TEST_REPORTER="html",
            DEBUG="pw:api",
            PLAYWRIGHT_JUNIT_OUTPUT_FILE="/e2e/playwright-junit.xml",
            **variables,
        )
        return json.loads(shown)


def gallery(source: str, mount: bool = False) -> list[str]:
    """Ask ``galleryEnabled`` of ``design.js`` for each switch setting.

    Args:
        source: the text of ``design.js``.
        mount: whether the spec secrets are mounted.

    Returns:
        Its answer with keep on, with keep and the switch on, with the switch
        spelled in capitals and with keep off.
    """
    found = re.search(
        r"^function galleryEnabled\(\) \{\n.*?^\}", source, re.DOTALL | re.MULTILINE
    )
    with tempfile.TemporaryDirectory() as tmp:
        function = mounted(
            found.group(0) if found else "const galleryEnabled = () => null;",
            tmp if mount else str(Path(tmp) / "absent"),
        )
        script = (
            f'const fs = require("fs");\n{function}\nconsole.log(galleryEnabled());'
        )
        return [node(script, **variables) for variables in SWITCHES]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestSpecSecretsCapture(unittest.TestCase):
    def test_the_switch_turns_capture_recording_and_the_gallery_off(self) -> None:
        source = read_text(str(CONFIG))
        self.assertEqual(
            config_with(source, INFINITO_PLAYWRIGHT_NO_CAPTURE="true"), CAPTURE_OFF
        )
        self.assertEqual(config_with(source, INFINITO_PLAYWRIGHT_KEEP="true"), KEPT)
        design = read_text(str(DESIGN))
        self.assertEqual(gallery(design), ["true", "false", "false", "false"])

    def test_the_mount_turns_capture_off_whatever_the_switch_says(self) -> None:
        source = read_text(str(CONFIG))
        self.assertEqual(
            config_with(source, True, INFINITO_PLAYWRIGHT_NO_CAPTURE="false"),
            CAPTURE_OFF,
        )
        self.assertEqual(gallery(read_text(str(DESIGN)), True), ["false"] * 4)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestSpecSecretsCaptureNegativeControls(unittest.TestCase):
    def test_capture_left_to_the_switch_alone_is_caught(self) -> None:
        unmounted = edited(CONFIG, (MOUNT_SWITCH, ""))
        self.assertNotEqual(
            config_with(unmounted, True, INFINITO_PLAYWRIGHT_NO_CAPTURE="false"),
            CAPTURE_OFF,
        )
        self.assertEqual(
            gallery(edited(DESIGN, (MOUNT_SWITCH, "")), True),
            ["true", "false", "false", "false"],
        )

    def test_capture_recording_or_the_gallery_left_on_is_caught(self) -> None:
        for old, new in (
            ('trace: "off"', 'trace: "on"'),
            ("captureOff ? [] : ", ""),
            ("delete process.env[name];", ""),
            ('captureOff ? "/tmp/test-results" : ', ""),
            ('process.env.PLAYWRIGHT_NO_COPY_PROMPT = "1";', ""),
            ('...(captureOff ? { updateSnapshots: "none" } : {}),', ""),
            (" || reporterEnv.test(name)", ""),
        ):
            with self.subTest(old=old):
                broken = edited(CONFIG, (old, new))
                self.assertNotEqual(
                    config_with(broken, INFINITO_PLAYWRIGHT_NO_CAPTURE="true"),
                    CAPTURE_OFF,
                )
        lenient = edited(DESIGN, (" && !captureOff", ""))
        self.assertEqual(gallery(lenient), ["true", "true", "true", "false"])


if __name__ == "__main__":
    unittest.main()
