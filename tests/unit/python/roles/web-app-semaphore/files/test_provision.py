from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from .provision._fake_provision import (
    CREDENTIALS,
    JWT,
    STATE_KEYS,
    WORKSPACE,
    FakePlatform,
    load,
)

provision = load("provision")
RefusedError = provision.inputs.RefusedError
SCS = CREDENTIALS["providers"]["scs"]
CUSTOMER_SCS = f"tenant/data/{WORKSPACE}-provision/providers/scs"
PLATFORM_SCS = f"tenant/data/{WORKSPACE}-provision/scs"
CUSTOMER_FIELDS = {
    "hetzner": {"token"},
    "ionos": {"token"},
    "scs": {"application_credential_id", "application_credential_secret"},
}
CATALOG_REGION = {
    "auth_url": "https://keystone.catalog.example.org/v3",
    "region": "RegionCatalog",
    "network": "public",
}
CUSTOMER = {
    "application_credential_id": "customer-credential-id",
    "application_credential_secret": "customer-credential-secret",
}
PLATFORM = {
    "auth_url": "https://keystone.platform.example.org/v3",
    "region_name": "RegionPlatform",
    "application_credential_id": "platform-credential-id",
    "application_credential_secret": "platform-credential-secret",
}
FOREIGN_ENDPOINT = {
    "auth_url": "https://keystone.customer-chosen.example.net/v3",
    "region_name": "RegionCustomer",
}
TEST_BUDGET = dt.timedelta(hours=1)
READY_BOUND = 30
READY_POLL = 0.01
CLEANUP_PAUSE = 0.5
TOFU_REPORT = ("pid", "group", "parent", "plugin")
RUNNER = """
import importlib.util, os, pathlib, sys
python = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(python))
spec = importlib.util.spec_from_file_location("runner", python / "provision.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.tofu(pathlib.Path(sys.argv[2]), dict(os.environ), "apply")
"""
SLOW_TOFU = """#!{python}
import os, pathlib, signal, subprocess, sys, time
signal.signal(signal.SIGINT, signal.SIG_IGN)
plugin = 0
if os.environ["FAKE_TOFU_PLUGIN"] == "spawn":
    plugin = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]).pid
lock = pathlib.Path.cwd() / "state.tflock"
mode = os.environ["FAKE_TOFU_SIGINT"]
def interrupted(_signum, _frame):
    (pathlib.Path.cwd() / "sigint").write_text("received", encoding="utf-8")
    if mode == "trap":
        lock.unlink(missing_ok=True)
        sys.exit(130)
signal.signal(signal.SIGINT, signal.SIG_IGN if mode == "ignore" else interrupted)
lock.write_text("held", encoding="utf-8")
ready = pathlib.Path(os.environ["FAKE_TOFU_READY"])
part = ready.with_name(ready.name + ".part")
part.write_text(
    "%d %d %d %d" % (os.getpid(), os.getpgrp(), os.getppid(), plugin), encoding="utf-8"
)
part.replace(ready)
time.sleep(60)
"""


class TempCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)


class TestBackend(TempCase):
    def setUp(self):
        super().setUp()
        self.config = {"cafile": "", "state": "https://s3.example.org"}

    def test_values_are_escaped_for_hcl(self):
        self.assertEqual(provision._hcl('a${b}%{c}"'), '"a$${b}%%{c}\\""')

    def test_the_backend_file_is_private_and_written_once(self):
        keys = {**STATE_KEYS, "secret_key": "s${x}"}
        path = provision.write_backend(
            self.root, self.config, "b", "SO/1.tfstate", keys
        )
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        text = path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertIn('secret_key = "s$${x}"\n', text)
        self.assertIn('endpoints = {\n  s3 = "https://s3.example.org"\n}\n', text)
        self.assertNotIn("custom_ca_bundle", text)
        with self.assertRaises(FileExistsError):
            provision.write_backend(self.root, self.config, "b", "k", keys)

    def test_a_ca_file_reaches_the_backend(self):
        config = {**self.config, "cafile": "/etc/ssl/ca.pem"}
        path = provision.write_backend(self.root, config, "b", "k", STATE_KEYS)
        text = path.read_text()  # nocheck: cache-read tempdir
        self.assertIn('custom_ca_bundle = "/etc/ssl/ca.pem"\n', text)


