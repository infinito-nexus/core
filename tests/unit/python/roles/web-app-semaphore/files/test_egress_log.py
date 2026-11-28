from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
PROBE = ROLE / "files" / "test" / "egress_log.py"
SPEC = ROLE / "files" / "playwright" / "test-workspace-runners.js"
TEST_ENV = ROLE / "templates" / "test.env.j2"
TEST_SH = ROLE / "files" / "test" / "test.sh"
COMPOSE = ROLE / "templates" / "workspace" / "compose.yml.j2"
VARS = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
SERVICE = "egress"
TARGET = "203.0.113.1:443"
LISTED = "203.0.113.5:22"
METADATA = "169.254.169.254:80"
WORKSPACE = "ws-0b6f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4"
EGRESS = f"semaphore-{WORKSPACE}-{SERVICE}-1"
RUNNER = f"semaphore-{WORKSPACE}-runner-1"
SERVER = "semaphore"


def load_probe():
    """Returns:
    The module ``files/test/egress_log.py``.
    """
    spec = spec_from_file_location("semaphore_egress_log", str(PROBE))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def entry(container, message):
    """Args:
    container: ``CONTAINER_NAME`` of the journal entry.
    message: its ``MESSAGE``.

    Returns:
        The entry as one ``journalctl --output=json`` line.
    """
    return json.dumps({"CONTAINER_NAME": container, "MESSAGE": message})


def squid(result, target):
    """Args:
    result: ``<action>/<code>`` of the access log line.
    target: the CONNECT target.

    Returns:
        A Squid access log line in its native format.
    """
    return (
        f"1763672400.123     12 172.30.12.3 {result} 3940 CONNECT {target} "
        "- HIER_NONE/- text/html"
    )


def env_value(key):
    """Args:
    key: a key of ``templates/test.env.j2``.

    Returns:
        Its value as the template writes it.
    """
    return next(
        line.partition("=")[2]
        for line in read_text(str(TEST_ENV)).splitlines()
        if line.startswith(f"{key}=")
    )


class TestEgressLog(unittest.TestCase):
    def setUp(self):
        self.probe = load_probe()

    def run_probe(self, lines):
        """Args:
        lines: the journal lines the probe reads.

        Returns:
            ``(status, line)`` of the probe for ``TARGET``.
        """
        counts = self.probe.connects(lines, SERVICE, TARGET)
        return self.probe.verdict(*counts, TARGET)

    def test_a_refusal_the_egress_proxy_logged_passes(self):
        lines = [
            entry(EGRESS, squid("TCP_TUNNEL/200", LISTED)),
            entry(EGRESS, squid("TCP_DENIED/403", TARGET)),
            entry(SERVER, "task 12 finished"),
        ]
        self.assertEqual(self.probe.connects(lines, SERVICE, TARGET), (2, 1, 0))
        self.assertEqual(
            self.run_probe(lines),
            (0, f"OK: 1 TCP_DENIED/403 CONNECT {TARGET} in the egress log"),
        )

    def test_a_boot_whose_egress_spec_did_not_run_is_reported_apart(self):
        logs = {
            "no egress proxy logged": [entry(SERVER, "task 12 finished"), ""],
            "other egress traffic only": [
                entry(EGRESS, squid("TCP_TUNNEL/200", LISTED)),
                entry(EGRESS, squid("TCP_DENIED/403", METADATA)),
            ],
        }
        for name, lines in logs.items():
            with self.subTest(name):
                status, line = self.run_probe(lines)
                self.assertEqual(status, 2, line)
                self.assertTrue(line.startswith("NOT RUN: "), line)

    def test_a_run_that_reached_the_target_without_a_refusal_fails(self):
        logs = {
            "the target let through": [entry(EGRESS, squid("TCP_TUNNEL/200", TARGET))],
            "a refusal beside a tunnel": [
                entry(EGRESS, squid("TCP_DENIED/403", TARGET)),
                entry(EGRESS, squid("TCP_TUNNEL/200", TARGET)),
            ],
            "another denial code": [entry(EGRESS, squid("TCP_DENIED/407", TARGET))],
        }
        for name, lines in logs.items():
            with self.subTest(name):
                status, line = self.run_probe(lines)
                self.assertEqual(status, 1, line)
                self.assertTrue(line.startswith("FAIL: "), line)

    def test_negative_control_a_refusal_another_container_echoed_is_no_pass(self):
        lines = [
            entry(EGRESS, squid("TCP_TUNNEL/200", LISTED)),
            entry(RUNNER, squid("TCP_DENIED/403", TARGET)),
        ]
        self.assertEqual(self.run_probe(lines)[0], 2)
        self.assertNotEqual(self.probe.CONTAINER, ".*")
        with mock.patch.object(self.probe, "CONTAINER", ".*"):
            self.assertEqual(self.run_probe(lines)[0], 0)

    def test_the_probe_prints_counts_and_the_target_only(self):
        secret = "password=Canary-Pass-1"
        lines = [
            entry(EGRESS, f"{squid('TCP_DENIED/403', TARGET)} {secret}"),
            entry(SERVER, secret),
        ]
        for status, line in (self.run_probe(lines), self.run_probe(lines[1:])):
            with self.subTest(line):
                self.assertNotIn(secret, line)
                self.assertIn(status, (0, 1, 2))

    def test_the_cli_test_checks_the_target_the_spec_refuses(self):
        spec = re.search(r'const UNLISTED_PUBLIC = "([^"]+)";', read_text(str(SPEC)))
        self.assertEqual(env_value("SEMAPHORE_TEST_REFUSED_TARGET"), spec.group(1))
        self.assertEqual(spec.group(1), TARGET)
        self.assertEqual(
            env_value("SEMAPHORE_TEST_EGRESS_SERVICE"),
            "{{ SEMAPHORE_EGRESS_SERVICE }}",
        )
        self.assertEqual(VARS["SEMAPHORE_EGRESS_SERVICE"], SERVICE)
        self.assertEqual(VARS["SEMAPHORE_WORKSPACE_ALIAS"], "ws-{{ WORKSPACE }}")
        self.assertIn(
            'name: "semaphore-{{ semaphore_workspace_alias }}"', read_text(str(COMPOSE))
        )
        self.assertRegex(EGRESS, self.probe.CONTAINER.format(service=SERVICE))
        self.assertNotRegex(RUNNER, self.probe.CONTAINER.format(service=SERVICE))
        self.assertIn(
            'python3 -I "${probe}" "${SEMAPHORE_TEST_EGRESS_SERVICE}" '
            '"${SEMAPHORE_TEST_REFUSED_TARGET}"',
            read_text(str(TEST_SH)),
        )


