# tests/unit/roles/sys-svc-compose-ca/files/test_compose_ca_inject.py
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.yaml import load_yaml, load_yaml_str

from . import PROJECT_ROOT

_CA_TRUST = load_yaml(str(PROJECT_ROOT / "group_vars" / "all" / "02_tls.yml"))[
    "CA_TRUST"
]
CA_CERT_CONTAINER = _CA_TRUST["inject_cert_container"]
CA_WRAPPER_CONTAINER = _CA_TRUST["inject_wrapper_container"]


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class TestComposeCaInject(unittest.TestCase):
    def setUp(self):
        self.m = _load_module(
            "roles/sys-svc-compose-ca/files/compose_ca.py",
            "compose_ca_inject_mod",
        )

    def test_normalize_cmd(self):
        self.assertEqual(self.m.normalize_cmd(["a", "b"]), ["a", "b"])
        self.assertEqual(self.m.normalize_cmd("echo hi"), ["/bin/sh", "-lc", "echo hi"])
        self.assertEqual(
            self.m.normalize_cmd(["/bin/sh", "-c", "if", "!", "grep", "foo"]),
            ["/bin/sh", "-c", "if ! grep foo"],
        )
        self.assertEqual(
            self.m.normalize_cmd(
                [
                    "/bin/sh",
                    "-c",
                    "if",
                    "!",
                    "grep",
                    "-qF",
                    "INFINITO_TAIGA_AUTH_CONFIG",  # nocheck: test-fixture
                    "/taiga-back/settings/config.py",
                    ";",
                    "then",
                ]
            ),
            [
                "/bin/sh",
                "-c",
                "if ! grep -qF INFINITO_TAIGA_AUTH_CONFIG /taiga-back/settings/config.py ; then",
            ],
        )
        self.assertEqual(self.m.normalize_cmd(None), [])
        with self.assertRaises(SystemExit):
            self.m.normalize_cmd(123)

    def test_shell_payload_single_string_preserved(self):
        self.assertEqual(
            self.m._shell_payload(
                [
                    "if ! grep -qF INFINITO_TAIGA_AUTH_CONFIG /taiga-back/settings/config.py; then cat /taiga-back/settings/config.append.py >> /taiga-back/settings/config.py; fi; exec /taiga-back/docker/entrypoint.sh"
                ]
            ),
            "if ! grep -qF INFINITO_TAIGA_AUTH_CONFIG /taiga-back/settings/config.py; then cat /taiga-back/settings/config.append.py >> /taiga-back/settings/config.py; fi; exec /taiga-back/docker/entrypoint.sh",
        )

    def test_normalize_entrypoint(self):
        self.assertEqual(self.m.normalize_entrypoint(["a", "b"]), ["a", "b"])
        self.assertEqual(
            self.m.normalize_entrypoint("echo hi"), ["/bin/sh", "-lc", "echo hi"]
        )
        self.assertEqual(
            self.m.normalize_entrypoint(["/bin/sh", "-c", "echo", "hi"]),
            ["/bin/sh", "-c", "echo hi"],
        )
        self.assertEqual(self.m.normalize_entrypoint(None), [])
        with self.assertRaises(SystemExit):
            self.m.normalize_entrypoint(123)

    def test_parse_yaml_requires_mapping(self):
        doc = self.m.parse_yaml("a: 1\n", "x")
        self.assertEqual(doc["a"], 1)

        with self.assertRaises(SystemExit):
            self.m.parse_yaml("- 1\n- 2\n", "x")

    def test_has_build(self):
        self.assertTrue(self.m._has_build({"build": {"context": "."}}))
        self.assertTrue(self.m._has_build({"build": "./"}))
        self.assertFalse(self.m._has_build({}))
        self.assertFalse(self.m._has_build({"build": None}))

    def test_find_builder_service_for_image(self):
        services = {
            "app": {"image": "custom:1", "build": {"context": "."}},
            "worker": {"image": "custom:1"},
            "other": {"image": "other:2", "build": {"context": "."}},
        }
        self.assertEqual(
            self.m._find_builder_service_for_image(image="custom:1", services=services),
            "app",
        )
        self.assertEqual(
            self.m._find_builder_service_for_image(
                image="missing:tag", services=services
            ),
            "",
        )
        self.assertEqual(
            self.m._find_builder_service_for_image(image="", services=services),
            "",
        )

    def test_ensure_image_available_builds_self_when_build_present(self):
        """
        If the service has build:, ensure_image_available should run
        `compose ... build <service>` (not pull).
        """
        calls = []

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            calls.append(cmd)

            if cmd[:3] == ["docker", "image", "inspect"]:
                inspect_calls = [
                    c for c in calls if c[:3] == ["docker", "image", "inspect"]
                ]
                if len(inspect_calls) == 1:
                    return 1, "", "no such image"
                return 0, json.dumps([{"Config": {"Entrypoint": [], "Cmd": []}}]), ""

            if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["build", "app"]:
                return 0, "built", ""

            return 1, "", "unexpected"

        base_cmd = ["docker", "compose", "-p", "p", "-f", "compose.yml"]

        with patch.object(self.m, "run", side_effect=fake_run):
            self.m.ensure_image_available(
                service_name="app",
                svc={"image": "custom:1", "build": {"context": "."}},
                image="custom:1",
                services={"app": {"image": "custom:1", "build": {"context": "."}}},
                service_to_compose_cmd={"app": base_cmd},
                compose_base_cmd=base_cmd,
                cwd=Path("/tmp"),
                env={},
            )

        self.assertTrue(any(c[-2:] == ["build", "app"] for c in calls))
        self.assertFalse(any(c[-2:] == ["pull", "app"] for c in calls))

    def test_ensure_image_available_builds_builder_for_shared_image(self):
        """
        New robust logic:
        - 'worker' has no build but references image 'custom:1'
        - 'app' has build and same image 'custom:1'
        => should run `compose ... build app` and not pull worker.
        """
        calls = []

        services = {
            "app": {"image": "custom:1", "build": {"context": "."}},
            "worker": {"image": "custom:1"},
        }

        base_cmd = ["docker", "compose", "-p", "p", "-f", "compose.yml"]
        service_to_cmd = {"app": base_cmd, "worker": base_cmd}

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            calls.append(cmd)

            if cmd[:3] == ["docker", "image", "inspect"]:
                inspect_calls = [
                    c for c in calls if c[:3] == ["docker", "image", "inspect"]
                ]
                if len(inspect_calls) == 1:
                    return 1, "", "no such image"
                return 0, json.dumps([{"Config": {"Entrypoint": [], "Cmd": []}}]), ""

            if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["build", "app"]:
                return 0, "built", ""

            if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["pull", "worker"]:
                return 0, "pulled", ""

            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            self.m.ensure_image_available(
                service_name="worker",
                svc=services["worker"],
                image="custom:1",
                services=services,
                service_to_compose_cmd=service_to_cmd,
                compose_base_cmd=base_cmd,
                cwd=Path("/tmp"),
                env={},
            )

        self.assertTrue(any(c[-2:] == ["build", "app"] for c in calls))
        self.assertFalse(any(c[-2:] == ["pull", "worker"] for c in calls))

    def test_ensure_image_available_falls_back_to_pull_when_no_builder(self):
        """
        If there is no builder service for an image, fall back to pull(service).
        """
        calls = []

        services = {"worker": {"image": "registry.example/worker:1"}}
        base_cmd = ["docker", "compose", "-p", "p", "-f", "compose.yml"]
        service_to_cmd = {"worker": base_cmd}

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            calls.append(cmd)

            if cmd[:3] == ["docker", "image", "inspect"]:
                inspect_calls = [
                    c for c in calls if c[:3] == ["docker", "image", "inspect"]
                ]
                if len(inspect_calls) == 1:
                    return 1, "", "no such image"
                return 0, json.dumps([{"Config": {"Entrypoint": [], "Cmd": []}}]), ""

            if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["pull", "worker"]:
                return 0, "pulled", ""

            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            self.m.ensure_image_available(
                service_name="worker",
                svc=services["worker"],
                image=services["worker"]["image"],
                services=services,
                service_to_compose_cmd=service_to_cmd,
                compose_base_cmd=base_cmd,
                cwd=Path("/tmp"),
                env={},
            )

        self.assertTrue(any(c[-2:] == ["pull", "worker"] for c in calls))

    @patch.object(Path, "exists", autospec=True, return_value=True)
    @patch.object(Path, "is_dir", autospec=True, return_value=True)
    @patch.object(Path, "read_text", autospec=True)
    @patch.object(Path, "write_text", autospec=True)
    @patch.object(Path, "mkdir", autospec=True)
    def test_main_generates_override(
        self, _mkdir, _write_text, _read_text, _is_dir, _exists
    ):
        """
        main():
          - parses compose files to discover profiles
          - runs `compose ... config`
          - inspects images via `container image inspect`
          - writes override with CA_TRUST_* envs
        """
        _read_text.return_value = "services:\n  app:\n    image: myimage:latest\n"

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            if (
                len(cmd) >= 3
                and cmd[0:2] == ["docker", "compose"]
                and cmd[-1] == "config"
            ):
                yml = "services:\n  app:\n    image: myimage:latest\n"
                return 0, yml, ""

            if cmd[:3] == ["docker", "image", "inspect"]:
                json_out = json.dumps(
                    [{"Config": {"Entrypoint": ["/entry"], "Cmd": ["run"]}}]
                )
                return 0, json_out, ""

            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            argv = [
                "compose_ca.py",
                "--chdir",
                "/tmp/app",
                "--project",
                "p",
                "--compose-files",
                "-f compose.yml -f compose.override.yml",
                "--out",
                "compose.ca.override.yml",
                "--ca-host",
                "/etc/infinito/ca/root-ca.crt",
                "--wrapper-host",
                "/etc/infinito/bin/with-ca-trust.sh",
                "--ca-container",
                CA_CERT_CONTAINER,
                "--wrapper-container",
                CA_WRAPPER_CONTAINER,
                "--trust-name",
                "infinito.local",
            ]
            with patch("sys.argv", argv):
                rc = self.m.main()

        self.assertEqual(rc, 0)
        self.assertTrue(_write_text.called)

        args, _kwargs = _write_text.call_args
        written = args[1] if len(args) > 1 else ""
        self.assertIn("CA_TRUST_NAME", written)
        self.assertIn("infinito.local", written)

    @patch.object(Path, "exists", autospec=True, return_value=True)
    @patch.object(Path, "is_dir", autospec=True, return_value=True)
    @patch.object(Path, "read_text", autospec=True)
    @patch.object(Path, "write_text", autospec=True)
    @patch.object(Path, "mkdir", autospec=True)
    def test_main_empty_services_writes_noop_override(
        self, _mkdir, _write_text, _read_text, _is_dir, _exists
    ):
        """main(): an app whose merged compose has no services (a launcher-based
        app such as discourse with all backends shared) writes an empty override
        and exits 0 instead of dying with 'No services found'."""
        _read_text.return_value = "services: {}\n"

        def fake_run(cmd, *, cwd, env):
            if (
                len(cmd) >= 3
                and cmd[0:2] == ["docker", "compose"]
                and cmd[-1] == "config"
            ):
                return 0, "services: {}\n", ""
            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            argv = [
                "compose_ca.py",
                "--chdir",
                "/tmp/app",
                "--project",
                "p",
                "--compose-files",
                "-f compose.yml",
                "--out",
                "compose.ca.override.yml",
                "--ca-host",
                "/etc/infinito/ca/root-ca.crt",
                "--wrapper-host",
                "/etc/infinito/bin/with-ca-trust.sh",
                "--ca-container",
                CA_CERT_CONTAINER,
                "--wrapper-container",
                CA_WRAPPER_CONTAINER,
                "--trust-name",
                "infinito.local",
            ]
            with patch("sys.argv", argv):
                rc = self.m.main()

        self.assertEqual(rc, 0)
        self.assertTrue(_write_text.called)
        args, _kwargs = _write_text.call_args
        written = args[1] if len(args) > 1 else ""
        self.assertIn("services", written)
        self.assertNotIn("CA_TRUST_NAME", written)

    @patch.object(Path, "exists", autospec=True, return_value=True)
    @patch.object(Path, "is_dir", autospec=True, return_value=True)
    def test_main_requires_trust_name(self, _is_dir, _exists):
        argv = [
            "compose_ca.py",
            "--chdir",
            "/tmp/app",
            "--project",
            "p",
            "--compose-files",
            "-f compose.yml",
            "--out",
            "compose.ca.override.yml",
            "--ca-host",
            "/etc/infinito/ca/root-ca.crt",
            "--wrapper-host",
            "/etc/infinito/bin/with-ca-trust.sh",
            "--ca-container",
            CA_CERT_CONTAINER,
            "--wrapper-container",
            CA_WRAPPER_CONTAINER,
        ]
        with patch("sys.argv", argv), self.assertRaises(SystemExit):
            self.m.main()

    def test_docker_image_has_bin_sh_true(self):
        """
        docker_image_has_bin_sh(): returns True when container run succeeds.
        """

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            self.assertEqual(
                cmd[:6],
                ["docker", "run", "--rm", "--entrypoint", "/bin/sh", "img:1"],
            )
            self.assertEqual(cmd[6:], ["-c", "exit 0"])
            return 0, "", ""

        with patch.object(self.m, "run", side_effect=fake_run):
            ok = self.m.docker_image_has_bin_sh("img:1", cwd=Path("/tmp"), env={})
        self.assertTrue(ok)

    def test_docker_image_has_bin_sh_false(self):
        """
        docker_image_has_bin_sh(): returns False when container run fails (distroless-like).
        """

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            return 1, "", 'exec: "/bin/sh": stat /bin/sh: no such file or directory'

        with patch.object(self.m, "run", side_effect=fake_run):
            ok = self.m.docker_image_has_bin_sh("img:1", cwd=Path("/tmp"), env={})
        self.assertFalse(ok)

    def test_docker_image_has_bin_sh_ambiguous_on_timeout(self):
        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            return self.m.TIMEOUT_RC, "", "timed out after 60s"

        with patch.object(self.m, "run", side_effect=fake_run):
            state = self.m.docker_image_has_bin_sh("img:1", cwd=Path("/tmp"), env={})
        self.assertIsNone(state)

    def test_gather_one_image_pulls_when_absent(self):
        """An absent image is pulled + re-inspected so the /bin/sh probe is accurate."""
        calls = []

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            calls.append(cmd)
            if cmd[:3] == ["docker", "image", "inspect"]:
                if ["docker", "pull", "img:1"] in calls:
                    cfg = [{"Config": {"Entrypoint": ["/entry.sh"], "Cmd": ["run"]}}]
                    return 0, json.dumps(cfg), ""
                return 1, "", "No such image: img:1"
            if cmd[:2] == ["docker", "pull"]:
                return 0, "", ""
            if cmd[:5] == ["docker", "run", "--rm", "--entrypoint", "/bin/sh"]:
                return 0, "", ""
            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            exists, ep, cmd, has_sh = self.m._gather_one_image(
                "img:1", cwd=Path("/tmp"), env={}
            )
        self.assertTrue(exists)
        self.assertEqual(ep, ["/entry.sh"])
        self.assertEqual(cmd, ["run"])
        self.assertTrue(has_sh)
        self.assertIn(["docker", "pull", "img:1"], calls)

    def test_gather_one_image_no_pull_when_present(self):
        """When the image is already present, `_gather_one_image` must NOT pull."""
        calls = []

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            calls.append(cmd)
            if cmd[:3] == ["docker", "image", "inspect"]:
                cfg = [{"Config": {"Entrypoint": ["/entry.sh"], "Cmd": ["run"]}}]
                return 0, json.dumps(cfg), ""
            if cmd[:5] == ["docker", "run", "--rm", "--entrypoint", "/bin/sh"]:
                return 0, "", ""
            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            exists, _ep, _cmd, has_sh = self.m._gather_one_image(
                "img:1", cwd=Path("/tmp"), env={}
            )
        self.assertTrue(exists)
        self.assertTrue(has_sh)
        self.assertNotIn(["docker", "pull", "img:1"], calls)

    def test_gather_one_image_never_pulls_built_tags(self):
        """A locally-built tag must not be pulled: the registry would serve an
        unrelated base image whose CMD then gets pinned into the override."""
        calls = []

        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            calls.append(cmd)
            if cmd[:3] == ["docker", "image", "inspect"]:
                return 1, "", "No such image: python:3.14-bookworm"
            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            exists, _ep, _cmd, _has_sh = self.m._gather_one_image(
                "python:3.14-bookworm", cwd=Path("/tmp"), env={}, pull_if_absent=False
            )
        self.assertFalse(exists)
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in calls))

    def test_gather_image_meta_skips_pull_for_built_images(self):
        """gather_image_meta must route built tags through pull_if_absent=False."""
        seen = {}

        def fake_gather(image, *, cwd, env, pull_if_absent=True):
            seen[image] = pull_if_absent
            return (False, [], [], False)

        with patch.object(self.m, "_gather_one_image", side_effect=fake_gather):
            self.m.gather_image_meta(
                ["built:1", "pulled:1"],
                cwd=Path("/tmp"),
                env={},
                built_images={"built:1"},
            )
        self.assertFalse(seen["built:1"])
        self.assertTrue(seen["pulled:1"])

    def test_render_override_wraps_when_probe_ambiguous(self):
        services = {"svc": {"image": "img:1"}}
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={"img:1": (True, ["/entry"], ["run"], None)},
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        out = doc["services"]["svc"]
        self.assertEqual(out.get("entrypoint"), [CA_WRAPPER_CONTAINER])
        self.assertEqual(out.get("command"), ["/entry", "run"])

    def test_render_override_wraps_when_inspect_ambiguous(self):
        services = {
            "svc": {
                "image": "img:1",
                "entrypoint": ["/svc-entry"],
                "command": ["svc-run"],
            }
        }
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={"img:1": (False, [], [], None)},
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        out = doc["services"]["svc"]
        self.assertEqual(out.get("entrypoint"), [CA_WRAPPER_CONTAINER])
        self.assertEqual(out.get("command"), ["/svc-entry", "svc-run"])

    def test_render_override_env_only_when_probe_clean_negative(self):
        services = {"svc": {"image": "img:1"}}
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={"img:1": (True, ["/entry"], ["run"], False)},
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        out = doc["services"]["svc"]
        self.assertNotIn("entrypoint", out)
        self.assertNotIn("command", out)
        self.assertIn("environment", out)
        self.assertIn("volumes", out)

    def test_gather_one_image_inspect_timeout_is_ambiguous(self):
        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            if cmd[:3] == ["docker", "image", "inspect"]:
                return self.m.TIMEOUT_RC, "", "timed out after 90s"
            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            meta = self.m._gather_one_image("img:1", cwd=Path("/tmp"), env={})

        self.assertEqual(meta, (False, [], [], None))

    def test_gather_one_image_inspect_clean_negative_no_shell(self):
        def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
            if cmd[:3] == ["docker", "image", "inspect"]:
                return 1, "", "no such image"
            return 1, "", "unexpected"

        with patch.object(self.m, "run", side_effect=fake_run):
            meta = self.m._gather_one_image("img:1", cwd=Path("/tmp"), env={})

        self.assertEqual(meta, (False, [], [], False))

    def test_render_override_sets_env_and_mounts_always(self):
        """
        render_override(): must always set CA env vars + fallback envs and always mount CA+wrapper.
        This must hold even for images without /bin/sh (no entrypoint override in that case).
        """
        services = {"svc": {"image": "img:1"}}
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={"img:1": (True, ["/entry"], ["run"], False)},
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        self.assertIn("services", doc)
        self.assertIn("svc", doc["services"])
        out = doc["services"]["svc"]

        self.assertIn("volumes", out)
        self.assertIn(f"/host/ca.crt:{CA_CERT_CONTAINER}:ro", out["volumes"])
        self.assertIn(
            f"/host/with-ca-trust.sh:{CA_WRAPPER_CONTAINER}:ro",
            out["volumes"],
        )

        env = out.get("environment", {})
        self.assertEqual(env.get("CA_TRUST_CERT"), CA_CERT_CONTAINER)
        self.assertEqual(env.get("CA_TRUST_NAME"), "infinito.local")
        self.assertEqual(env.get("SSL_CERT_FILE"), CA_CERT_CONTAINER)
        self.assertEqual(env.get("REQUESTS_CA_BUNDLE"), CA_CERT_CONTAINER)
        self.assertEqual(env.get("CURL_CA_BUNDLE"), CA_CERT_CONTAINER)
        self.assertEqual(env.get("NODE_EXTRA_CA_CERTS"), CA_CERT_CONTAINER)

        self.assertNotIn("entrypoint", out)
        self.assertNotIn("command", out)

    def test_render_override_wraps_when_sh_exists(self):
        """
        render_override(): when /bin/sh exists, it must override entrypoint to wrapper
        and set command to the effective command (final entrypoint + final cmd).
        """
        services = {"svc": {"image": "img:1"}}
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={"img:1": (True, ["/entry"], ["run", "--flag"], True)},
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        out = doc["services"]["svc"]
        self.assertEqual(out.get("entrypoint"), [CA_WRAPPER_CONTAINER])
        self.assertEqual(out.get("command"), ["/entry", "run", "--flag"])

    def test_render_override_uses_service_entrypoint_command_over_image(self):
        """
        If the composed config explicitly sets entrypoint/command, those must win over image defaults.
        effective_cmd = svc_entrypoint + svc_command
        """
        services = {
            "svc": {
                "image": "img:1",
                "entrypoint": ["/svc-entry"],
                "command": ["svc-run", "x"],
            }
        }
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={"img:1": (True, ["/img-entry"], ["img-run"], True)},
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        out = doc["services"]["svc"]
        self.assertEqual(out["command"], ["/svc-entry", "svc-run", "x"])

    def test_render_override_collapses_shell_command_when_entrypoint_is_shell(self):
        """
        If the composed service already uses a shell entrypoint, the command must stay
        a single shell payload so /bin/sh -c receives exactly one argument.
        """
        shell_tokens = [
            "if",
            "!",
            "grep",
            "-qF",
            "INFINITO_TAIGA_AUTH_CONFIG",  # nocheck: test-fixture
            "/taiga-back/settings/config.py",
            ";",
            "then",
            "cat",
            "/taiga-back/settings/config.append.py",
            ">>",
            "/taiga-back/settings/config.py",
            ";",
            "fi",
            ";",
            "exec",
            "/taiga-back/docker/entrypoint.sh",
        ]
        services = {
            "svc": {
                "image": "img:1",
                "entrypoint": ["/bin/sh", "-c"],
                "command": shell_tokens,
            }
        }
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={"img:1": (True, ["/entry"], ["run"], True)},
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        out = doc["services"]["svc"]
        self.assertEqual(out.get("entrypoint"), [CA_WRAPPER_CONTAINER])
        self.assertEqual(out.get("command")[:2], ["/bin/sh", "-c"])
        self.assertEqual(
            out.get("command")[2],
            "if ! grep -qF INFINITO_TAIGA_AUTH_CONFIG /taiga-back/settings/config.py ; then cat /taiga-back/settings/config.append.py >> /taiga-back/settings/config.py ; fi ; exec /taiga-back/docker/entrypoint.sh",
        )

    def test_render_override_gathers_each_unique_image_once(self):
        """Image metadata is gathered once per unique image, not per service."""
        services = {
            "a": {"image": "img:1"},
            "b": {"image": "img:1"},
        }
        service_to_cmd = {
            "a": ["docker", "compose", "-p", "p", "-f", "compose.yml"],
            "b": ["docker", "compose", "-p", "p", "-f", "compose.yml"],
        }

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={"img:1": (True, ["/entry"], ["run"], True)},
        ) as p_gather:
            self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        p_gather.assert_called_once()
        self.assertEqual(p_gather.call_args.args[0], ["img:1"])

    def test_main_generates_override_includes_entrypoint_when_sh_exists(self):
        """
        main(): when /bin/sh exists for the image, the written override should include entrypoint wrapper.
        """
        with (
            patch.object(Path, "exists", autospec=True, return_value=True),
            patch.object(Path, "is_dir", autospec=True, return_value=True),
            patch.object(
                Path,
                "read_text",
                autospec=True,
                return_value="services:\n  app:\n    image: myimage:latest\n",
            ),
            patch.object(Path, "mkdir", autospec=True),
            patch.object(Path, "write_text", autospec=True) as p_write,
        ):

            def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
                if (
                    len(cmd) >= 3
                    and cmd[0:2] == ["docker", "compose"]
                    and cmd[-1] == "config"
                ):
                    yml = "services:\n  app:\n    image: myimage:latest\n"
                    return 0, yml, ""

                if cmd[:3] == ["docker", "image", "inspect"]:
                    json_out = json.dumps(
                        [{"Config": {"Entrypoint": ["/entry"], "Cmd": ["run"]}}]
                    )
                    return 0, json_out, ""

                if cmd[:6] == [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint",
                    "/bin/sh",
                    "myimage:latest",
                ]:
                    return 0, "", ""

                return 1, "", "unexpected"

            with patch.object(self.m, "run", side_effect=fake_run):
                argv = [
                    "compose_ca.py",
                    "--chdir",
                    "/tmp/app",
                    "--project",
                    "p",
                    "--compose-files",
                    "-f compose.yml -f compose.override.yml",
                    "--out",
                    "compose.ca.override.yml",
                    "--ca-host",
                    "/etc/infinito/ca/root-ca.crt",
                    "--wrapper-host",
                    "/etc/infinito/bin/with-ca-trust.sh",
                    "--ca-container",
                    CA_CERT_CONTAINER,
                    "--wrapper-container",
                    CA_WRAPPER_CONTAINER,
                    "--trust-name",
                    "infinito.local",
                ]
                with patch("sys.argv", argv):
                    rc = self.m.main()

            self.assertEqual(rc, 0)
            self.assertTrue(p_write.called)

            args, _kwargs = p_write.call_args
            written = args[1] if len(args) > 1 else ""
            parsed = load_yaml_str(written)
            self.assertIn("services", parsed)
            self.assertIn("app", parsed["services"])
            self.assertEqual(
                parsed["services"]["app"].get("entrypoint"),
                [CA_WRAPPER_CONTAINER],
            )

    def test_escape_compose_vars_replaces_single_dollar(self):
        """
        escape_compose_vars(): must replace $ with $$ so Compose does not interpolate on host.
        """
        self.assertEqual(
            self.m.escape_compose_vars(['exec "$FOO"']),
            ['exec "$$FOO"'],
        )
        self.assertEqual(
            self.m.escape_compose_vars(["$FOO", "${FOO}", "x$y", "$", "plain"]),
            ["$$FOO", "$${FOO}", "x$$y", "$$", "plain"],
        )

    def test_escape_compose_vars_keeps_strings_without_dollar_unchanged(self):
        """
        escape_compose_vars(): must not modify strings without '$'.
        """
        argv = ["/entry", "run", "--flag", "exec /bin/app", "x_y-z.1"]
        self.assertEqual(self.m.escape_compose_vars(argv), argv)

    def test_render_override_escapes_dollar_in_command_when_wrapping(self):
        """
        render_override(): when wrapping is enabled (has /bin/sh),
        command argv must have $ escaped to $$ to prevent host-side Compose interpolation.
        """
        services = {"svc": {"image": "img:1"}}
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={
                "img:1": (True, [], ["sh", "-lc", 'exec "$CHESS_ENTRYPOINT_INT"'], True)
            },
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        out = doc["services"]["svc"]
        self.assertEqual(out.get("entrypoint"), [CA_WRAPPER_CONTAINER])
        self.assertEqual(
            out.get("command"),
            ["sh", "-lc", 'exec "$$CHESS_ENTRYPOINT_INT"'],
        )

    def test_render_override_no_wrapper_emits_env_and_mounts_only(self):
        """
        render_override(wrap=False): swarm path must emit only volumes + environment,
        never entrypoint/command (docker stack deploy does not un-escape $$), and must
        not probe/inspect/pull the image (images need not exist at generation time).
        """
        services = {"svc": {"image": "img:1"}}
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with (
            patch.object(self.m, "ensure_image_available") as p_ensure,
            patch.object(self.m, "docker_image_inspect") as p_inspect,
            patch.object(self.m, "docker_image_has_bin_sh") as p_has_sh,
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
                wrap=False,
            )

        out = doc["services"]["svc"]
        self.assertIn("volumes", out)
        self.assertEqual(out["environment"].get("SSL_CERT_FILE"), CA_CERT_CONTAINER)
        self.assertNotIn("entrypoint", out)
        self.assertNotIn("command", out)
        p_ensure.assert_not_called()
        p_inspect.assert_not_called()
        p_has_sh.assert_not_called()

    def test_render_override_does_not_escape_when_not_wrapping(self):
        """
        render_override(): when /bin/sh does NOT exist (distroless-like),
        we must not set 'command' at all (and therefore no escaping occurs).
        """
        services = {"svc": {"image": "img:1"}}
        service_to_cmd = {"svc": ["docker", "compose", "-p", "p", "-f", "compose.yml"]}

        with patch.object(
            self.m,
            "gather_image_meta",
            return_value={
                "img:1": (
                    True,
                    [],
                    ["sh", "-lc", 'exec "$CHESS_ENTRYPOINT_INT"'],
                    False,
                )
            },
        ):
            doc = self.m.render_override(
                services,
                service_to_cmd,
                cwd=Path("/tmp"),
                env={},
                ca_host="/host/ca.crt",
                wrapper_host="/host/with-ca-trust.sh",
                ca_container=CA_CERT_CONTAINER,
                wrapper_container=CA_WRAPPER_CONTAINER,
                trust_name="infinito.local",
            )

        out = doc["services"]["svc"]
        self.assertNotIn("entrypoint", out)
        self.assertNotIn("command", out)

    def test_main_writes_override_with_escaped_dollar_when_image_cmd_contains_dollar(
        self,
    ):
        """
        main(): if the image Cmd contains '$VAR', the written override must contain '$$VAR'
        (Compose-escape) so the container shell can expand it at runtime.
        """
        with (
            patch.object(Path, "exists", autospec=True, return_value=True),
            patch.object(Path, "is_dir", autospec=True, return_value=True),
            patch.object(
                Path,
                "read_text",
                autospec=True,
                return_value="services:\n  app:\n    image: myimage:latest\n",
            ),
            patch.object(Path, "mkdir", autospec=True),
            patch.object(Path, "write_text", autospec=True) as p_write,
        ):

            def fake_run(cmd, *, cwd, env, timeout=None, capture=True):
                if (
                    len(cmd) >= 3
                    and cmd[0:2] == ["docker", "compose"]
                    and cmd[-1] == "config"
                ):
                    yml = "services:\n  app:\n    image: myimage:latest\n"
                    return 0, yml, ""

                if cmd[:3] == ["docker", "image", "inspect"]:
                    json_out = json.dumps(
                        [
                            {
                                "Config": {
                                    "Entrypoint": [],
                                    "Cmd": [
                                        "sh",
                                        "-lc",
                                        'exec "$CHESS_ENTRYPOINT_INT"',
                                    ],
                                }
                            }
                        ]
                    )
                    return 0, json_out, ""

                if cmd[:6] == [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint",
                    "/bin/sh",
                    "myimage:latest",
                ]:
                    return 0, "", ""

                return 1, "", "unexpected"

            with patch.object(self.m, "run", side_effect=fake_run):
                argv = [
                    "compose_ca.py",
                    "--chdir",
                    "/tmp/app",
                    "--project",
                    "p",
                    "--compose-files",
                    "-f compose.yml",
                    "--out",
                    "compose.ca.override.yml",
                    "--ca-host",
                    "/etc/infinito/ca/root-ca.crt",
                    "--wrapper-host",
                    "/etc/infinito/bin/with-ca-trust.sh",
                    "--ca-container",
                    CA_CERT_CONTAINER,
                    "--wrapper-container",
                    CA_WRAPPER_CONTAINER,
                    "--trust-name",
                    "infinito.local",
                ]
                with patch("sys.argv", argv):
                    rc = self.m.main()

        self.assertEqual(rc, 0)
        self.assertTrue(p_write.called)

        args, _kwargs = p_write.call_args
        written = args[1] if len(args) > 1 else ""
        parsed = load_yaml_str(written)

        self.assertIn("services", parsed)
        self.assertIn("app", parsed["services"])
        self.assertEqual(
            parsed["services"]["app"].get("command"),
            ["sh", "-lc", 'exec "$$CHESS_ENTRYPOINT_INT"'],
        )


if __name__ == "__main__":
    unittest.main()