class TestEncryption(unittest.TestCase):
    def test_state_and_plan_are_enforced_with_the_workspace_transit_key(self):
        document = json.loads(provision.encryption(WORKSPACE))
        key = document["key_provider"]["openbao"]["workspace"]
        self.assertEqual(key["key_name"], f"{WORKSPACE}-provision")
        self.assertEqual(key["transit_engine_path"], "/transit")
        for target in ("state", "plan"):
            self.assertEqual(
                document[target],
                {"method": "${method.aes_gcm.workspace}", "enforced": True},
            )


class TestCredentials(TempCase):
    def test_every_credential_name_is_cleared(self):
        names = provision.credential_names(CREDENTIALS)
        self.assertLessEqual(
            {
                "AWS_ACCESS_KEY_ID",
                "CLOUDFLARE_API_TOKEN",
                "DNS_UPDATE_KEYSECRET",
                "HCLOUD_TOKEN",
                "IONOS_TOKEN",
                "OS_APPLICATION_CREDENTIAL_SECRET",
                "OS_AUTH_TYPE",
                "PROXMOX_VE_API_TOKEN",
                "INCUS_ADDR",
                "INCUS_CONF",
            },
            names,
        )


class TestProviderTokenIsolation(unittest.TestCase):
    def test_each_customer_token_lies_below_the_provision_role_only(self):
        own = f"tenant/data/{WORKSPACE}-provision/providers/"
        runner = f"tenant/data/{WORKSPACE}/"
        kind = provision.provider_env.WORKSPACE_SECRETS
        holders = {
            name: spec[kind]
            for name, spec in CREDENTIALS["providers"].items()
            if kind in spec
        }
        self.assertEqual(set(holders), set(CUSTOMER_FIELDS))
        for name, secrets in holders.items():
            with self.subTest(provider=name):
                (secret,) = secrets
                path = secret["path"].format(workspace=WORKSPACE)
                self.assertEqual(path, own + name)
                self.assertFalse(path.startswith(runner))
                self.assertEqual(set(secret["env"].values()), CUSTOMER_FIELDS[name])
                platform = {
                    env
                    for s in CREDENTIALS["providers"][name]["secrets"]
                    for env in s["env"]
                }
                catalog = set(secret.get(provision.provider_env.CATALOG, {}))
                self.assertEqual(set(secret["env"]) | catalog, platform)


class ScsCase(TempCase):
    def setUp(self):
        super().setUp()
        self.records = {CUSTOMER_SCS: dict(CUSTOMER), PLATFORM_SCS: dict(PLATFORM)}
        self.platform = FakePlatform(self.records, {})
        self.addCleanup(self.platform.stop)
        self.bao = provision.remote.OpenBao(self.platform.origin, "")
        self.bao.login(f"{WORKSPACE}-provision", JWT)
        patcher = mock.patch.object(provision.provider_env.remote, "keystone_contract")
        self.contract = patcher.start()
        self.addCleanup(patcher.stop)

    def environment(self, source, region):
        return self.environment_of(SCS, source, region)

    def environment_of(self, spec, source, region):
        self.platform.reads.clear()
        context = {"workspace": WORKSPACE, "zone": "z", "host": "", "provider": "scs"}
        return provision.provider_env.provider_environment(
            self.bao, spec, context, self.root, source, region
        )


