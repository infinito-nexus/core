from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml

from . import PROJECT_ROOT

HELPER = (
    PROJECT_ROOT / "roles" / "sys-svc-compose" / "tasks" / "utils" / "netns_request.yml"
)
PLAYBOOK = Path(sys.executable).with_name("ansible-playbook")
STATUS_CHECK = "  failed_when: netns_request_answer.rc != 0 or"
SLOW_SECONDS = 2
FAKE = """\
import os
import sys
from pathlib import Path

sys.stdin.read()
state = Path(__file__).resolve().parent / "state"
state.mkdir(exist_ok=True)
mode, name, arg = os.environ["HTTP_URL"].split("/", 3)[3].split("/")
counter = state / (name + ".count")
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(count))
statuses = [int(status) for status in arg.split(",")]
status = statuses[min(count, len(statuses)) - 1]
print('{"status": %d, "content_type": "text/plain", "content": "ANSWERMARK-%s"}' % (status, name))
"""


def _call(name: str, statuses: str, **params) -> dict:
    return {
        "name": f"call {name}",
        "ansible.builtin.include_tasks": "{{ helper }}",
        "vars": {
            "netns_request_argv": "{{ fake_argv }}",
            "netns_request_host": "localhost",
            "netns_request_method": "GET",
            "netns_request_url": f"http://probe/seq/{name}/{statuses}",
            "netns_request_status": [200],
            "netns_request_retries": 0,
            "netns_request_delay": 0,
            "netns_request_no_log": False,
            "netns_request_result": name,
        }
        | params,
    }


def _guarded(name: str, call: dict) -> dict:
    return {
        "name": f"guard {name}",
        "block": [call, {"ansible.builtin.set_fact": {name + "_outcome": "accepted"}}],
        "rescue": [
            {
                "ansible.builtin.set_fact": {
                    name + "_outcome": (
                        "{{ 'failed: ' ~ ansible_failed_result.msg ~ ' '"
                        " ~ ansible_failed_result.stderr | default('') }}"
                    )
                }
            }
        ],
    }


def _slow(name: str, **params) -> dict:
    return _call(
        name,
        "200",
        netns_request_argv="{{ program_argv }}",
        netns_request_url="{{ slow_url }}",
        **params,
    )


class _SlowHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        time.sleep(SLOW_SECONDS)
        try:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SLOWMARK")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args) -> None:
        pass


UNMASKED = _call("unmasked", "200")
del UNMASKED["vars"]["netns_request_no_log"]
TASKS = [
    _guarded("slow", _slow("slow", netns_request_timeout=1)),
    _slow("slow_default"),
    _guarded("bad_timeout", _slow("bad_timeout", netns_request_timeout=0)),
    _guarded("wrong", _call("wrong", "503")),
    _call("retry", "503,503,200", netns_request_retries=3),
    _call("stale", "200"),
    _call("stale", "200", netns_request_skip=True),
    _call("hidden", "200", netns_request_no_log=True),
    _call("shown", "200"),
    _guarded("unmasked", UNMASKED),
    {
        "ansible.builtin.copy": {
            "dest": "{{ out }}",
            "mode": "0644",
            "content": (
                "{{ {'wrong': wrong_outcome, 'retry': retry.status, "
                "'stale_skipped': stale is skipped, 'stale_status': stale.status | default(none), "
                "'unmasked': unmasked_outcome, 'slow': slow_outcome, "
                "'slow_default': slow_default.status, 'bad_timeout': bad_timeout_outcome} | to_json }}"
            ),
        }
    },
]


