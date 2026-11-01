from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest import TestCase, main, mock

from . import PROJECT_ROOT


def _load_script():
    path = (
        PROJECT_ROOT
        / "roles"
        / "sys-ctl-hlth-runtime"
        / "files"
        / "python"
        / "script.py"
    )
    spec = importlib.util.spec_from_file_location("hlth_runtime_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = _load_script()
FLOORS = {"8.2": "8.2.35", "8.3": "8.3.36", "8.4": "8.4.27", "8.5": "8.5.12"}
MARKER = SCRIPT.PROBE_MARKER


def _container(name, stack=None, service=None):
    return SCRIPT.Container(id=f"id-{name}", name=name, stack=stack, service=service)


def _probe(version, expose_php=False, upload_progress=False):
    return SCRIPT.PhpProbe(
        version=version,
        settings={
            "expose_php": expose_php,
            "session.upload_progress.enabled": upload_progress,
        },
    )


def _check(containers, probes, hardened=None):
    return SCRIPT.check(
        containers, FLOORS, hardened or {}, lambda container_id: probes[container_id]
    )


class TestFloorViolation(TestCase):
    def test_a_version_at_its_floor_passes(self):
        self.assertIsNone(SCRIPT.floor_violation("8.3.36", FLOORS))

    def test_a_version_below_its_floor_fails(self):
        self.assertIn(
            "below the security floor 8.4.27", SCRIPT.floor_violation("8.4.26", FLOORS)
        )

    def test_php_8_1_is_end_of_life(self):
        self.assertIn("end-of-life line 8.1", SCRIPT.floor_violation("8.1.34", FLOORS))

    def test_php_7_4_is_end_of_life(self):
        self.assertIn("end-of-life line 7.4", SCRIPT.floor_violation("7.4.33", FLOORS))

    def test_a_line_newer_than_every_floor_passes(self):
        self.assertIsNone(SCRIPT.floor_violation("8.6.0", FLOORS))

    def test_a_distro_revision_suffix_is_ignored(self):
        self.assertIsNone(SCRIPT.floor_violation("8.4.27-1+deb13u1", FLOORS))

    def test_an_unparsable_version_fails(self):
        self.assertIn("unparsable", SCRIPT.floor_violation("eight", FLOORS))


class TestParseProbe(TestCase):
    def test_startup_warnings_before_the_probe_line_are_skipped(self):
        stdout = f"PHP Warning:  Module 'redis' already loaded\n{MARKER}|8.3.36||0\n"
        self.assertEqual(SCRIPT.parse_probe(stdout), _probe("8.3.36"))

    def test_enabled_settings_are_reported_on(self):
        self.assertEqual(
            SCRIPT.parse_probe(f"\n{MARKER}|8.4.27|1|1\n"),
            _probe("8.4.27", expose_php=True, upload_progress=True),
        )

    def test_output_without_the_probe_line_raises(self):
        with self.assertRaises(SCRIPT.ProbeError):
            SCRIPT.parse_probe("Segmentation fault\n")

    def test_a_probe_line_with_missing_fields_raises(self):
        with self.assertRaises(SCRIPT.ProbeError):
            SCRIPT.parse_probe(f"{MARKER}|8.4.27\n")


class TestIdentity(TestCase):
    def test_compose_labels_give_project_and_service(self):
        labels = {
            "com.docker.compose.project": "nextcloud",
            "com.docker.compose.service": "cron",
        }
        self.assertEqual(SCRIPT.identity(labels), ("nextcloud", "cron"))

    def test_swarm_labels_strip_the_stack_prefix(self):
        labels = {
            "com.docker.stack.namespace": "nextcloud",
            "com.docker.swarm.service.name": "nextcloud_nextcloud",
        }
        self.assertEqual(SCRIPT.identity(labels), ("nextcloud", "nextcloud"))

    def test_a_container_without_labels_has_no_identity(self):
        self.assertEqual(SCRIPT.identity(None), (None, None))


class TestCheck(TestCase):
    def test_an_eol_runtime_outside_any_stack_fails(self):
        failures, _infos = _check(
            [_container("legacy")], {"id-legacy": _probe("8.1.34")}
        )
        self.assertEqual(failures, ["legacy: PHP 8.1.34 runs the end-of-life line 8.1"])

    def test_a_patched_runtime_passes(self):
        self.assertEqual(
            _check([_container("app")], {"id-app": _probe("8.5.12")}), ([], [])
        )

    def test_a_hardened_service_with_expose_php_on_fails(self):
        failures, _infos = _check(
            [_container("wp", "wordpress", "wordpress")],
            {"id-wp": _probe("8.4.27", expose_php=True)},
            {"wordpress": ["wordpress"]},
        )
        self.assertEqual(
            failures, ["wp: expose_php on, the php_hardening ini is not in effect"]
        )

    def test_a_hardened_service_with_both_settings_off_passes(self):
        self.assertEqual(
            _check(
                [_container("wp", "wordpress", "wordpress")],
                {"id-wp": _probe("8.4.27")},
                {"wordpress": ["wordpress"]},
            ),
            ([], []),
        )

    def test_a_sidecar_of_a_hardened_stack_is_info_only(self):
        failures, infos = _check(
            [_container("nc-cron", "nextcloud", "cron")],
            {"id-nc-cron": _probe("8.4.27", upload_progress=True)},
            {"nextcloud": ["nextcloud"]},
        )
        self.assertEqual(failures, [])
        self.assertEqual(
            infos,
            [
                "nc-cron: session.upload_progress.enabled on (sidecar without php_hardening)"
            ],
        )

    def test_a_container_outside_hardened_stacks_is_not_judged_on_settings(self):
        self.assertEqual(
            _check(
                [_container("app", "other", "app")],
                {"id-app": _probe("8.4.27", expose_php=True)},
                {"wordpress": ["wordpress"]},
            ),
            ([], []),
        )

    def test_a_hardened_service_without_php_fails(self):
        failures, _infos = _check(
            [_container("wp", "wordpress", "wordpress")],
            {"id-wp": None},
            {"wordpress": ["wordpress"]},
        )
        self.assertEqual(
            failures, ["wp: declares php_hardening but has no php to verify it"]
        )

    def test_a_container_without_php_is_skipped(self):
        self.assertEqual(_check([_container("db")], {"id-db": None}), ([], []))

    def test_a_probe_error_is_a_failure(self):
        def broken(_container_id):
            raise SCRIPT.ProbeError("php exited 255: boom")

        failures, _infos = SCRIPT.check([_container("app")], FLOORS, {}, broken)
        self.assertEqual(failures, ["app: php exited 255: boom"])


class TestProbePhp(TestCase):
    def _run(self, returncode, stdout="", stderr=""):
        completed = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        with mock.patch.object(SCRIPT.subprocess, "run", return_value=completed):
            return SCRIPT.probe_php("abc")

    def test_exit_127_means_no_php(self):
        self.assertIsNone(self._run(127, stderr="executable file not found"))

    def test_exit_126_means_no_php(self):
        self.assertIsNone(self._run(126, stderr="OCI runtime exec failed"))

    def test_another_non_zero_exit_raises(self):
        with self.assertRaises(SCRIPT.ProbeError):
            self._run(255, stderr="PHP Fatal error")

    def test_a_timeout_raises(self):
        with (
            mock.patch.object(
                SCRIPT.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="php", timeout=60),
            ),
            self.assertRaises(SCRIPT.ProbeError),
        ):
            SCRIPT.probe_php("abc")