class TestScsCustomerCredential(ScsCase):
    def test_scs_workspace_credential_uses_the_catalog_endpoint(self):
        started = dt.datetime.now(dt.UTC)
        self.assertEqual(
            self.environment("workspace", CATALOG_REGION),
            {
                "OS_AUTH_URL": CATALOG_REGION["auth_url"],
                "OS_REGION_NAME": CATALOG_REGION["region"],
                "OS_APPLICATION_CREDENTIAL_ID": CUSTOMER["application_credential_id"],
                "OS_APPLICATION_CREDENTIAL_SECRET": CUSTOMER[
                    "application_credential_secret"
                ],
                "OS_AUTH_TYPE": "v3applicationcredential",
            },
        )
        self.assertEqual(self.platform.reads, [CUSTOMER_SCS, CUSTOMER_SCS])
        self.contract.assert_called_once_with(
            CATALOG_REGION["auth_url"],
            CUSTOMER["application_credential_id"],
            CUSTOMER["application_credential_secret"],
            mock.ANY,
        )
        deadline = self.contract.call_args.args[3]
        longest = provision.provider_env.RUN_BUDGET + provision.provider_env.TOFU_GRACE
        self.assertGreaterEqual(deadline, started + longest)

    def test_a_catalog_region_without_the_endpoint_refuses(self):
        for key in ("auth_url", "region"):
            region = {name: v for name, v in CATALOG_REGION.items() if name != key}
            for planted in (region, {**region, key: ""}):
                with (
                    self.subTest(key=key, planted=planted),
                    self.assertRaisesRegex(RefusedError, f"region names no {key}$"),
                ):
                    self.environment("workspace", planted)
        self.contract.assert_not_called()

    def test_scs_workspace_credential_refuses_a_foreign_endpoint(self):
        for field, value in FOREIGN_ENDPOINT.items():
            self.records[CUSTOMER_SCS] = {**CUSTOMER, field: value}
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(
                    RefusedError, f"{CUSTOMER_SCS} carries {field}, which only"
                ),
            ):
                self.environment("workspace", CATALOG_REGION)
        self.contract.assert_not_called()

    def test_negative_control_a_record_read_endpoint_reaches_opentofu(self):
        self.records[CUSTOMER_SCS] = {**CUSTOMER, **FOREIGN_ENDPOINT}
        (customer,) = SCS[provision.provider_env.WORKSPACE_SECRETS]
        (platform,) = SCS["secrets"]
        read_from_record = {
            key: value
            for key, value in customer.items()
            if key != provision.provider_env.CATALOG
        } | {"env": platform["env"]}
        spec = SCS | {provision.provider_env.WORKSPACE_SECRETS: [read_from_record]}
        environment = self.environment_of(spec, "workspace", CATALOG_REGION)
        self.assertEqual(environment["OS_AUTH_URL"], FOREIGN_ENDPOINT["auth_url"])
        self.assertEqual(environment["OS_REGION_NAME"], FOREIGN_ENDPOINT["region_name"])
        with self.assertRaisesRegex(RefusedError, "carries auth_url, region_name"):
            self.environment("workspace", CATALOG_REGION)

    def test_a_missing_or_empty_customer_field_refuses(self):
        for field in CUSTOMER:
            kept = {name: v for name, v in CUSTOMER.items() if name != field}
            for planted in (kept, {**kept, field: ""}):
                self.records[CUSTOMER_SCS] = planted
                with (
                    self.subTest(field=field, planted=planted),
                    self.assertRaisesRegex(RefusedError, f"holds no {field}$"),
                ):
                    self.environment("workspace", CATALOG_REGION)
        self.contract.assert_not_called()

    def test_scs_sources_never_fall_back(self):
        platform = self.environment("platform", CATALOG_REGION)
        self.assertNotIn(CUSTOMER_SCS, self.platform.reads)
        self.assertEqual(platform["OS_AUTH_URL"], PLATFORM["auth_url"])
        self.assertEqual(
            platform["OS_APPLICATION_CREDENTIAL_ID"],
            PLATFORM["application_credential_id"],
        )
        self.assertFalse(set(CUSTOMER.values()) & set(platform.values()))
        self.contract.assert_not_called()
        workspace = self.environment("workspace", CATALOG_REGION)
        self.assertNotIn(PLATFORM_SCS, self.platform.reads)
        self.assertFalse(set(PLATFORM.values()) & set(workspace.values()))
        del self.records[CUSTOMER_SCS]
        with self.assertRaisesRegex(RefusedError, f"{CUSTOMER_SCS} holds no"):
            self.environment("workspace", CATALOG_REGION)
        self.assertNotIn(PLATFORM_SCS, self.platform.reads)


