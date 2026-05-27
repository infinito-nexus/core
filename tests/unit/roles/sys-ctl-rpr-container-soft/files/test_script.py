import types
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from . import PROJECT_ROOT


def load_script_module():
    """
    Import the script under test from roles/sys-ctl-rpr-container-soft/files/script.py
    """
    script_path = (
        PROJECT_ROOT / "roles" / "sys-ctl-rpr-container-soft" / "files" / "script.py"
    )
    if not script_path.exists():
        raise FileNotFoundError(f"script.py not found at {script_path}")
    spec = spec_from_file_location("rpr_soft_script", str(script_path))
    mod = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


class TestRepairDockerSoft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script_module()

    def test_normalize_services_arg(self):
        s = self.script
        self.assertEqual(
            s.normalize_services_arg(["svc-a.service", " ", "svc-b.service"], None),
            ["svc-a.service", "svc-b.service"],
        )
        self.assertEqual(
            s.normalize_services_arg(None, "svc-a.service   svc-b.service"),
            ["svc-a.service", "svc-b.service"],
        )
        self.assertEqual(
            s.normalize_services_arg(
                None, "svc-a.service, svc-b.service, svc-c.service"
            ),
            ["svc-a.service", "svc-b.service", "svc-c.service"],
        )
        self.assertEqual(s.normalize_services_arg([], ""), [])

    def test_wait_while_manipulation_running_respects_timeout(self):
        s = self.script
        calls = {"checks": 0, "sleeps": 0}
        t = {"now": 0}

        def fake_run(cmd, shell, check):
            self.assertIn("systemctl is-active --quiet", cmd)
            self.assertFalse(check)
            calls["checks"] += 1
            return types.SimpleNamespace(returncode=0)

        def fake_sleep(_secs):
            calls["sleeps"] += 1

        def fake_time():
            # each call advances time by 610s
            t["now"] += 610
            return t["now"]

        old_run = s.subprocess.run
        old_sleep = s.time.sleep
        old_time = s.time.time
        try:
            s.subprocess.run = fake_run
            s.time.sleep = fake_sleep
            s.time.time = fake_time

            s.wait_while_manipulation_running(
                ["svc-a", "svc-b"], waiting_time=600, timeout=1200
            )

            self.assertGreaterEqual(calls["sleeps"], 1)
            self.assertGreaterEqual(calls["checks"], 1)
        finally:
            s.subprocess.run = old_run
            s.time.sleep = old_sleep
            s.time.time = old_time

    def test_main_restarts_and_counts_errors_and_wrapper_usage(self):
        s = self.script
        cmd_log = []

        def fake_print_bash(cmd):
            cmd_log.append(cmd)

            # 1) container ps mocks (STRICT: prefilter compose-labeled containers)
            if cmd.startswith(
                "container ps --filter label=com.docker.compose.project --filter health=unhealthy"
            ):
                return ["app1-web-1", "db-1"]
            if cmd.startswith(
                "container ps --filter label=com.docker.compose.project --filter status=exited"
            ):
                # non-compose containers are filtered out by the new container ps command
                return ["app1-worker-1"]

            # 2) container inspect labels (only called for compose containers now)
            if cmd.startswith(
                "container inspect -f '{{ index .Config.Labels \"com.docker.compose.project\" }}'"
            ):
                container = cmd.split()[-1]
                if container in ("app1-web-1", "app1-worker-1"):
                    return ["app1"]
                if container == "db-1":
                    return ["db"]
                return [""]

            if cmd.startswith(
                "container inspect -f '{{ index .Config.Labels \"com.docker.compose.project.working_dir\" }}'"
            ):
                container = cmd.split()[-1]
                if container in ("app1-web-1", "app1-worker-1"):
                    return ["/BASE/app1"]
                if container == "db-1":
                    return ["/BASE/db"]
                return [""]

            # 3) wrapper invocations
            if "compose" in cmd:
                return []

            return []

        def fake_isfile(path):
            return path in (
                "/BASE/app1/compose.yml",
                "/BASE/db/compose.yml",
            )

        old_print_bash = s.print_bash
        old_isfile2 = s.os.path.isfile
        try:
            s.print_bash = fake_print_bash
            s.os.path.isfile = fake_isfile

            errors = s.main("/BASE", manipulation_services=[], timeout=None)

            # With label prefilter, non-compose containers are ignored -> 0 errors
            self.assertEqual(errors, 0)

            restart_cmds = [c for c in cmd_log if "compose" in c and " restart" in c]
            self.assertTrue(
                any(
                    'compose --chdir "/BASE/app1" --project "app1" restart' in c
                    for c in restart_cmds
                )
            )
            self.assertTrue(
                any(
                    'compose --chdir "/BASE/db" --project "db" restart' in c
                    for c in restart_cmds
                )
            )

            # Wrapper calls must include --project
            self.assertTrue(
                all("--project" in c for c in restart_cmds),
                "Wrapper calls must include --project",
            )
        finally:
            s.print_bash = old_print_bash
            s.os.path.isfile = old_isfile2


if __name__ == "__main__":
    unittest.main()
