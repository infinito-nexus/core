from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.platform_monitoring import agent_key_line, configuration_base, digest_path

from .test_host import HELPER, LOGIN, ReleaseHost, blob, load, public_key

DIGEST = digest_path(configuration_base(PROJECT_ROOT))
CHECKMK = "192.0.2.7"
DIGEST_HELPER = (
    PROJECT_ROOT / "roles/svc-net-platform-monitoring/files/python/digest_line.py"
)
HOLD_LOCK = (
    "import fcntl, os, sys, time\n"
    "handle = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)\n"
    "fcntl.flock(handle, fcntl.LOCK_EX)\n"
    "print('held', flush=True)\n"
    "time.sleep(1)\n"
)
SEGMENT = "target"
WORKSPACE = "0a1b2c3d-0000-4000-8000-00000000000a"
AGENT_BODY = "#!/bin/sh\n"
AGENT_SHA = hashlib.sha256(AGENT_BODY.encode()).hexdigest()
OTHER_LINE = f"worker {'2' * 64}\n"
OWN_LINE = f"{SEGMENT} {'0' * 64}\n"


class ReleaseHostMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.mod = load(HELPER, "release_host")
        self.keys = ReleaseHost(self)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        for path, body in (
            (self.mod.AGENT_MARKER, f"{AGENT_SHA}\n"),
            (self.mod.AGENT_SCRIPT, AGENT_BODY),
            (DIGEST, OWN_LINE),
        ):
            target = self.host_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        self.agent = public_key()
        self.customer = public_key()
        self.monitoring_line = agent_key_line(public_key(), CHECKMK, WORKSPACE)
        self.write_keys()

    def host_path(self, absolute):
        return self.root / absolute.lstrip("/")

    def write_keys(self):
        self.keys.write(
            self.keys.keys(LOGIN),
            [f"{self.agent} workspace", f"{self.customer} me", self.monitoring_line],
        )

    def login_keys(self):
        return self.keys.keys(LOGIN).read_text(
            encoding="utf-8"
        )  # nocheck: cache-read tempdir

    def release(self, monitoring=None, action="apply", flags=("--monitoring",)):
        stdout = io.StringIO()
        arguments = self.mod.parser().parse_args(
            [
                action,
                "--login",
                LOGIN,
                "--app-control-user",
                "app-control",
                "--backup-user",
                "backup",
                "--agent-key",
                *blob(self.agent),
                "--federation-digest",
                DIGEST,
                *flags,
            ]
        )
        code = self.mod.release(
            arguments,
            stdout,
            self.keys.home,
            str(self.keys.sudoers),
            self.mod.keygen_accepts,
            monitoring or self.mod.Monitoring(self.root, [DIGEST]),
        )
        return code, json.loads(stdout.getvalue().splitlines()[-1])

    def removed(self, result):
        return {name: result["removed"][name] for name in self.mod.MONITORING_COUNTS}

    def test_release_removes_the_agent_its_key_line_and_the_digest(self):
        code, result = self.release()
        self.assertEqual(code, 0)
        self.assertEqual(
            self.removed(result),
            {"federation_token": 1, "monitoring_agent": 1, "monitoring_key": 1},
        )
        self.assertFalse(self.host_path(self.mod.AGENT_SCRIPT).exists())
        self.assertFalse(self.host_path(self.mod.AGENT_MARKER).exists())
        self.assertFalse(self.host_path(DIGEST).exists())
        self.assertNotIn(self.monitoring_line, self.login_keys())
        self.assertIn(self.customer, self.login_keys())

    def test_an_agent_the_host_installed_otherwise_stays(self):
        self.host_path(self.mod.AGENT_MARKER).unlink()
        code, result = self.release()
        self.assertEqual(code, 0, result)
        self.assertEqual(
            self.removed(result),
            {"federation_token": 1, "monitoring_agent": 0, "monitoring_key": 1},
        )
        self.assertTrue(self.host_path(self.mod.AGENT_SCRIPT).exists())
        self.assertNotIn(self.monitoring_line, self.login_keys())

    def test_a_marker_without_its_script_is_dropped(self):
        self.host_path(self.mod.AGENT_SCRIPT).unlink()
        code, result = self.release()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["removed"]["monitoring_agent"], 0)
        self.assertFalse(self.host_path(self.mod.AGENT_MARKER).exists())

    def test_the_share_step_removes_the_share_and_keeps_every_key(self):
        before = self.keys.snapshot()
        code, result = self.release(action="share")
        self.assertEqual(code, 0, result)
        self.assertEqual(
            result, {"removed": {"federation_token": 1, "monitoring_agent": 1}}
        )
        self.assertEqual(set(result["removed"]), set(self.mod.SHARE_COUNTS))
        self.assertFalse(self.host_path(self.mod.AGENT_SCRIPT).exists())
        self.assertFalse(self.host_path(DIGEST).exists())
        self.assertEqual(self.keys.snapshot(), before)
        code, result = self.release()
        self.assertEqual(code, 0, result)
        self.assertEqual(
            self.removed(result),
            {"federation_token": 0, "monitoring_agent": 0, "monitoring_key": 1},
        )
        self.assertNotIn(self.monitoring_line, self.login_keys())

    def test_a_share_step_the_host_refuses_writes_nothing(self):
        self.keys.write(self.keys.keys(LOGIN), [f"{self.agent} workspace"])
        code, result = self.release(action="share")
        self.assertEqual(code, 2)
        self.assertIn("refused", result)
        self.assertTrue(self.host_path(self.mod.AGENT_SCRIPT).exists())
        self.assertTrue(self.host_path(DIGEST).exists())

    def test_a_second_release_removes_nothing_more(self):
        self.assertEqual(self.release()[0], 0)
        self.keys.write(
            self.keys.keys(LOGIN), [f"{self.agent} workspace", f"{self.customer} me"]
        )
        code, result = self.release()
        self.assertEqual(code, 0)
        self.assertEqual(
            self.removed(result), dict.fromkeys(self.mod.MONITORING_COUNTS, 0)
        )

    def test_an_agent_that_outlives_its_removal_fails_and_keeps_every_key(self):
        mod = self.mod

        class Stuck(mod.Monitoring):
            def remove(self):
                return {"monitoring_agent": 0, "federation_token": 0}

        before = self.keys.snapshot()
        code, result = self.release(monitoring=Stuck(self.root, [DIGEST]))
        self.assertEqual(code, 1)
        self.assertIn(
            f"the agent {mod.AGENT_SCRIPT} is still installed", result["failed"]
        )
        self.assertIn(f"the digest file {DIGEST} still exists", result["failed"])
        self.assertEqual(self.keys.snapshot(), before)

    def test_a_stopped_instance_releases_without_any_http_round_trip(self):
        network = [
            name
            for name in ("socket", "ssl", "http", "urllib")
            if hasattr(self.mod, name)
        ]
        self.assertEqual(network, [])
        code, result = self.release()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["removed"]["federation_token"], 1)
        self.assertFalse(self.host_path(DIGEST).exists())

    def test_negative_control_a_digest_left_on_disk_fails_the_proof(self):
        mod = self.mod
        held = self.host_path(DIGEST)

        class Rewritten(mod.Monitoring):
            def remove(self):
                removed = super().remove()
                held.write_text(OWN_LINE, encoding="utf-8")
                return removed

        before = self.keys.snapshot()
        code, result = self.release(monitoring=Rewritten(self.root, [DIGEST]))
        self.assertEqual(code, 1)
        self.assertIn(f"the digest file {DIGEST} still exists", result["failed"])
        self.assertEqual(self.keys.snapshot(), before)

    def test_a_never_monitored_host_releases_without_a_federation_digest(self):
        arguments = self.mod.parser().parse_args(
            [
                "share",
                "--login",
                LOGIN,
                "--app-control-user",
                "a",
                "--backup-user",
                "b",
                "--agent-key",
                *blob(self.agent),
            ]
        )
        self.assertEqual(arguments.federation_digest, [])
        self.host_path(DIGEST).unlink()
        code, result = self.release(
            monitoring=self.mod.Monitoring(self.root, []), action="share"
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(
            result, {"removed": {"federation_token": 0, "monitoring_agent": 1}}
        )
        self.assertFalse(self.host_path(self.mod.AGENT_SCRIPT).exists())

    def test_every_digest_file_a_core_ever_wrote_is_removed_and_proven(self):
        old = "/etc/old-core/conf.d/federate.sha256"
        target = self.host_path(old)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(OWN_LINE, encoding="utf-8")
        arguments = self.mod.parser().parse_args(
            [
                "share",
                "--login",
                LOGIN,
                "--app-control-user",
                "a",
                "--backup-user",
                "b",
                "--agent-key",
                *blob(self.agent),
                "--federation-digest",
                DIGEST,
                old,
            ]
        )
        self.assertEqual(arguments.federation_digest, [DIGEST, old])
        monitoring = self.mod.Monitoring(self.root, arguments.federation_digest)
        code, result = self.release(monitoring=monitoring, action="share")
        self.assertEqual(code, 0, result)
        self.assertFalse(self.host_path(DIGEST).exists())
        self.assertFalse(target.exists())
        target.write_text(OWN_LINE, encoding="utf-8")
        self.assertEqual(monitoring.proof(), [f"the digest file {old} still exists"])

    def test_without_a_federation_digest_the_agent_is_still_proven_gone(self):
        mod = self.mod

        class Stuck(mod.Monitoring):
            def remove(self):
                return {"monitoring_agent": 0, "federation_token": 0}

        code, result = self.release(monitoring=Stuck(self.root, []))
        self.assertEqual(code, 1)
        self.assertEqual(
            result["failed"], f"the agent {mod.AGENT_SCRIPT} is still installed"
        )

    def test_a_failing_removal_fails_before_any_key_write(self):
        self.host_path(DIGEST).unlink()
        self.host_path(DIGEST).mkdir()
        before = self.keys.snapshot()
        code, result = self.release()
        self.assertEqual(code, 1)
        self.assertIn("could not be removed", result["failed"])
        self.assertEqual(self.keys.snapshot(), before)

    def test_a_key_line_that_comes_back_fails_the_release(self):
        mod = self.mod
        keys = self.keys.keys(LOGIN)
        line = self.monitoring_line
        original = mod.apply

        def apply_and_readd(writes):
            original(writes)
            with keys.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

        mod.apply = apply_and_readd
        code, result = self.release()
        self.assertEqual(code, 1)
        self.assertIn(
            f"{keys} still lets the platform monitoring key in", result["failed"]
        )

    def test_a_refusal_writes_no_monitoring_change(self):
        self.keys.write(self.keys.keys(LOGIN), [f"{self.agent} workspace"])
        code, result = self.release()
        self.assertEqual(code, 2)
        self.assertIn("refused", result)
        self.assertTrue(self.host_path(self.mod.AGENT_SCRIPT).exists())
        self.assertTrue(self.host_path(DIGEST).exists())

    def test_the_check_refuses_like_the_release_and_writes_nothing(self):
        before = self.keys.snapshot()
        self.assertEqual(self.release(action="check"), (0, {"checked": True}))
        self.assertEqual(self.keys.snapshot(), before)
        self.assertTrue(self.host_path(self.mod.AGENT_SCRIPT).exists())
        self.assertTrue(self.host_path(DIGEST).exists())
        self.keys.write(self.keys.keys(LOGIN), [f"{self.agent} workspace"])
        code, result = self.release(action="check")
        self.assertEqual(code, 2)
        self.assertEqual(result, self.release()[1])

    def test_releasing_the_stack_host_takes_every_digest_line(self):
        held = self.host_path(DIGEST)
        held.write_text(OWN_LINE + OTHER_LINE, encoding="utf-8")
        code, result = self.release(action="share")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["removed"]["federation_token"], 1)
        self.assertFalse(held.exists())

    def test_a_deploy_edit_waits_for_the_release_lock(self):
        held = self.host_path(DIGEST)
        helper = DIGEST_HELPER
        self.assertEqual(self.mod.DIGEST_LOCK, load(helper, "digest_line").LOCK_SUFFIX)
        monitoring = self.mod.Monitoring(self.root, [DIGEST])
        with self.mod.digest_lock(held):
            deploy = subprocess.Popen(
                [sys.executable, str(helper), str(held), "worker", OTHER_LINE.strip()],
                stdout=subprocess.PIPE,
                text=True,
            )
            time.sleep(0.5)
            self.assertIsNone(deploy.poll())
            waiting = held.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
            self.assertEqual(waiting, OWN_LINE)
        self.assertEqual(deploy.communicate(timeout=30)[0], "changed\n")
        edited = held.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertEqual(edited, OWN_LINE + OTHER_LINE)
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLD_LOCK, f"{held}{self.mod.DIGEST_LOCK}"],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.assertEqual(holder.stdout.readline(), "held\n")
        started = time.monotonic()
        self.assertEqual(monitoring.remove()["federation_token"], 1)
        self.assertGreaterEqual(time.monotonic() - started, 0.5)
        self.assertFalse(held.exists())

    def test_an_agent_another_install_changed_stays_and_its_marker_goes(self):
        script = self.host_path(self.mod.AGENT_SCRIPT)
        script.write_text("#!/bin/sh\necho foreign\n", encoding="utf-8")
        code, result = self.release()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["removed"]["monitoring_agent"], 0)
        self.assertTrue(script.exists())
        self.assertFalse(self.host_path(self.mod.AGENT_MARKER).exists())

    def test_without_monitoring_apply_counts_the_base_counts_alone(self):
        self.host_path(self.mod.AGENT_MARKER).unlink()
        self.host_path(DIGEST).unlink()
        self.keys.write(
            self.keys.keys(LOGIN), [f"{self.agent} workspace", f"{self.customer} me"]
        )
        code, result = self.release(flags=())
        self.assertEqual(code, 0, result)
        self.assertEqual(list(result["removed"]), list(self.mod.BASE_COUNTS))
        self.assertTrue(self.host_path(self.mod.AGENT_SCRIPT).exists())

    def test_without_monitoring_a_host_holding_the_share_is_refused(self):
        lines = [f"{self.agent} workspace", f"{self.customer} me"]
        for name, marked, line, digest in (
            ("marker", True, False, False),
            ("key line", False, True, False),
            ("digest file", False, False, True),
        ):
            with self.subTest(name):
                marker = self.host_path(self.mod.AGENT_MARKER)
                held = self.host_path(DIGEST)
                if marked:
                    marker.write_text("x\n", encoding="utf-8")
                else:
                    marker.unlink(missing_ok=True)
                if digest:
                    held.write_text(OTHER_LINE, encoding="utf-8")
                else:
                    held.unlink(missing_ok=True)
                self.keys.write(
                    self.keys.keys(LOGIN),
                    [*lines, self.monitoring_line] if line else lines,
                )
                before = self.keys.snapshot()
                checked = self.release(action="check", flags=())
                code, result = self.release(flags=())
                self.assertEqual(code, 2, result)
                self.assertEqual(checked, (code, result))
                self.assertIn(name, result["refused"])
                self.assertIn("release it while the platform runs", result["refused"])
                self.assertEqual(self.keys.snapshot(), before)
                self.assertEqual(held.exists(), digest)

    def test_a_line_written_before_the_workspace_binding_is_released_too(self):
        self.monitoring_line = (
            f'command="check_mk_agent",restrict,from="{CHECKMK}" '
            f"{public_key()} infinito-platform-monitoring"
        )
        self.write_keys()
        code, result = self.release()
        self.assertEqual((code, self.removed(result)["monitoring_key"]), (0, 1))
        self.assertNotIn(self.monitoring_line, self.login_keys())

    def test_only_the_forced_command_line_counts_as_the_monitoring_key(self):
        self.assertTrue(self.mod.monitoring_key_line(self.monitoring_line))
        for line in (
            f"{self.customer} infinito-platform-monitoring",
            f'command="check_mk_agent" {self.customer} me',
            f'command="check_mk_agent",restrict {self.customer} other',
        ):
            with self.subTest(line=line):
                self.assertFalse(self.mod.monitoring_key_line(line))


if __name__ == "__main__":
    unittest.main()
