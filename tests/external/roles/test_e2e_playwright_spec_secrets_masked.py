"""Run two failing specs in the role's Playwright image through the real masker."""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import NoReturn

from utils.annotations.message import notice, warning
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "test-e2e-playwright"
FILES = ROLE / "files"
HELPER = FILES / "spec_secrets.py"
MASKER = FILES / "spec_secrets_mask.py"
VALUE = "Pa%\"s<w&r'd\\9X é \U0001f600 Sentinel-Value-9f3c abcdefghijklmnopqrstuvwxyz0123456789"
WINDOW = 8
ANSI = re.compile("\x1b?\\[[0-9;]*m")
NETWORK_FAILURE = re.compile(
    r"ENOTFOUND|EAI_AGAIN|ETIMEDOUT|ECONNRESET|ECONNREFUSED|ERR_SOCKET_TIMEOUT"
    r"|no such host|i/o timeout|TLS handshake timeout|connection refused"
    r"|connection reset|Temporary failure in name resolution|toomanyrequests"
    r"|network is unreachable|unexpected EOF|too many requests|\bE(?:5\d\d|429)\b"
    r"|HTTP status:? 5\d\d|Service Unavailable|Bad Gateway|Gateway Time-?out"
    r"|Client\.Timeout|context deadline exceeded",
    re.IGNORECASE,
)
FAILED_CASE = re.compile(r"<(?:failure|error)[\s>]")
SPEC = """\
const fs = require("fs");
const { test, expect } = require("@playwright/test");

const value = fs.readFileSync("/run/spec-secrets/LONG_KEY", "utf8");

test("a failing fill shows no spec secret", async ({ page }) => {
  console.log(`filling ${value}`);
  await page.setContent('<input id="present">');
  await page.locator("#missing").fill(value, { timeout: 2000 });
});

test("a failing value check shows no spec secret", async ({ page }) => {
  await page.setContent('<input id="present">');
  await page.locator("#present").fill(value);
  await expect(page.locator("#present")).toHaveValue(`${value}!`, { timeout: 2000 });
});
"""
TIMEOUTS = {"TEST": "30000", "EXPECT": "2000", "NAVIGATION": "10000", "ACTION": "2000"}
PULL_SECONDS = 300
INSTALL_SECONDS = 240
RUN_SECONDS = 240
TITLE = "Spec secrets real run"


def blocker() -> str:
    """Name what keeps the real run from this host.

    Returns:
        The reason to skip, empty when the run can go ahead.
    """
    if os.environ.get("ACT"):
        return "ACT is set: act runs no nested Playwright container"
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return (
            "GITHUB_ACTIONS is not true: this runs in the 🧪 Test job of"
            " .github/workflows/call-test.yml, step ▶️ Run the full test suite via make"
        )
    if not shutil.which("docker"):
        return "docker is not in PATH"
    return ""


BLOCKER = blocker()


def image() -> tuple[str, str]:
    """Read the Playwright image the role runs and its npm version.

    Returns:
        The image reference and the ``@playwright/test`` version it ships.
    """
    meta = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES), default_if_missing={})
    tag = str(meta["playwright"]["version"])
    return f"{meta['playwright']['image']}:{tag}", re.sub(r"^v|-.*$", "", tag)


def leaks(text: str) -> bool:
    """Tell whether a piece of the value shows, raw or XML-escaped.

    Args:
        text: masked output or report.

    Returns:
        Whether a piece of ``WINDOW`` bytes shows, both cut as UTF-8.
    """
    plain = ANSI.sub("", text)
    raw = VALUE.encode()
    return any(
        raw[at : at + WINDOW] in view
        for view in (plain.encode(), html.unescape(plain).encode())
        for at in range(len(raw) - WINDOW + 1)
    )


def fetch(case: unittest.TestCase, argv: list[str], seconds: int, what: str) -> None:
    """Run a step that reaches a registry, skipping the case on a network failure and failing it on any other.

    Args:
        case: the test case to skip or fail.
        argv: the command, which handles no secret.
        seconds: how long it may take.
        what: the step, for the warning.
    """
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=seconds, check=False
        )
    except subprocess.TimeoutExpired:
        skip(case, f"{what} timed out after {seconds} s")
    if done.returncode == 0:
        return
    lines = done.stderr.strip().splitlines() or [f"exit {done.returncode}"]
    if NETWORK_FAILURE.search(done.stderr):
        skip(case, f"{what} failed: {lines[-1]}")
    case.fail(f"{what} failed: {lines[-1]}")


def skip(case: unittest.TestCase, reason: str) -> NoReturn:
    """Skip the case with a warning annotation that names the reason.

    Args:
        case: the test case to skip.
        reason: what kept the real run from finishing.
    """
    warning(
        f"the real run was skipped: {reason}",
        title=TITLE,
        file=str(ROLE.relative_to(PROJECT_ROOT) / ROLE_FILE_META_SERVICES),
    )
    raise unittest.SkipTest(reason)


