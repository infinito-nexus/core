from __future__ import annotations

import importlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import _script_shims
from ._script_shims import HOST, ScriptRunner
from ._semaphore_fake import WORKSPACE_ID

kc = importlib.import_module(
    "tests.unit.python.roles.web-app-keycloak.files.test_usage"
)

OTHER_HOST = "203.0.113.11"
TASK_TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJ0YXNrX2lkIjozMX0.c2lnbmF0dXJl"
COUNTED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
USAGE_SHIM = """
import http.client, io, json, os, sys, urllib.request
from pathlib import Path
args = sys.argv[1:]
operation = json.loads(Path([a[1:] for a in args if a.startswith("@")][0]).read_text())
with open(os.environ["SHIM_RECORD"], "a") as record:
    record.write(json.dumps({"name": "ansible-playbook", "argv": args, "cwd": os.getcwd(),
                             "operation": operation, "env": dict(os.environ)}) + "\\n")
sys.path.insert(0, os.environ["SHIM_KC_PYTHON"])
import usage
class PlainHTTPS(urllib.request.HTTPHandler):
    https_request = urllib.request.AbstractHTTPHandler.do_request_
    def https_open(self, req):
        return self.do_open(http.client.HTTPConnection, req)
usage.tls_opener = lambda cafile: usage.opener(PlainHTTPS())
secret = Path(os.environ["SHIM_KC_SECRET_FILE"]).read_text()
limit = args[args.index("--limit") + 1].split(",")
code = 0
for host, role in json.loads(os.environ["SHIM_KC_HOSTS"]).items():
    if host not in limit:
        continue
    request = {**role, "host": host, "secret": secret if role["enabled"] else "",
               "result_dir": operation["usage_result_dir"]}
    script = os.path.join(os.environ["SHIM_KC_PYTHON"], "usage.py")
    code = usage.main([script], io.StringIO(json.dumps(request))) or code
sys.exit(2 if code else 0)
"""


def usage_env(**overrides):
    """Args:
    overrides: variables to set; None drops one.

    Returns:
        The environment of a scheduled ``usage`` task of a workspace with two hosts.
    """
    env = {
        "SEMAPHORE_JWT": TASK_TOKEN,
        "WORKSPACE": WORKSPACE_ID,
        "WORKSPACE_TARGETS": f"{HOST}:443,{HOST}:22,{OTHER_HOST}:443",
        "WORKSPACE_INVENTORY_FILE": "devices.yml",
    }
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def leaks(run, calls, secret):
    """Args:
    run: the completed process.
    calls: what the playbook shim recorded.
    secret: the value that must not leave the task.

    Returns:
        Every place of the run the value appears in.
    """
    places = [
        name
        for name, text in (("stdout", run.stdout), ("stderr", run.stderr))
        if secret in text
    ]
    places += [f"{c['name']} argv" for c in calls if secret in " ".join(c["argv"])]
    places += [
        f"{c['name']} operation" for c in calls if secret in json.dumps(c["operation"])
    ]
    return places