FIXTURE = ROLE / "files" / "playwright" / "workspace-fixture.js"
PLAYWRIGHT_ENV = ROLE / "templates" / "playwright.env.j2"
SKIP_LINE = 'if [ -n "${SEMAPHORE_TEST_WORKSPACES_SKIP}" ]; then'
REQUIRE = re.compile(r"function requireWorkspaces\(\) \{\n(.*?)\n\}", re.DOTALL)
OWN_SKIP = (
    "  function requireWorkspaces() {\n"
    '    shared.skipUnlessServiceEnabled("sso");\n'
    "  }\n"
)
R8_SKIP = 'if [ "${SEMAPHORE_TEST_WORKSPACES_ENABLED}" != "true" ]; then'
PLAYWRIGHT_SKIP = (
    "SEMAPHORE_WORKSPACES_SKIP={{ SEMAPHORE_WORKSPACES_SKIP | dotenv_quote }}"
)
MARK_LINE = 'if [ -z "${SEMAPHORE_TEST_JOURNAL_SINCE}" ]; then'
STALE, MARK, FRESH = 1_700_000_000, 1_700_000_100, 1_700_000_200
SINCE_READ = 'journalctl --since "@${SEMAPHORE_TEST_JOURNAL_SINCE}"'
BOOT_READ = "journalctl --boot"
JOURNAL_STUB = f"""#!{sys.executable} -I
import json
import os
import sys

floor = None
if "--since" in sys.argv:
    floor = int(sys.argv[sys.argv.index("--since") + 1].removeprefix("@"))
with open(os.environ["ENTRIES"], encoding="utf-8") as handle:
    for stamp, container, message in json.load(handle):
        if floor is None or stamp >= floor:
            print(json.dumps({{"CONTAINER_NAME": container, "MESSAGE": message}}))
"""


def cli_check(test_sh, entries, since=str(MARK)):
    """Args:
    test_sh: the text of ``files/test/test.sh``, possibly planted.
    entries: ``(epoch, CONTAINER_NAME, MESSAGE)`` of every entry the journal
        of the stack host holds, before and after the mark.
    since: ``SEMAPHORE_TEST_JOURNAL_SINCE``, the epoch the role deploy marked.

    Returns:
        ``(status, line)`` of the CLI check on the stack host, read through a
        ``journalctl`` that honours ``--since @<epoch>`` and reads the whole
        boot without it.
    """
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        stubs = root / "bin"
        stubs.mkdir()
        (stubs / "journalctl").write_text(JOURNAL_STUB)
        (stubs / "journalctl").chmod(0o755)
        (root / "entries.json").write_text(json.dumps(list(entries)))
        (root / "test").mkdir()
        (root / "test" / "test.sh").write_text(test_sh)
        (root / "test" / "egress_log.py").write_text(read_text(str(PROBE)))
        run = subprocess.run(
            ["bash", str(root / "test" / "test.sh")],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
            env={
                "PATH": f"{stubs}:{os.environ['PATH']}",
                "ENTRIES": str(root / "entries.json"),
                "SEMAPHORE_TEST_EGRESS_SERVICE": SERVICE,
                "SEMAPHORE_TEST_IS_STACK_HOST": "true",
                "SEMAPHORE_TEST_JOURNAL_SINCE": since,
                "SEMAPHORE_TEST_LOG_TAG": "web-app-semaphore",
                "SEMAPHORE_TEST_REFUSED_TARGET": TARGET,
                "SEMAPHORE_TEST_WORKSPACES_SKIP": "",
            },
        )
        return run.returncode, run.stdout.strip()