class TestRunBudget(unittest.TestCase):
    def setUp(self):
        self.addCleanup(signal.signal, signal.SIGALRM, signal.getsignal(signal.SIGALRM))

    def run_main(self, budget, held):
        """Args:
            budget: the ``RUN_BUDGET`` of the run.
            held: the seconds the dispatched template takes.

        Returns:
            ``(exit code, stderr)`` of :func:`provision.main`.
        """
        stderr = io.StringIO()
        with (
            mock.patch.object(provision.provider_env, "RUN_BUDGET", budget),
            mock.patch.object(provision, "dispatch", lambda *_: time.sleep(held)),
            contextlib.redirect_stderr(stderr),
        ):
            code = provision.main(["provision.py", "provision"], {}, Path("/none"))
        return code, stderr.getvalue()

    def test_a_run_past_its_budget_fails_naming_the_budget(self):
        code, stderr = self.run_main(dt.timedelta(seconds=1), 10)
        self.assertEqual(code, 1)
        self.assertIn(
            "provision.sh: failed: the run exceeded its time budget of 0:00:01", stderr
        )

    def test_negative_control_a_run_within_its_budget_ends_and_clears_the_alarm(self):
        self.assertEqual(self.run_main(dt.timedelta(seconds=30), 0), (0, ""))
        self.assertEqual(signal.alarm(0), 0)

    def test_the_alarm_is_the_budget_the_credential_must_outlive(self):
        with (
            mock.patch.object(provision.signal, "alarm") as alarm,
            mock.patch.object(provision, "dispatch"),
        ):
            self.assertEqual(provision.main(["p", "provision"], {}, Path("/none")), 0)
        budget = int(provision.provider_env.RUN_BUDGET.total_seconds())
        self.assertEqual(alarm.call_args_list, [mock.call(budget), mock.call(0)])

    def test_the_previous_alarm_handler_is_restored(self):
        def previous(_signum, _frame):
            return None

        signal.signal(signal.SIGALRM, previous)
        self.run_main(dt.timedelta(seconds=30), 0)
        self.assertIs(signal.getsignal(signal.SIGALRM), previous)