class TestRunningContainers(TestCase):
    def test_every_engine_call_is_bounded_by_a_timeout(self):
        timeouts = []

        def fake_run(args, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            if args[:2] == ["container", "ps"]:
                return SimpleNamespace(returncode=0, stdout="id-app\n", stderr="")
            inspected = [{"Id": "id-app", "Name": "/app", "Config": {"Labels": None}}]
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(inspected), stderr=""
            )

        with mock.patch.object(SCRIPT.subprocess, "run", side_effect=fake_run):
            SCRIPT.running_containers()
        self.assertEqual(timeouts, [SCRIPT.EXEC_TIMEOUT_SECONDS] * 2)


class TestMain(TestCase):
    def _main(self, php_versions):
        """Run main() against a fake engine.

        Args:
            php_versions: ``{container name: PHP version or None}``.
        """
        inspected = [
            {
                "Id": f"id-{name}",
                "Name": f"/{name}",
                "Config": {"Labels": None},
            }
            for name in php_versions
        ]

        def fake_run(args, **_kwargs):
            if args[:2] == ["container", "ps"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout="\n".join(i["Id"] for i in inspected),
                    stderr="",
                )
            if args[:2] == ["container", "inspect"]:
                return SimpleNamespace(
                    returncode=0, stdout=json.dumps(inspected), stderr=""
                )
            if args[:2] == ["container", "exec"]:
                version = php_versions[args[2].removeprefix("id-")]
                if version is None:
                    return SimpleNamespace(
                        returncode=127, stdout="", stderr="not found"
                    )
                return SimpleNamespace(
                    returncode=0, stdout=f"\n{MARKER}|{version}||0\n", stderr=""
                )
            raise AssertionError(f"unexpected command {args}")

        argv = ["--floors", json.dumps({"php": FLOORS}), "--hardened", "{}"]
        with (
            mock.patch.object(SCRIPT.subprocess, "run", side_effect=fake_run),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            code = SCRIPT.main(argv)
        return code, out.getvalue()

    def test_main_fails_on_an_eol_runtime(self):
        code, output = self._main({"akaunting": "8.1.34", "postgres": None})
        self.assertEqual(code, 1)
        self.assertIn("akaunting: PHP 8.1.34 runs the end-of-life line 8.1", output)

    def test_main_passes_when_every_runtime_is_patched(self):
        code, _output = self._main({"wordpress": "8.4.27", "postgres": None})
        self.assertEqual(code, 0)

    def _main_on_engine_error(self, error):
        argv = ["--floors", json.dumps({"php": FLOORS}), "--hardened", "{}"]
        with (
            mock.patch.object(SCRIPT.subprocess, "run", side_effect=error),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            code = SCRIPT.main(argv)
        return code, out.getvalue()

    def test_main_fails_with_one_line_on_a_hung_engine(self):
        code, output = self._main_on_engine_error(
            subprocess.TimeoutExpired(cmd=["container", "ps"], timeout=60)
        )
        self.assertEqual(code, 1)
        self.assertEqual(len(output.splitlines()), 1)
        self.assertIn("timed out after 60 seconds", output)

    def test_main_fails_with_one_line_on_a_failing_engine(self):
        code, output = self._main_on_engine_error(
            subprocess.CalledProcessError(returncode=1, cmd=["container", "ps"])
        )
        self.assertEqual(code, 1)
        self.assertEqual(len(output.splitlines()), 1)
        self.assertIn("returned non-zero exit status 1", output)


if __name__ == "__main__":
    main()