STALE_REFUSAL = (STALE, EGRESS, squid("TCP_DENIED/403", TARGET))
STALE_TUNNEL = (STALE, EGRESS, squid("TCP_TUNNEL/200", TARGET))
FRESH_REFUSAL = (FRESH, EGRESS, squid("TCP_DENIED/403", TARGET))


class TestJournalSinceMark(unittest.TestCase):
    def setUp(self):
        self.test_sh = read_text(str(TEST_SH))

    def test_only_the_lines_after_the_mark_decide(self):
        self.assertEqual(cli_check(self.test_sh, [STALE_REFUSAL])[0], 2)
        self.assertEqual(cli_check(self.test_sh, [STALE_TUNNEL, FRESH_REFUSAL])[0], 0)

    def test_a_run_without_a_mark_skips(self):
        status, line = cli_check(self.test_sh, [STALE_REFUSAL], since="")
        self.assertEqual(status, 0)
        self.assertTrue(line.startswith("SKIP: this run deployed no "), line)

    def test_negative_control_a_boot_wide_read_lets_a_stale_line_decide(self):
        self.assertEqual(self.test_sh.count(SINCE_READ), 1)
        planted = self.test_sh.replace(SINCE_READ, BOOT_READ)
        self.assertEqual(cli_check(planted, [STALE_REFUSAL])[0], 0)
        self.assertEqual(cli_check(planted, [STALE_TUNNEL, FRESH_REFUSAL])[0], 1)

    def test_the_role_deploy_marks_the_stack_host_journal_for_the_check(self):
        tasks = load_yaml_str(read_text(str(ROLE / "tasks" / "00_core.yml")))
        mark = tasks[-1]
        self.assertEqual(mark["register"], "semaphore_journal_mark")
        self.assertEqual(mark["ansible.builtin.command"]["argv"], ["date", "+%s"])
        self.assertEqual(mark["when"], "IS_STACK_HOST | bool")
        self.assertIn(
            "semaphore_journal_mark.stdout", env_value("SEMAPHORE_TEST_JOURNAL_SINCE")
        )


def skip_findings(test_sh, fixture, runners):
    """Args:
    test_sh: the text of ``files/test/test.sh``, possibly planted.
    fixture: the text of ``workspace-fixture.js``.
    runners: the text of the workspace runners spec, possibly planted.

    Returns:
        Every skip of the CLI check or of the workspace specs that reads
        another source than ``SEMAPHORE_WORKSPACES_SKIP``.
    """
    findings = []
    if env_value("SEMAPHORE_TEST_WORKSPACES_SKIP") != (
        "{{ SEMAPHORE_WORKSPACES_SKIP | quote }}"
    ):
        findings.append("test.env carries another skip")
    if PLAYWRIGHT_SKIP not in read_text(str(PLAYWRIGHT_ENV)):
        findings.append("playwright.env carries another skip")
    findings += [
        f"test.sh skips on {line}"
        for line in test_sh.splitlines()
        if line.startswith("if [")
        and "SEMAPHORE_TEST_IS_STACK_HOST" not in line
        and line not in (SKIP_LINE, MARK_LINE)
    ]
    body = REQUIRE.search(fixture).group(1)
    if "process.env.SEMAPHORE_WORKSPACES_SKIP" not in body or "shared." in body:
        findings.append("the fixture skips on another source")
    if "function requireWorkspaces" in runners:
        findings.append("the runners spec skips on its own")
    return findings


class TestOneSkipSource(unittest.TestCase):
    def setUp(self):
        self.test_sh = read_text(str(TEST_SH))
        self.fixture = read_text(str(FIXTURE))
        self.runners = read_text(str(SPEC))

    def test_the_cli_check_and_the_specs_skip_on_one_reason(self):  # nocheck: test.text-presence -- cross-file lint: one skip source, mutation-tested  # fmt: skip
        self.assertEqual(skip_findings(self.test_sh, self.fixture, self.runners), [])

    def test_negative_control_an_own_skip_on_either_side_is_caught(self):
        self.assertEqual(self.test_sh.count(SKIP_LINE), 1)
        planted_sh = self.test_sh.replace(SKIP_LINE, R8_SKIP)
        planted_spec = self.runners.replace(
            "exports.register = function (shared) {\n",
            f"exports.register = function (shared) {{\n{OWN_SKIP}",
        )
        self.assertEqual(
            skip_findings(planted_sh, self.fixture, planted_spec),
            [f"test.sh skips on {R8_SKIP}", "the runners spec skips on its own"],
        )


if __name__ == "__main__":
    unittest.main()