class TestTofuBudget(TempCase):
    def setUp(self):
        super().setUp()
        for signum in (signal.SIGALRM, signal.SIGTERM):
            self.addCleanup(signal.signal, signum, signal.getsignal(signum))
        self.addCleanup(signal.alarm, 0)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "tofu"
        fake.write_text(SLOW_TOFU.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        self.task = self.root / "task"
        self.task.mkdir()
        self.ready = self.root / "ready"
        self.sigint = self.task / "sigint"
        self.helpers = []
        self.plugin = "none"
        self.capture = False

    def when(self, marker, action):
        """Args:
        marker: the file a helper thread waits for, at most
            :data:`READY_BOUND` seconds.
        action: what the thread does once it appeared, e.g. a
            :meth:`send`.
        """
        done = threading.Event()

        def run():
            deadline = time.monotonic() + READY_BOUND
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(READY_POLL)
            if marker.exists():
                done.set()
                action()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.helpers.append((marker, thread, done))

    @staticmethod
    def send(signum):
        """Args:
            signum: the signal to send.

        Returns:
            An action that sends ``signum`` to this process.
        """
        return lambda: os.kill(os.getpid(), signum)

    def environment(self, sigint):
        """Args:
            sigint: what the fake tofu does on SIGINT: ``trap`` releases its
                lock and exits, ``linger`` notes it and runs on, ``ignore``
                ignores it.

        Returns:
            The environment of the fake tofu; ``self.plugin`` is ``spawn``
            for one with a plugin child that ignores SIGINT, ``none`` without.
        """
        return {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FAKE_TOFU_SIGINT": sigint,
            "FAKE_TOFU_READY": str(self.ready),
            "FAKE_TOFU_PLUGIN": self.plugin,
        }

    def run_apply(self, sigint, grace):
        """Args:
            sigint: the SIGINT behaviour of :meth:`environment`.
            grace: the ``TOFU_GRACE`` of the run.

        Returns:
            ``(exit code, stderr)`` of :func:`provision.main` running ``tofu
            apply``, with its output captured if ``self.capture``, the code of
            its ``SystemExit`` after a ``SIGTERM``; every :meth:`when` helper
            has acted by then.
        """
        env = self.environment(sigint)
        stderr = io.StringIO()
        signal.signal(signal.SIGTERM, provision._terminate)
        with (
            mock.patch.object(provision.provider_env, "RUN_BUDGET", TEST_BUDGET),
            mock.patch.object(provision.provider_env, "TOFU_GRACE", grace),
            mock.patch.object(
                provision,
                "dispatch",
                lambda *_: provision.tofu(
                    self.task, env, "apply", capture=self.capture
                ),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                code = provision.main(["provision.py", "provision"], {}, Path("/none"))
            except SystemExit as stop:
                code = stop.code
        for marker, thread, done in self.helpers:
            thread.join()
            self.assertTrue(done.is_set(), f"the fake tofu never wrote {marker.name}")
        return code, stderr.getvalue()

    def tofu_report(self):
        """Returns:
        ``pid``, process ``group``, ``parent`` and ``plugin`` pid (0 for
        none) the fake tofu reported once ready.
        """
        text = self.ready.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return dict(zip(TOFU_REPORT, map(int, text.split()), strict=True))

    def assert_ended(self, pid, what):
        """Args:
        pid: a process the run must have ended; it gets
            :data:`READY_BOUND` seconds, and SIGKILL if it still runs with
            the start time it had here, so a reused pid is never killed.
        what: the process the failure names.
        """
        stat = self.stat(pid)
        if stat is None:
            return
        start = stat[1]
        deadline = time.monotonic() + READY_BOUND
        while self.running(pid, start) and time.monotonic() < deadline:
            time.sleep(READY_POLL)
        if self.running(pid, start):
            os.kill(pid, signal.SIGKILL)
            self.fail(f"{what} outlived the run")

    def assert_tofu_ended(self):
        self.assert_ended(self.tofu_report()["pid"], "the fake tofu")

    def test_a_budget_end_interrupts_tofu_which_releases_its_lock(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 1)
        self.assertTrue((self.task / "sigint").is_file())
        self.assertFalse((self.task / "state.tflock").exists())
        self.assertIn(f"the run exceeded its time budget of {TEST_BUDGET}", stderr)
        self.assertIn("tofu apply stopped on SIGINT with exit code 130", stderr)
        self.assert_tofu_ended()

    def test_tofu_runs_in_the_process_group_its_supervisor_leads(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        report = self.tofu_report()
        self.assertEqual(report["group"], report["parent"])
        self.assertNotEqual(report["group"], os.getpgrp())
        self.assertNotEqual(report["parent"], os.getpid())

    def test_the_kill_after_the_grace_takes_the_plugins_of_tofu(self):
        self.plugin = "spawn"
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("ignore", dt.timedelta(milliseconds=200))
        self.assert_ended(self.tofu_report()["plugin"], "the plugin of tofu")
        self.assertEqual(code, 1)
        self.assertIn("ignored SIGINT", stderr)

    def test_the_death_of_the_runner_takes_tofu_and_its_plugins(self):
        self.plugin = "spawn"
        runner = subprocess.Popen(
            [
                sys.executable,
                "-c",
                RUNNER,
                str(Path(provision.__file__).parent),
                str(self.task),
            ],
            env=self.environment("trap"),
        )
        self.addCleanup(runner.wait)
        deadline = time.monotonic() + READY_BOUND
        while not self.ready.exists() and time.monotonic() < deadline:
            time.sleep(READY_POLL)
        runner.kill()
        self.assertTrue(self.ready.exists(), "the fake tofu never got ready")
        report = self.tofu_report()
        self.assert_ended(report["plugin"], "the plugin of tofu")
        self.assert_ended(report["pid"], "the fake tofu")

    def test_a_plugin_outliving_tofu_ends_with_the_run(self):
        self.plugin = "spawn"
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 1)
        self.assertIn("tofu apply stopped on SIGINT with exit code 130", stderr)
        self.assert_ended(self.tofu_report()["plugin"], "the plugin of tofu")

    def kill_supervisor(self):
        os.kill(self.tofu_report()["parent"], signal.SIGKILL)

    def test_a_killed_supervisor_gives_tofu_the_grace_then_takes_its_group(self):
        self.plugin = "spawn"
        self.when(self.ready, self.kill_supervisor)
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=1))
        self.assertEqual(code, 1)
        self.assertIn(f"tofu apply died with {-signal.SIGKILL}", stderr)
        self.assertIn("may miss resources and keep its lock", stderr)
        self.assertTrue(self.sigint.is_file())
        self.assertFalse((self.task / "state.tflock").exists())
        report = self.tofu_report()
        self.assert_ended(report["plugin"], "the plugin of tofu")
        self.assert_ended(report["pid"], "the fake tofu")

    def test_a_budget_end_after_the_supervisor_died_keeps_the_grace(self):
        self.capture = True

        def kill_supervisor_then_end_the_budget():
            self.kill_supervisor()
            os.kill(os.getpid(), signal.SIGALRM)

        self.when(self.ready, kill_supervisor_then_end_the_budget)
        code, stderr = self.run_apply("linger", dt.timedelta(seconds=1))
        self.assertEqual(code, 1)
        self.assertIn(f"the run exceeded its time budget of {TEST_BUDGET}", stderr)
        self.assertNotIn("stopped on SIGINT", stderr)
        self.assertIn("may miss resources and keep its lock", stderr)
        self.assertTrue(self.sigint.is_file())
        self.assert_tofu_ended()

    def test_the_group_kill_finds_the_supervisor_unreaped(self):
        killpg = os.killpg
        states = []

        def recorded(group, signum):
            if signum == signal.SIGKILL:
                states.append(self.stat(group))
            killpg(group, signum)

        self.when(self.ready, self.send(signal.SIGALRM))
        with mock.patch.object(provision.os, "killpg", recorded):
            self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual([state and state[0] for state in states], ["Z"])
        self.assert_tofu_ended()

    @staticmethod
    def stat(pid):
        """Args:
            pid: a process id.

        Returns:
            ``(state, start time)``, fields 3 and 22 of ``/proc/<pid>/stat``,
            or ``None`` once no process has that id, also when it ends
            between the open and the read of that file.
        """
        try:
            text = Path(f"/proc/{pid}/stat").read_text(
                encoding="utf-8"
            )  # nocheck: cache-read procfs
        except (FileNotFoundError, ProcessLookupError):
            return None
        fields = text.rsplit(")", 1)[1].split()
        return fields[0], fields[19]

    def running(self, pid, start):
        """Args:
            pid: a process id.
            start: the start time of the process meant, from :meth:`stat`.

        Returns:
            Whether that process runs; a zombie no parent reaped yet counts as
            ended, and so does another process that reused ``pid``.
        """
        stat = self.stat(pid)
        return stat is not None and stat[0] != "Z" and stat[1] == start

    def test_negative_control_tofu_ignoring_sigint_is_killed_after_the_grace(self):
        grace = dt.timedelta(milliseconds=200)
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("ignore", grace)
        self.assertEqual(code, 1)
        self.assertFalse((self.task / "sigint").exists())
        self.assertTrue((self.task / "state.tflock").is_file())
        self.assertIn(f"the run exceeded its time budget of {TEST_BUDGET}", stderr)
        self.assertIn(f"tofu apply ignored SIGINT for {grace} and was killed", stderr)
        self.assert_tofu_ended()

    def test_a_sigterm_interrupts_tofu_which_releases_its_lock(self):
        self.when(self.ready, self.send(signal.SIGTERM))
        code, _ = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertTrue((self.task / "sigint").is_file())
        self.assertFalse((self.task / "state.tflock").exists())
        self.assert_tofu_ended()

    def test_negative_control_a_sigterm_kills_tofu_ignoring_sigint_after_the_grace(
        self,
    ):
        grace = dt.timedelta(milliseconds=200)
        self.when(self.ready, self.send(signal.SIGTERM))
        code, _ = self.run_apply("ignore", grace)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertFalse(self.sigint.exists())
        self.assertTrue((self.task / "state.tflock").is_file())
        self.assert_tofu_ended()

    def test_a_second_signal_in_the_grace_kills_tofu_at_once(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        self.when(self.sigint, self.send(signal.SIGTERM))
        started = time.monotonic()
        code, _ = self.run_apply("linger", dt.timedelta(seconds=READY_BOUND))
        self.assertLess(time.monotonic() - started, READY_BOUND)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertTrue((self.task / "state.tflock").is_file())
        self.assert_tofu_ended()

    def test_a_stop_holds_the_budget_off_during_the_grace(self):
        armed = []
        self.when(self.ready, self.send(signal.SIGTERM))
        self.when(
            self.sigint,
            lambda: armed.append(signal.getitimer(signal.ITIMER_REAL)[0]),
        )
        code, _ = self.run_apply("linger", dt.timedelta(seconds=1))
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(armed, [0.0])
        self.assert_tofu_ended()

    def test_a_budget_end_during_the_cleanup_fires_once_it_removed_the_task(self):
        def over(*_):
            raise provision.BudgetError("over budget")

        signal.signal(signal.SIGALRM, over)
        remove = shutil.rmtree

        def slow(path, **options):
            time.sleep(CLEANUP_PAUSE)
            remove(path, **options)

        with (
            mock.patch.object(provision.shutil, "rmtree", slow),
            self.assertRaisesRegex(provision.BudgetError, "over budget"),
            provision.task_directory() as task,
        ):
            signal.setitimer(signal.ITIMER_REAL, CLEANUP_PAUSE / 2)
        self.assertFalse(task.exists())

    def test_the_task_directory_defers_the_budget_during_its_cleanup(self):
        signal.signal(signal.SIGALRM, lambda *_: None)
        remove = shutil.rmtree
        armed = []

        def watched(path, **options):
            armed.append(signal.getitimer(signal.ITIMER_REAL)[0])
            remove(path, **options)

        with (
            mock.patch.object(provision.shutil, "rmtree", watched),
            provision.task_directory() as task,
        ):
            signal.alarm(100)
        self.assertEqual(armed, [0.0])
        self.assertFalse(task.exists())
        self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 90)


class TestLock(TempCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(provision.tempfile, "tempdir", str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unlock_refuses_while_a_task_of_its_workspace_runs(self):
        with provision.workspace_lock(WORKSPACE, False):
            with provision.workspace_lock(WORKSPACE, False):
                pass
            with (
                self.assertRaisesRegex(RefusedError, "is running"),
                provision.workspace_lock(WORKSPACE, True),
            ):
                pass
            with provision.workspace_lock("ws-other", True):
                pass
        with provision.workspace_lock(WORKSPACE, True):
            pass

    def test_the_task_directory_is_removed_after_a_failure(self):
        with self.assertRaises(RuntimeError), provision.task_directory() as task:
            (task / "backend.tfbackend").write_text("x")
            raise RuntimeError("tofu failed")
        self.assertFalse(task.exists())


class TestMain(unittest.TestCase):
    def run_main(self, argv, env):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = provision.main(argv, env, Path("/nonexistent"))
        return code, stderr.getvalue()

    def test_a_bad_call_or_configuration_is_refused(self):
        valid = {
            "PROVISION_DNS_FLAVOR": "knot",
            "BAO_ADDR": "https://bao.example.org",
            "PROVISION_STATE_ENDPOINT": "https://s3.example.org",
        }
        cases = {
            "names no template": (["provision.py"], valid),
            "unexpected argument 'x'": (["provision.py", "destroy", "x"], valid),
            "PROVISION_CATALOG_DIR is missing": (["provision.py", "destroy"], valid),
            "is no DNS flavor": (
                ["provision.py", "dns"],
                {**valid, "PROVISION_DNS_FLAVOR": "bind"},
            ),
        }
        for message, (argv, env) in cases.items():
            with self.subTest(message=message):
                code, stderr = self.run_main(argv, env)
                self.assertEqual(code, 2)
                self.assertIn("refused: ", stderr)
                self.assertIn(message, stderr)


if __name__ == "__main__":
    unittest.main()
