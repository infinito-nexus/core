from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import shutil
import signal
import stat
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from .provision._fake_provision import (
    CREDENTIALS,
    JWT,
    WORKSPACE,
    FakePlatform,
    TempCase,
    load,
)
from .provision._fake_spawner import FakeSpawner

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
CLEANUP_PAUSE = 0.5


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
        patcher = mock.patch.object(
            provision.provider_env.keystone, "keystone_contract"
        )
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

    def raised(self, error):
        """Args:
            error: what the dispatched template raises.

        Returns:
            ``(exit code, stderr)`` of :func:`provision.main`, ``(None, the
            error)`` when the error escapes it, as no ``failed:`` line and no
            exit code 1 reach Semaphore then.
        """
        stderr = io.StringIO()
        with (
            mock.patch.object(provision, "dispatch", side_effect=error),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                code = provision.main(["provision.py", "provision"], {}, Path("/none"))
            except type(error) as escaped:
                return None, repr(escaped)
        return code, stderr.getvalue()

    def test_a_sandbox_error_fails_the_run_with_its_line(self):
        error = provision.sandbox.SandboxError("a process of the sandbox 1 survived")
        self.assertEqual(self.raised(error), (1, f"provision.sh: failed: {error}\n"))

    def test_negative_control_a_main_blind_to_sandbox_errors_lets_them_escape(self):
        error = provision.sandbox.SandboxError("a process of the sandbox 1 survived")
        blind = tuple(kind for kind in provision.FAILURES if kind is not type(error))
        self.assertLess(len(blind), len(provision.FAILURES))
        with mock.patch.object(provision, "FAILURES", blind):
            self.assertEqual(self.raised(error), (None, repr(error)))

    def test_negative_control_a_refusal_still_refuses(self):
        refusal = RefusedError("names no template")
        self.assertEqual(
            self.raised(refusal), (2, f"provision.sh: refused: {refusal}\n")
        )


class TestTaskDirectoryBudget(TempCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(signal.signal, signal.SIGALRM, signal.getsignal(signal.SIGALRM))
        self.addCleanup(signal.alarm, 0)
        patcher = mock.patch.object(provision.tempfile, "tempdir", str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.spawner = FakeSpawner(
            load("sandbox.spawner"),
            self.root / "sandboxes",
            self.root,
            Path(os.devnull),
            provision.OPENTOFU / "tofurc",
        )
        self.addCleanup(self.spawner.close)

    def purging(self, before):
        """Args:
        before: called in the spawner right before it removes the files of
            a sandbox.
        """
        purge = self.spawner.privileges.purge

        def purged(*arguments):
            before()
            purge(*arguments)

        patcher = mock.patch.object(self.spawner.privileges, "purge", purged)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_budget_end_during_the_cleanup_fires_once_it_removed_the_task(self):
        def over(*_):
            raise provision.opentofu.BudgetError("over budget")

        signal.signal(signal.SIGALRM, over)
        self.purging(lambda: time.sleep(CLEANUP_PAUSE))
        with (
            self.assertRaisesRegex(provision.opentofu.BudgetError, "over budget"),
            provision.task_directory() as task,
        ):
            signal.setitimer(signal.ITIMER_REAL, CLEANUP_PAUSE / 2)
        self.assertFalse(task.exists())

    def test_the_task_directory_defers_the_budget_during_its_cleanup(self):
        signal.signal(signal.SIGALRM, lambda *_: None)
        armed = []
        self.purging(lambda: armed.append(signal.getitimer(signal.ITIMER_REAL)[0]))
        with provision.task_directory() as task:
            signal.alarm(100)
        self.assertEqual(armed, [0.0])
        self.assertFalse(task.exists())
        self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 90)

    def test_the_task_directory_is_removed_after_a_failure(self):
        with self.assertRaises(RuntimeError), provision.task_directory() as task:
            (task / "backend.tfbackend").write_text("x")
            raise RuntimeError("tofu failed")
        self.assertFalse(task.exists())
        self.assertFalse(task.parent.exists())


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
            "the destroy template pins no provider": (
                ["provision.py", "destroy"],
                valid,
            ),
            "pins no provider of": (["provision.py", "provision", "x"], valid),
            "unexpected argument 'x'": (
                ["provision.py", "destroy", "incus", "x"],
                valid,
            ),
            "unexpected argument 'incus'": (
                ["provision.py", "unlock", "incus"],
                valid,
            ),
            "PROVISION_CATALOG_DIR is missing": (
                ["provision.py", "destroy", "incus"],
                valid,
            ),
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


class TestTaskWrites(TempCase):
    def setUp(self):
        super().setUp()
        self.task = self.root / "task"
        self.task.mkdir()
        self.task.chmod(provision.sandbox.TASK_MODE)

    def test_tofu_init_replaces_the_staged_lock_file_in_a_real_task_directory(self):
        staged = self.root / "staged.lock.hcl"
        staged.write_text("old", encoding="utf-8")
        lock = self.task / ".terraform.lock.hcl"
        shutil.copy2(staged, lock)
        part = self.task / ".terraform.lock.hcl.tmp"
        part.write_text("new", encoding="utf-8")
        part.replace(lock)
        self.assertEqual(lock.read_bytes(), b"new")  # nocheck: cache-read tempdir
        self.assertEqual(
            stat.S_IMODE(self.task.stat().st_mode), provision.sandbox.TASK_MODE
        )

    def test_a_write_that_climbs_out_of_the_task_is_refused(self):
        with self.assertRaisesRegex(provision.sandbox.SandboxError, "no path below"):
            outside = os.path.relpath(self.root / "x", self.task)
            provision.sandbox.task_write(self.task, outside, "x")
        self.assertFalse((self.root / "x").exists())


if __name__ == "__main__":
    unittest.main()
