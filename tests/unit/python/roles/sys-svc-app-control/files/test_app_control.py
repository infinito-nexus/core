import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "sys-svc-app-control"
    / "files"
    / "python"
    / "app_control.py"
)
STATE_FILE = ".app-control-state"
REGISTRY_FILE = ".app-control.json"
HEALTH_SERVICE = "sys-ctl-hlth-webserver.infinito.nexus.service"
HEALTH_DELAY_SECONDS = 60
HEALTH_CANCEL = ["systemctl", "stop", "app-control-health-refresh.timer"]
HEALTH_START = [
    "systemd-run",
    "--unit=app-control-health-refresh",
    f"--on-active={HEALTH_DELAY_SECONDS}",
    "--timer-property=AccuracySec=1s",
    "--timer-property=RemainAfterElapse=no",
    "--collect",
    "systemctl",
    "start",
    "--no-block",
    HEALTH_SERVICE,
]


def load_module():
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = spec_from_file_location("app_control", str(SCRIPT))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def registry(application_id, project, **overrides):
    base = {
        "application_id": application_id,
        "project": project,
        "control": True,
        "status": "started",
        "mode": "compose",
        "stack_files": [f"/opt/compose/{project}/compose.yml"],
        "timer": f"{application_id}.1.0.0.infinito.nexus.timer",
    }
    base.update(overrides)
    return base


class FakeRun:
    def __init__(self, timers=(), services=(), failing=()):
        self.timers = set(timers)
        self.services = list(services)
        self.failing = set(failing)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[:2] == ["systemctl", "list-unit-files"]:
            listed = f"{argv[-1]} enabled enabled\n" if argv[-1] in self.timers else ""
            return subprocess.CompletedProcess(argv, 0, stdout=listed, stderr="")
        if argv[:3] == ["docker", "stack", "services"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout="\n".join(self.services) + "\n", stderr=""
            )
        if any(project in argv for project in self.failing):
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def actions(self):
        return [argv for argv, _ in self.calls if argv[1] != "list-unit-files"]


class Host:
    def __init__(self, *registries):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.compositions = root / "compose"
        self.paused_apps = root / "www" / "paused" / "apps"
        self.compositions.mkdir()
        self.paused_apps.mkdir(parents=True)
        self.config_path = root / "app-control.json"
        self.config = {
            "compositions": str(self.compositions),
            "registry_file": REGISTRY_FILE,
            "state_file": STATE_FILE,
            "paused_apps": str(self.paused_apps),
            "compose": "/usr/bin/compose",
            "binary": "/usr/bin/app-control",
            "health_service": HEALTH_SERVICE,
            "health_delay_seconds": HEALTH_DELAY_SECONDS,
        }
        self.config_path.write_text(json.dumps(self.config))
        self.registries = {}
        for registry in registries:
            instance = self.compositions / registry["project"]
            instance.mkdir()
            entry = {**registry, "instance": str(instance)}
            (instance / REGISTRY_FILE).write_text(json.dumps(entry))
            self.registries[entry["application_id"]] = entry

    def set_state(self, project, state):
        (self.compositions / project / STATE_FILE).write_text(f"{state}\n")

    def state(self, project):
        marker = self.compositions / project / STATE_FILE
        if not marker.exists():
            return None
        return marker.read_text(encoding="utf-8").strip()  # nocheck: cache-read tempdir

    def projected(self, project):
        return (self.paused_apps / project).exists()

    def close(self):
        self.tmp.cleanup()


class DesiredStateTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_without_a_marker_the_declared_status_decides(self):
        self.assertEqual(self.mod.desired_state(None, "stopped"), "stopped")
        self.assertEqual(self.mod.desired_state(None, "started"), "started")

    def test_a_marker_outranks_the_declared_status(self):
        self.assertEqual(self.mod.desired_state("started", "stopped"), "started")
        self.assertEqual(self.mod.desired_state("stopped", "started"), "stopped")

    def test_an_unknown_status_is_refused(self):
        with self.assertRaises(self.mod.RefusedError):
            self.mod.desired_state(None, "paused")


class ReadStateTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.host = Host(registry("web-app-wiki", "wiki"))
        self.entry = self.host.registries["web-app-wiki"]

    def tearDown(self):
        self.host.close()

    def test_a_missing_marker_reads_as_none(self):
        self.assertIsNone(self.mod.read_state(self.host.config, self.entry))

    def test_a_marker_reads_as_its_state(self):
        self.host.set_state("wiki", "stopped")
        self.assertEqual(self.mod.read_state(self.host.config, self.entry), "stopped")

    def test_a_corrupt_marker_is_refused(self):
        self.host.set_state("wiki", "sleeping")
        with self.assertRaises(self.mod.RefusedError):
            self.mod.read_state(self.host.config, self.entry)


class SelectTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.found = {
            "web-app-wiki": registry("web-app-wiki", "wiki"),
            "web-app-keycloak": registry("web-app-keycloak", "keycloak", control=False),
            "web-app-board": registry("web-app-board", "board"),
        }

    def test_all_is_exactly_the_controlled_applications(self):
        chosen = self.mod.select(self.found, "all")
        self.assertEqual(
            [entry["application_id"] for entry in chosen],
            ["web-app-board", "web-app-wiki"],
        )

    def test_an_application_outside_app_control_is_refused(self):
        with self.assertRaises(self.mod.RefusedError):
            self.mod.select(self.found, "web-app-keycloak")

    def test_an_application_not_deployed_here_is_refused(self):
        with self.assertRaises(self.mod.RefusedError):
            self.mod.select(self.found, "web-app-absent")

    def test_a_control_flag_that_is_no_boolean_is_refused(self):
        found = {"web-app-wiki": registry("web-app-wiki", "wiki", control="true")}
        with self.assertRaises(self.mod.RefusedError):
            self.mod.select(found, "all")


class SshRequestTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_stop_and_start_of_one_application_or_all_pass(self):
        self.assertEqual(
            self.mod.ssh_request("app-control stop web-app-wiki"),
            ("stop", "web-app-wiki"),
        )
        self.assertEqual(
            self.mod.ssh_request("app-control start all"), ("start", "all")
        )

    def test_anything_else_is_refused(self):
        for original in (
            "",
            "stop web-app-wiki",
            "app-control reconcile",
            "app-control stop web-app-wiki extra",
            "app-control stop ../etc",
            "app-control stop web-app-wiki;id",
            "app-control stop Web-App",
            "sh -c id",
        ):
            with (
                self.subTest(original=original),
                self.assertRaises(self.mod.RefusedError),
            ):
                self.mod.ssh_request(original)


class PauseTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_compose_marks_projects_and_takes_the_project_down(self):
        host = Host(registry("web-app-wiki", "wiki"))
        run = FakeRun()
        try:
            self.mod.pause(host.config, host.registries["web-app-wiki"], run)
            state, projected = host.state("wiki"), host.projected("wiki")
        finally:
            host.close()
        self.assertEqual(state, "stopped")
        self.assertTrue(projected)
        self.assertEqual(
            run.actions(),
            [
                [
                    "/usr/bin/compose",
                    "--chdir",
                    str(host.compositions / "wiki"),
                    "--project",
                    "wiki",
                    "down",
                ]
            ],
        )

    def test_the_application_timer_stops_when_it_exists(self):
        host = Host(registry("web-app-wiki", "wiki"))
        timer = host.registries["web-app-wiki"]["timer"]
        run = FakeRun(timers=[timer])
        try:
            self.mod.pause(host.config, host.registries["web-app-wiki"], run)
        finally:
            host.close()
        self.assertIn(["systemctl", "stop", timer], run.actions())

    def test_swarm_scales_every_stack_service_to_zero(self):
        host = Host(registry("web-app-wiki", "wiki", mode="swarm"))
        run = FakeRun(services=["wiki_app", "wiki_worker"])
        try:
            self.mod.pause(host.config, host.registries["web-app-wiki"], run)
        finally:
            host.close()
        self.assertEqual(
            run.actions()[-1],
            [
                "docker",
                "service",
                "scale",
                "--detach=false",
                "wiki_app=0",
                "wiki_worker=0",
            ],
        )

    def test_swarm_without_services_scales_nothing(self):
        host = Host(registry("web-app-wiki", "wiki", mode="swarm"))
        run = FakeRun(services=[])
        try:
            self.mod.pause(host.config, host.registries["web-app-wiki"], run)
        finally:
            host.close()
        self.assertFalse([argv for argv in run.actions() if "scale" in argv])

    def test_an_unknown_mode_is_refused_before_anything_changes(self):
        host = Host(registry("web-app-wiki", "wiki", mode="kubernetes"))
        try:
            with self.assertRaises(self.mod.RefusedError):
                self.mod.pause(host.config, host.registries["web-app-wiki"], FakeRun())
            state = host.state("wiki")
        finally:
            host.close()
        self.assertIsNone(state)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_compose_brings_the_project_up_and_lifts_the_paused_page(self):
        host = Host(registry("web-app-wiki", "wiki"))
        host.set_state("wiki", "stopped")
        (host.paused_apps / "wiki").touch()
        run = FakeRun()
        try:
            self.mod.resume(host.config, host.registries["web-app-wiki"], run)
            state, projected = host.state("wiki"), host.projected("wiki")
        finally:
            host.close()
        self.assertEqual(run.actions()[0][-2:], ["up", "-d"])
        self.assertEqual(state, "started")
        self.assertFalse(projected)

    def test_swarm_redeploys_the_rendered_stack_from_its_instance(self):
        host = Host(
            registry(
                "web-app-wiki",
                "wiki",
                mode="swarm",
                stack_files=["/c/wiki/compose.yml", "/c/wiki/compose.override.yml"],
            )
        )
        run = FakeRun()
        try:
            self.mod.resume(host.config, host.registries["web-app-wiki"], run)
        finally:
            host.close()
        argv, kwargs = run.calls[0]
        self.assertEqual(
            argv,
            [
                "docker",
                "stack",
                "deploy",
                "--compose-file",
                "/c/wiki/compose.yml",
                "--compose-file",
                "/c/wiki/compose.override.yml",
                "--resolve-image",
                "never",
                "--prune",
                "--with-registry-auth",
                "wiki",
            ],
        )
        self.assertEqual(kwargs["cwd"], str(host.compositions / "wiki"))

    def test_a_failed_start_keeps_the_application_paused(self):
        host = Host(registry("web-app-wiki", "wiki"))
        host.set_state("wiki", "stopped")
        try:
            with self.assertRaises(subprocess.CalledProcessError):
                self.mod.resume(
                    host.config,
                    host.registries["web-app-wiki"],
                    FakeRun(failing=["wiki"]),
                )
            state = host.state("wiki")
        finally:
            host.close()
        self.assertEqual(state, "stopped")


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_reconcile(self, host, run):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            failed = self.mod.reconcile(host.config, run)
        return failed, stdout.getvalue()

    def test_a_new_application_is_created_in_its_declared_stopped_status(self):
        host = Host(registry("web-app-wiki", "wiki", status="stopped"))
        run = FakeRun()
        try:
            failed, stdout = self.run_reconcile(host, run)
            state, projected = host.state("wiki"), host.projected("wiki")
        finally:
            host.close()
        self.assertEqual(failed, [])
        self.assertEqual(state, "stopped")
        self.assertTrue(projected)
        self.assertIn("[web-app-wiki] CHANGED stopped", stdout)
        self.assertEqual(run.actions()[-1][-1], "down")

    def test_a_new_application_is_created_in_its_declared_started_status(self):
        host = Host(registry("web-app-wiki", "wiki", status="started"))
        run = FakeRun()
        try:
            failed, _ = self.run_reconcile(host, run)
            state = host.state("wiki")
        finally:
            host.close()
        self.assertEqual(failed, [])
        self.assertEqual(state, "started")
        self.assertEqual(run.actions(), [])

    def test_the_state_semaphore_set_survives_a_redeploy(self):
        host = Host(registry("web-app-wiki", "wiki", status="stopped"))
        host.set_state("wiki", "started")
        run = FakeRun()
        try:
            _, stdout = self.run_reconcile(host, run)
            state = host.state("wiki")
        finally:
            host.close()
        self.assertEqual(state, "started")
        self.assertEqual(run.actions(), [])
        self.assertIn("[web-app-wiki] ok started", stdout)

    def test_a_paused_application_is_paused_again_after_the_deploy_ran_it(self):
        host = Host(registry("web-app-wiki", "wiki", status="started"))
        host.set_state("wiki", "stopped")
        run = FakeRun()
        try:
            self.run_reconcile(host, run)
            projected = host.projected("wiki")
        finally:
            host.close()
        self.assertTrue(projected)
        self.assertEqual(run.actions()[-1][-1], "down")

    def test_an_application_outside_app_control_loses_any_pause_state(self):
        host = Host(registry("web-app-keycloak", "keycloak", control=False))
        host.set_state("keycloak", "stopped")
        (host.paused_apps / "keycloak").touch()
        run = FakeRun()
        try:
            failed, _ = self.run_reconcile(host, run)
            state, projected = host.state("keycloak"), host.projected("keycloak")
        finally:
            host.close()
        self.assertEqual(failed, [])
        self.assertIsNone(state)
        self.assertFalse(projected)
        self.assertEqual(run.calls, [])


class MainTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, host, argv, run, environ=None, euid=0, execvp=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.mod.main(
                ["--config", str(host.config_path), *argv],
                run=run,
                environ=environ or {},
                execvp=execvp or (lambda *_: None),
                euid=lambda: euid,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_stop_all_never_touches_the_control_plane(self):
        host = Host(
            registry("web-app-wiki", "wiki"),
            registry("web-app-keycloak", "keycloak", control=False),
        )
        run = FakeRun()
        try:
            code, _, _ = self.run_main(host, ["stop", "all"], run)
            states = {name: host.state(name) for name in ("wiki", "keycloak")}
        finally:
            host.close()
        self.assertEqual(code, 0)
        self.assertEqual(states, {"wiki": "stopped", "keycloak": None})
        self.assertFalse([argv for argv in run.actions() if "keycloak" in argv])

    def test_one_failing_application_fails_the_run_but_not_the_others(self):
        host = Host(
            registry("web-app-board", "board"), registry("web-app-wiki", "wiki")
        )
        run = FakeRun(failing=["board"])
        try:
            code, _, stderr = self.run_main(host, ["stop", "all"], run)
            wiki = host.state("wiki")
        finally:
            host.close()
        self.assertEqual(code, 1)
        self.assertEqual(wiki, "stopped")
        self.assertIn("FAILED applications: web-app-board", stderr)

    def test_stopping_an_application_outside_app_control_is_refused(self):
        host = Host(registry("web-app-keycloak", "keycloak", control=False))
        run = FakeRun()
        try:
            code, _, stderr = self.run_main(host, ["stop", "web-app-keycloak"], run)
        finally:
            host.close()
        self.assertEqual(code, 2)
        self.assertIn("not under app control", stderr)
        self.assertEqual(run.calls, [])

    def test_stop_and_start_need_root(self):
        host = Host(registry("web-app-wiki", "wiki"))
        run = FakeRun()
        try:
            code, _, _ = self.run_main(host, ["stop", "web-app-wiki"], run, euid=1000)
        finally:
            host.close()
        self.assertEqual(code, 2)
        self.assertEqual(run.calls, [])

    def test_a_stop_schedules_the_installed_health_sweep_after_the_pause(self):
        host = Host(registry("web-app-wiki", "wiki"))
        run = FakeRun(timers=[HEALTH_SERVICE])
        try:
            code, _, _ = self.run_main(host, ["stop", "web-app-wiki"], run)
        finally:
            host.close()
        self.assertEqual(code, 0)
        self.assertEqual(run.actions()[-2:], [HEALTH_CANCEL, HEALTH_START])
        self.assertEqual(run.actions().count(HEALTH_START), 1)

    def test_a_later_action_moves_the_pending_sweep_behind_it(self):
        host = Host(registry("web-app-wiki", "wiki"), registry("web-app-blog", "blog"))
        run = FakeRun(timers=[HEALTH_SERVICE])
        try:
            self.run_main(host, ["start", "web-app-wiki"], run)
            code, _, _ = self.run_main(host, ["start", "web-app-blog"], run)
        finally:
            host.close()
        self.assertEqual(code, 0)
        actions = run.actions()
        self.assertEqual(actions.count(HEALTH_START), 2)
        self.assertEqual(actions[-2:], [HEALTH_CANCEL, HEALTH_START])
        cancel_kwargs = [kwargs for argv, kwargs in run.calls if argv == HEALTH_CANCEL]
        self.assertTrue(all(kwargs["check"] is False for kwargs in cancel_kwargs))

    def test_a_host_without_the_health_sweep_skips_it(self):
        host = Host(registry("web-app-wiki", "wiki"))
        run = FakeRun()
        try:
            code, _, _ = self.run_main(host, ["start", "web-app-wiki"], run)
        finally:
            host.close()
        self.assertEqual(code, 0)
        self.assertNotIn(HEALTH_START, run.actions())

    def test_a_failed_sweep_start_is_reported_after_the_pause_took_effect(self):
        host = Host(registry("web-app-wiki", "wiki"))
        run = FakeRun(timers=[HEALTH_SERVICE], failing=[HEALTH_SERVICE])
        try:
            code, _, stderr = self.run_main(host, ["stop", "web-app-wiki"], run)
            state = host.state("wiki")
        finally:
            host.close()
        self.assertEqual(code, 1)
        self.assertEqual(state, "stopped")
        self.assertIn("health sweep not scheduled", stderr)

    def test_reconcile_leaves_the_health_sweep_alone(self):
        host = Host(registry("web-app-wiki", "wiki"))
        run = FakeRun(timers=[HEALTH_SERVICE])
        try:
            code, _, _ = self.run_main(host, ["reconcile"], run)
        finally:
            host.close()
        self.assertEqual(code, 0)
        self.assertNotIn(HEALTH_START, run.actions())

    def test_the_forced_command_reenters_through_sudo_with_a_fixed_argv(self):
        host = Host(registry("web-app-wiki", "wiki"))
        seen = []
        try:
            code, _, _ = self.run_main(
                host,
                ["ssh"],
                FakeRun(),
                environ={"SSH_ORIGINAL_COMMAND": "app-control stop web-app-wiki"},
                euid=1000,
                execvp=lambda file, argv: seen.append((file, argv)),
            )
        finally:
            host.close()
        self.assertEqual(code, 0)
        self.assertEqual(
            seen,
            [
                (
                    "sudo",
                    [
                        "sudo",
                        "-n",
                        "/usr/bin/app-control",
                        "--config",
                        str(host.config_path),
                        "stop",
                        "web-app-wiki",
                    ],
                )
            ],
        )

    def test_an_interactive_session_is_refused(self):
        host = Host(registry("web-app-wiki", "wiki"))
        seen = []
        try:
            code, _, _ = self.run_main(
                host,
                ["ssh"],
                FakeRun(),
                euid=1000,
                execvp=lambda *call: seen.append(call),
            )
        finally:
            host.close()
        self.assertEqual(code, 2)
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