def _run(root: Path, helper: Path, run: str, slow_url: str) -> dict:
    """Args:
        root: the directory holding ``fake.py``, ``play.yml`` and ``roles``.
        helper: the netns_request tasks file to include.
        run: name of this run's output and state directory.
        slow_url: URL of a server that answers after SLOW_SECONDS.

    Returns:
        ``rc``, the combined ``output`` at -v, the ``facts`` the play wrote, and
        the attempt ``count`` per call name.
    """
    base = root / run
    (base / "state").mkdir(parents=True)
    shutil.copy(root / "fake.py", base / "fake.py")
    out = base / "facts.json"
    extra = {
        "helper": str(helper),
        "fake_argv": [sys.executable, str(base / "fake.py")],
        "program_argv": [sys.executable, "-"],
        "slow_url": slow_url,
        "out": str(out),
        "ansible_become": False,
        "ansible_python_interpreter": sys.executable,
    }
    env = dict(os.environ)
    env.update(
        {
            "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
            "ANSIBLE_HOME": str(base / "ansible-home"),
            "ANSIBLE_LOCAL_TEMP": str(base / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(base / "ansible-remote"),
            "ANSIBLE_NOCOLOR": "1",
        }
    )
    result = subprocess.run(
        [
            str(PLAYBOOK),
            "-v",
            "-i",
            "localhost,",
            str(root / "play.yml"),
            "-e",
            json.dumps(extra),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "rc": result.returncode,
        "output": result.stdout + result.stderr,
        "facts": json.loads(read_text(str(out))) if out.is_file() else {},
        "count": {
            path.stem: int(read_text(str(path)))
            for path in (base / "state").iterdir()
            if path.suffix == ".count"
        },
    }


@unittest.skipUnless(PLAYBOOK.is_file(), f"{PLAYBOOK} is required")
class TestNetnsRequestRuns(unittest.TestCase):
    fixed: ClassVar[dict] = {}
    unchecked: ClassVar[dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "roles").symlink_to(PROJECT_ROOT / "roles")
            (root / "fake.py").write_text(FAKE, encoding="utf-8")
            dump_yaml(
                root / "play.yml",
                [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "tasks": TASKS,
                    }
                ],
            )
            helper = read_text(str(HELPER))
            if STATUS_CHECK not in helper:
                raise AssertionError(f"{HELPER} lost its status check")
            unchecked = root / "netns_request_unchecked.yml"
            unchecked.write_text(
                "\n".join(
                    line
                    for line in helper.splitlines()
                    if not line.startswith(STATUS_CHECK)
                ),
                encoding="utf-8",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
            server.daemon_threads = True
            threading.Thread(target=server.serve_forever, daemon=True).start()
            slow_url = f"http://127.0.0.1:{server.server_address[1]}/slow"
            try:
                cls.fixed = _run(root, HELPER, "fixed", slow_url)
                cls.unchecked = _run(root, unchecked, "unchecked", slow_url)
            finally:
                server.shutdown()
                server.server_close()

    def test_the_play_completes(self) -> None:
        self.assertEqual(0, self.fixed["rc"], self.fixed["output"])

    def test_a_single_attempt_with_a_wrong_status_fails(self) -> None:
        self.assertTrue(self.fixed["facts"]["wrong"].startswith("failed: "))
        self.assertEqual(1, self.fixed["count"]["wrong"])

    def test_retries_repeat_until_an_accepted_status(self) -> None:
        self.assertEqual(200, self.fixed["facts"]["retry"])
        self.assertEqual(3, self.fixed["count"]["retry"])

    def test_a_skip_replaces_the_earlier_result(self) -> None:
        self.assertIs(True, self.fixed["facts"]["stale_skipped"])
        self.assertIsNone(self.fixed["facts"]["stale_status"])
        self.assertEqual(1, self.fixed["count"]["stale"])

    def test_no_log_hides_the_answer_at_verbose_level(self) -> None:
        self.assertIn("ANSWERMARK-shown", self.fixed["output"])
        self.assertNotIn("ANSWERMARK-hidden", self.fixed["output"])

    def test_no_log_hides_the_url_in_the_task_title(self) -> None:
        self.assertIn("/seq/shown/", self.fixed["output"])
        self.assertNotIn("/seq/hidden/", self.fixed["output"])

    def test_the_timeout_ends_an_attempt_against_a_hanging_endpoint(self) -> None:
        self.assertTrue(self.fixed["facts"]["slow"].startswith("failed: "))

    def test_negative_control_without_the_timeout_the_same_endpoint_answers(
        self,
    ) -> None:
        self.assertEqual(200, self.fixed["facts"]["slow_default"])

    def test_a_timeout_that_is_no_positive_integer_is_refused(self) -> None:
        self.assertIn(
            "HTTP_TIMEOUT must be a positive integer",
            self.fixed["facts"]["bad_timeout"],
        )

    def test_a_call_without_its_mask_is_refused(self) -> None:
        self.assertIn("netns_request_no_log", self.fixed["facts"]["unmasked"])
        self.assertNotIn("unmasked", self.fixed["count"])

    def test_negative_control_without_failed_when_a_wrong_status_passes(self) -> None:
        self.assertEqual(0, self.unchecked["rc"], self.unchecked["output"])
        self.assertEqual("accepted", self.unchecked["facts"]["wrong"])


if __name__ == "__main__":
    unittest.main()