def real_run(case: unittest.TestCase) -> tuple[int, str, str]:
    """Install Playwright, then run the specs through the masker without network.

    Args:
        case: the test case to skip on a registry outage.

    Returns:
        The masker's exit code, everything it printed and the JUnit report.
    """
    reference, version = image()
    fetch(case, ["docker", "pull", "--quiet", reference], PULL_SECONDS, reference)
    user = [f"--user={os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]
    with tempfile.TemporaryDirectory() as tmp:
        stage, reports = Path(tmp, "stage"), Path(tmp, "reports")
        (stage / "tests").mkdir(parents=True)
        (stage / "volume").mkdir()
        stage.chmod(0o755)
        env_lines = [f"PLAYWRIGHT_{name}_TIMEOUT={ms}" for name, ms in TIMEOUTS.items()]
        (stage / ".env").write_text(
            "\n".join(["GITHUB_ACTIONS=true", *env_lines, ""]), encoding="utf-8"
        )
        (stage / ".env.keys").write_text("GITHUB_ACTIONS\n", encoding="utf-8")
        reports.mkdir()
        shutil.copy(FILES / "playwright.config.js", stage)
        utils = stage / "tests" / "personas" / "utils"
        utils.mkdir(parents=True)
        shutil.copy(FILES / "personas" / "utils" / "network.js", utils)
        (stage / "tests" / "secret.spec.js").write_text(SPEC, encoding="utf-8")
        install = ["npm", "install", "--no-fund", "--no-audit", "--no-save"]
        fetch(
            case,
            [
                *["docker", "run", "--rm", *user, "-v", f"{stage}:/e2e", "-w", "/e2e"],
                *[reference, *install, f"@playwright/test@{version}"],
            ],
            INSTALL_SECONDS,
            f"@playwright/test@{version} from the npm registry",
        )
        helper = [sys.executable, "-I", "-B", str(HELPER)]
        created = subprocess.run(
            [*helper, "create"], capture_output=True, text=True, check=True
        )
        directory = Path(created.stdout.strip())
        try:
            (directory / ".rendered").write_text(
                f"LONG_KEY={VALUE}\n", encoding="utf-8"
            )
            subprocess.run(
                [*helper, "split", str(directory)], capture_output=True, check=True
            )
            run = ["docker", "run", "--rm", "--ipc=host", "--network=none", *user]
            run += ["--env-file", str(stage / ".env")]
            run += ["-e", "INFINITO_PLAYWRIGHT_NO_CAPTURE=true"]
            run += ["-e", "NO_COLOR=1", "-e", "FORCE_COLOR=0", "--log-driver=none"]
            run += [f"--cidfile={directory}/.cid"]
            run += [
                "--mount",
                f"type=bind,src={directory},dst=/run/spec-secrets,readonly",
            ]
            run += ["-v", f"{stage}:/e2e:ro", "-v", f"{stage}/volume:/volume:ro"]
            run += ["-v", f"{directory}/reports:/reports"]
            run += ["-w", "/e2e", reference]
            masker = [sys.executable, "-I", "-B", str(MASKER)]
            paths = [str(directory), str(reports)]
            try:
                result = subprocess.run(
                    [*masker, "mask", *paths, "--", *run, "--"],
                    capture_output=True,
                    check=False,
                    timeout=RUN_SECONDS,
                )
            except subprocess.TimeoutExpired:
                scrubbed = subprocess.run(
                    [*masker, "scrub", *paths, "docker"],
                    capture_output=True,
                    check=False,
                )
                case.fail(
                    f"the masked run timed out after {RUN_SECONDS} s,"
                    f" scrub exit {scrubbed.returncode}"
                )
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        junit = reports / "playwright-junit.xml"
        report = read_text(str(junit)) if junit.exists() else ""
        printed = result.stdout.decode() + result.stderr.decode()
        return result.returncode, printed, report


@unittest.skipIf(BLOCKER, BLOCKER)
class TestSpecSecretsMaskedInTheRealImage(unittest.TestCase):
    def test_a_failing_fill_in_the_real_image_shows_no_spec_secret(self) -> None:
        code, printed, report = real_run(self)
        found = {
            "exit": code,
            "failed tests": len(FAILED_CASE.findall(report)),
            "masks in output": printed.count("***"),
            "masks in report": report.count("***"),
            "output leaks": leaks(printed),
            "report leaks": leaks(report),
        }
        notice(
            ", ".join(f"{key} {value}" for key, value in found.items()),
            title=TITLE,
            file=str(MASKER.relative_to(PROJECT_ROOT)),
        )
        self.assertEqual(
            {key: found[key] for key in ("exit", "failed tests")},
            {"exit": 1, "failed tests": 2},
        )
        self.assertEqual((found["output leaks"], found["report leaks"]), (False, False))
        self.assertGreater(found["masks in output"], 0)
        self.assertGreater(found["masks in report"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