class UsageScriptTests(unittest.TestCase):
    def setUp(self):
        self.runner = ScriptRunner()
        self.addCleanup(self.runner.cleanup)
        shim = self.runner.bin / "ansible-playbook"
        shim.write_text(f"#!{sys.executable}\n{USAGE_SHIM}", encoding="utf-8")
        self.secret_file = self.runner.tmp / "usage_client_secret"
        self.secret_file.write_text(kc.SECRET, encoding="utf-8")

    def fake(self, users=kc.REALM_USERS):
        fake = kc.FakeKeycloak(users)
        self.addCleanup(fake.stop)
        return fake

    def run_usage(
        self,
        hosts,
        env=None,
        python_dir=kc.PYTHON_DIR,
        args=(),
        directory=_script_shims.SCRIPTS_DIR,
    ):
        """Args:
        hosts: ``{host: (fake or None, enabled)}`` the inventory holds.
        env: the task environment, :func:`usage_env` when None.
        python_dir: the directory holding ``usage.py``.
        args: the command line.
        directory: the folder holding ``usage.sh`` and ``lib.sh``.

        Returns:
            The completed ``usage.sh``.
        """
        roles = {
            host: {
                "enabled": enabled,
                "url": fake.url if fake else "https://keycloak.invalid",
                "realm": kc.REALM,
                "client_id": kc.CLIENT_ID,
                "admin": kc.ADMIN,
                "cafile": "",
            }
            for host, (fake, enabled) in hosts.items()
        }
        return self.runner.run(
            "usage.sh",
            {
                **(usage_env() if env is None else env),
                "SHIM_KC_PYTHON": str(python_dir),
                "SHIM_KC_SECRET_FILE": str(self.secret_file),
                "SHIM_KC_HOSTS": json.dumps(roles),
            },
            args,
            directory,
        )

    def test_usage_ends_with_its_result(self):
        run = self.run_usage({HOST: (self.fake(), True)})
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout.splitlines()[-1])
        self.assertEqual(set(result), {"workspace", "counted_at", "hosts"})
        self.assertEqual(result["workspace"], WORKSPACE_ID)
        self.assertRegex(result["counted_at"], COUNTED_AT)
        self.assertEqual(
            result["hosts"],
            [{"host": HOST, "realm": kc.REALM, "active_users": kc.ACTIVE_PEOPLE}],
        )
        for entry in result["hosts"]:
            self.assertEqual(set(entry), {"host", "realm", "active_users"})
        (call,) = self.runner.calls()
        self.assertEqual(call["cwd"], str(self.runner.src))
        self.assertEqual(
            call["argv"][:5],
            [
                "-i",
                str(self.runner.checkout / "devices.yml"),
                "playbook-usage.yml",
                "--limit",
                f"{HOST},{OTHER_HOST}",
            ],
        )
        self.assertEqual(call["operation"]["ansible_connection"], "local")
        self.assertFalse(Path(call["operation"]["usage_result_dir"]).exists())

    def test_a_host_without_the_usage_client_is_reported_unmeasured(self):
        measured, unmeasured = self.fake(), self.fake()
        run = self.run_usage({HOST: (measured, True), OTHER_HOST: (unmeasured, False)})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            json.loads(run.stdout.splitlines()[-1])["hosts"],
            [
                {"host": HOST, "realm": kc.REALM, "active_users": kc.ACTIVE_PEOPLE},
                {"host": OTHER_HOST, "realm": kc.REALM, "active_users": None},
            ],
        )
        self.assertEqual(unmeasured.calls, [])
        self.assertNotEqual(measured.calls, [])

    def test_usage_refuses_arguments_and_malformed_input(self):
        for name, env, args, message in (
            ("argument", usage_env(), ("all",), "unexpected argument 'all'"),
            ("workspace", usage_env(WORKSPACE="ws-1"), (), "WORKSPACE is malformed"),
            (
                "targets",
                usage_env(WORKSPACE_TARGETS=None),
                (),
                "WORKSPACE_TARGETS is missing",
            ),
        ):
            with self.subTest(name):
                run = self.run_usage({HOST: (None, True)}, env=env, args=args)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn(f"usage.sh: {message}", run.stderr)
                self.assertEqual(self.runner.calls(), [])

    def test_usage_prints_no_secret(self):
        cases = (
            ("run", usage_env(), (), False, 0),
            ("refused run", usage_env(), ("all",), False, 2),
            ("failed run", usage_env(), (), True, 1),
        )
        for name, env, args, fail, code in cases:
            with self.subTest(name):
                fake = self.fake()
                fake.fail = fail
                run = self.run_usage({HOST: (fake, True)}, env=env, args=args)
                self.assertEqual(run.returncode != 0, code != 0, run.stderr)
                calls = self.runner.calls()
                self.assertEqual(leaks(run, calls, TASK_TOKEN), [])
                self.assertEqual(leaks(run, calls, kc.SECRET), [])
                self.assertEqual(
                    [c["name"] for c in calls if kc.SECRET in json.dumps(c["env"])], []
                )

    def test_negative_control_a_usage_py_that_prints_the_secret_is_caught(self):
        source = read_text(str(kc.PYTHON_DIR / "usage.py"))
        planted = source.replace(
            "        request = validated(stdin.read())\n",
            '        request = validated(stdin.read())\n        print(request["secret"])\n',
        )
        self.assertNotEqual(planted, source)
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / "usage.py").write_text(planted, encoding="utf-8")
            run = self.run_usage({HOST: (self.fake(), True)}, python_dir=Path(scratch))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(leaks(run, self.runner.calls(), kc.SECRET), ["stdout"])

    def test_negative_control_a_script_that_prints_the_token_is_caught(self):
        with tempfile.TemporaryDirectory() as scratch:
            drifted = Path(scratch)
            shutil.copy(_script_shims.SCRIPTS_DIR / "lib.sh", drifted / "lib.sh")
            text = read_text(str(_script_shims.SCRIPTS_DIR / "usage.sh"))
            (drifted / "usage.sh").write_text(
                text.replace(
                    'echo "${SCRIPT}: counting',
                    'echo "${SEMAPHORE_JWT}"\necho "${SCRIPT}: counting',
                ),
                encoding="utf-8",
            )
            run = self.run_usage({HOST: (self.fake(), True)}, directory=drifted)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(leaks(run, self.runner.calls(), TASK_TOKEN), ["stdout"])


if __name__ == "__main__":
    unittest.main()
