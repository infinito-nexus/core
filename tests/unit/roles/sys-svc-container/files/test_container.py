from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

THIS_FILE = Path(__file__).resolve()

CONTAINER_PY = PROJECT_ROOT / "roles" / "sys-svc-container" / "files" / "container.py"

_CA_TRUST = load_yaml(str(PROJECT_ROOT / "group_vars" / "all" / "02_tls.yml"))[
    "CA_TRUST"
]
CA_CERT_CONTAINER = _CA_TRUST["inject_cert_container"]
CA_WRAPPER_CONTAINER = _CA_TRUST["inject_wrapper_container"]

if not CONTAINER_PY.exists():
    raise FileNotFoundError(f"container.py not found at {CONTAINER_PY}")

spec = importlib.util.spec_from_file_location("container", CONTAINER_PY)
container = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(container)


class TestContainerWrapper(unittest.TestCase):
    # -----------------------------------------------------------------------
    # split_docker_run_argv
    # -----------------------------------------------------------------------

    def test_split_docker_run_argv_image_only(self):
        run_opts, image_and_args = container.split_docker_run_argv(["alpine:3.20"])
        self.assertEqual(run_opts, [])
        self.assertEqual(image_and_args, ["alpine:3.20"])

    def test_split_docker_run_argv_with_flags_and_command(self):
        argv = [
            "--rm",
            "--network",
            "host",
            "-e",
            "A=B",
            "alpine:3.20",
            "sh",
            "-lc",
            "echo hi",
        ]
        run_opts, image_and_args = container.split_docker_run_argv(argv)
        self.assertEqual(run_opts, ["--rm", "--network", "host", "-e", "A=B"])
        self.assertEqual(image_and_args, ["alpine:3.20", "sh", "-lc", "echo hi"])

    def test_split_docker_run_argv_respects_double_dash(self):
        argv = ["--rm", "--", "alpine:3.20", "echo", "hi"]
        run_opts, image_and_args = container.split_docker_run_argv(argv)
        self.assertEqual(run_opts, ["--rm", "--"])
        self.assertEqual(image_and_args, ["alpine:3.20", "echo", "hi"])

    def test_split_docker_run_argv_missing_image_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            container.split_docker_run_argv(["--rm", "--network", "host"])
        self.assertEqual(ctx.exception.code, 2)

    # -----------------------------------------------------------------------
    # extract_entrypoint
    # -----------------------------------------------------------------------

    def test_extract_entrypoint_space_form(self):
        run_opts, ep = container.extract_entrypoint(
            ["--rm", "--entrypoint", "sh", "--network", "host"]
        )
        self.assertEqual(ep, "sh")
        self.assertEqual(run_opts, ["--rm", "--network", "host"])

    def test_extract_entrypoint_equals_form(self):
        run_opts, ep = container.extract_entrypoint(
            ["--rm", "--entrypoint=sh", "--network", "host"]
        )
        self.assertEqual(ep, "sh")
        self.assertEqual(run_opts, ["--rm", "--network", "host"])

    # -----------------------------------------------------------------------
    # extract_pull_policy
    # -----------------------------------------------------------------------

    def test_extract_pull_policy_default(self):
        self.assertEqual(container.extract_pull_policy(["--rm"]), "missing")

    def test_extract_pull_policy_variants(self):
        cases = [
            (["--rm", "--pull", "always"], "always"),
            (["--rm", "--pull=always"], "always"),
            (["--rm", "--pull", "never"], "never"),
            (["--rm", "--pull=missing"], "missing"),
            (["--rm", "--pull", "invalid"], "missing"),
        ]
        for opts, expected in cases:
            with self.subTest(opts=opts):
                self.assertEqual(container.extract_pull_policy(opts), expected)

    # -----------------------------------------------------------------------
    # try_inspect_entrypoint_with_pull
    # -----------------------------------------------------------------------

    def test_try_inspect_entrypoint_pull_always(self):
        calls = []

        def fake_pull(image: str) -> None:
            calls.append(("pull", image))

        def fake_inspect(image: str):
            calls.append(("inspect", image))
            return ["/entrypoint"]

        orig_pull = container.docker_pull
        orig_inspect = container.inspect_image_entrypoint
        try:
            container.docker_pull = fake_pull
            container.inspect_image_entrypoint = fake_inspect

            ep = container.try_inspect_entrypoint_with_pull(
                "alpine:3.20",
                pull_policy="always",
            )
            self.assertEqual(ep, ["/entrypoint"])
            self.assertEqual(
                calls,
                [("pull", "alpine:3.20"), ("inspect", "alpine:3.20")],
            )
        finally:
            container.docker_pull = orig_pull
            container.inspect_image_entrypoint = orig_inspect

    def test_try_inspect_entrypoint_pull_missing_recovers(self):
        """
        New behavior (after your refactor):
        - inspect fails (SystemExit)
        - for pull_policy in {"missing","always"}: docker_pull() is called
        - then inspect is retried
        No subprocess.run() probing anymore.
        """
        calls = []

        def inspect_fail(image: str):
            calls.append(("inspect_fail", image))
            raise SystemExit(2)

        def inspect_ok(image: str):
            calls.append(("inspect_ok", image))
            return ["/entrypoint"]

        def fake_pull(image: str) -> None:
            calls.append(("pull", image))
            container.inspect_image_entrypoint = inspect_ok

        orig_pull = container.docker_pull
        orig_inspect = container.inspect_image_entrypoint
        try:
            container.inspect_image_entrypoint = inspect_fail
            container.docker_pull = fake_pull

            ep = container.try_inspect_entrypoint_with_pull(
                "alpine:3.20",
                pull_policy="missing",
            )

            self.assertEqual(ep, ["/entrypoint"])
            self.assertEqual(
                calls,
                [
                    ("inspect_fail", "alpine:3.20"),
                    ("pull", "alpine:3.20"),
                    ("inspect_ok", "alpine:3.20"),
                ],
            )
        finally:
            container.docker_pull = orig_pull
            container.inspect_image_entrypoint = orig_inspect

    def test_try_inspect_entrypoint_pull_never_fails(self):
        def inspect_fail(_image: str):
            raise SystemExit(2)

        orig_inspect = container.inspect_image_entrypoint
        try:
            container.inspect_image_entrypoint = inspect_fail

            with self.assertRaises(SystemExit) as ctx:
                container.try_inspect_entrypoint_with_pull(
                    "alpine:3.20",
                    pull_policy="never",
                )
            self.assertEqual(ctx.exception.code, 2)
        finally:
            container.inspect_image_entrypoint = orig_inspect

    # -----------------------------------------------------------------------
    # require_ca_env_soft
    # -----------------------------------------------------------------------

    def test_require_ca_env_soft_missing_env_returns_none_and_warns(self):
        """
        If the host CA env trio is missing, require_ca_env_soft() should:
          - return None
          - emit a warning on stderr
        """
        old_env = dict(os.environ)
        try:
            os.environ.pop("CA_TRUST_CERT_HOST", None)
            os.environ.pop("CA_TRUST_WRAPPER_HOST", None)
            os.environ.pop("CA_TRUST_NAME", None)
            os.environ.pop("CA_TRUST_CERT_CONTAINER", None)
            os.environ.pop("CA_TRUST_WRAPPER_CONTAINER", None)

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                res = container.require_ca_env_soft()

            self.assertIsNone(res)
            out = buf.getvalue()
            self.assertIn("[container][WARN]", out)
            self.assertIn("CA injection disabled (missing env:", out)
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_require_ca_env_soft_half_migrated_dies_loudly(self):
        """
        Host trio present but container paths absent = half-migrated caller:
        require_ca_env_soft() must fail hard instead of silently stripping
        CA trust from a host that clearly wants it.
        """
        old_env = dict(os.environ)
        try:
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                ca_file = td_path / "root-ca.crt"
                wrapper_file = td_path / "with-ca-trust.sh"
                ca_file.write_text("dummy-ca\n", encoding="utf-8")
                wrapper_file.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")

                os.environ["CA_TRUST_CERT_HOST"] = str(ca_file)
                os.environ["CA_TRUST_WRAPPER_HOST"] = str(wrapper_file)
                os.environ["CA_TRUST_NAME"] = "test-ca"
                os.environ.pop("CA_TRUST_CERT_CONTAINER", None)
                os.environ.pop("CA_TRUST_WRAPPER_CONTAINER", None)

                buf = io.StringIO()
                with (
                    contextlib.redirect_stderr(buf),
                    self.assertRaises(SystemExit),
                ):
                    container.require_ca_env_soft()

                self.assertIn("CA injection misconfigured", buf.getvalue())
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_require_ca_env_soft_missing_files_returns_none_and_warns(self):
        """
        If env vars exist but point to non-existing files, require_ca_env_soft() should:
          - return None
          - emit a warning on stderr
        """
        old_env = dict(os.environ)
        try:
            os.environ["CA_TRUST_CERT_HOST"] = "/does/not/exist/ca.crt"
            os.environ["CA_TRUST_WRAPPER_HOST"] = "/does/not/exist/with-ca-trust.sh"
            os.environ["CA_TRUST_NAME"] = "test-ca"
            os.environ["CA_TRUST_CERT_CONTAINER"] = CA_CERT_CONTAINER
            os.environ["CA_TRUST_WRAPPER_CONTAINER"] = CA_WRAPPER_CONTAINER

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                res = container.require_ca_env_soft()

            self.assertIsNone(res)
            out = buf.getvalue()
            self.assertIn("[container][WARN]", out)
            self.assertIn("CA injection disabled (CA files not found)", out)
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_require_ca_env_soft_ok_returns_tuple(self):
        """
        If env vars and referenced files exist, require_ca_env_soft() should return tuple.
        """
        old_env = dict(os.environ)
        try:
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                ca_file = td_path / "root-ca.crt"
                wrapper_file = td_path / "with-ca-trust.sh"

                ca_file.write_text("dummy-ca\n", encoding="utf-8")
                wrapper_file.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")

                os.environ["CA_TRUST_CERT_HOST"] = str(ca_file)
                os.environ["CA_TRUST_WRAPPER_HOST"] = str(wrapper_file)
                os.environ["CA_TRUST_NAME"] = "test-ca"
                os.environ["CA_TRUST_CERT_CONTAINER"] = CA_CERT_CONTAINER
                os.environ["CA_TRUST_WRAPPER_CONTAINER"] = CA_WRAPPER_CONTAINER

                buf = io.StringIO()
                with contextlib.redirect_stderr(buf):
                    res = container.require_ca_env_soft()

                self.assertIsNotNone(res)
                assert res is not None
                ca_host, wrapper_host, trust_name, ca_container, wrapper_container = res
                self.assertEqual(ca_host, str(ca_file))
                self.assertEqual(wrapper_host, str(wrapper_file))
                self.assertEqual(trust_name, "test-ca")
                self.assertEqual(ca_container, CA_CERT_CONTAINER)
                self.assertEqual(wrapper_container, CA_WRAPPER_CONTAINER)
                self.assertEqual(buf.getvalue().strip(), "")
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    # -----------------------------------------------------------------------
    # container_run fallback (no CA available)
    # -----------------------------------------------------------------------

    def test_container_run_falls_back_to_plain_docker_run_when_ca_missing(self):
        """
        When with_ca=True but CA env is missing, container_run() must fallback to:
          exec_docker(["docker","run", *argv])
        """
        old_env = dict(os.environ)
        calls = []

        def fake_exec_docker(cmd, debug=False):
            calls.append(("exec_docker", cmd, debug))
            return 0

        orig_exec_docker = container.exec_docker
        try:
            os.environ.pop("CA_TRUST_CERT_HOST", None)
            os.environ.pop("CA_TRUST_WRAPPER_HOST", None)
            os.environ.pop("CA_TRUST_NAME", None)

            container.exec_docker = fake_exec_docker

            argv = ["--rm", "alpine:3.20", "sh", "-lc", "echo hi"]
            rc = container.container_run(argv, debug=True, with_ca=True)

            self.assertEqual(rc, 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                calls[0][1],
                ["docker", "run", *argv],
            )
            self.assertTrue(calls[0][2])
        finally:
            container.exec_docker = orig_exec_docker
            os.environ.clear()
            os.environ.update(old_env)

    def test_container_run_injects_ca_env_when_image_has_no_entrypoint(self):
        """
        When with_ca=True, CA env is available, but the image has no ENTRYPOINT,
        container_run() must inject CA env vars and volume without an entrypoint wrapper.
        """
        old_env = dict(os.environ)
        calls = []

        def fake_exec_docker(cmd, debug=False):
            calls.append(("exec_docker", cmd, debug))
            return 0

        def fake_try_inspect_no_ep(image, pull_policy):
            return []

        orig_exec_docker = container.exec_docker
        orig_try_inspect = container.try_inspect_entrypoint_with_pull
        try:
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                ca_file = td_path / "root-ca.crt"
                wrapper_file = td_path / "with-ca-trust.sh"
                ca_file.write_text("dummy-ca\n", encoding="utf-8")
                wrapper_file.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")

                os.environ["CA_TRUST_CERT_HOST"] = str(ca_file)
                os.environ["CA_TRUST_WRAPPER_HOST"] = str(wrapper_file)
                os.environ["CA_TRUST_NAME"] = "test-ca"
                os.environ["CA_TRUST_CERT_CONTAINER"] = CA_CERT_CONTAINER
                os.environ["CA_TRUST_WRAPPER_CONTAINER"] = CA_WRAPPER_CONTAINER

                container.exec_docker = fake_exec_docker
                container.try_inspect_entrypoint_with_pull = fake_try_inspect_no_ep

                argv = ["--rm", "playwright:v1.0", "/bin/bash", "-lc", "npm install"]
                rc = container.container_run(argv, debug=False, with_ca=True)

            self.assertEqual(rc, 0)
            self.assertEqual(len(calls), 1)
            cmd = calls[0][1]
            self.assertEqual(cmd[0], "docker")
            self.assertEqual(cmd[1], "run")
            cmd_str = " ".join(cmd)
            self.assertIn("NODE_EXTRA_CA_CERTS", cmd_str)
            self.assertIn(CA_CERT_CONTAINER, cmd_str)
            self.assertNotIn("--entrypoint", cmd_str)
            self.assertIn("playwright:v1.0", cmd_str)
            self.assertIn("npm install", cmd_str)
        finally:
            container.exec_docker = orig_exec_docker
            container.try_inspect_entrypoint_with_pull = orig_try_inspect
            os.environ.clear()
            os.environ.update(old_env)

    def test_container_run_with_ca_false_always_plain_docker_run(self):
        """
        When with_ca=False, container_run() must always call plain container run (no env needed).
        """
        calls = []

        def fake_exec_docker(cmd, debug=False):
            calls.append(("exec_docker", cmd, debug))
            return 0

        orig_exec_docker = container.exec_docker
        try:
            container.exec_docker = fake_exec_docker

            argv = ["--rm", "alpine:3.20", "echo", "hi"]
            rc = container.container_run(argv, debug=False, with_ca=False)

            self.assertEqual(rc, 0)
            self.assertEqual(
                calls,
                [("exec_docker", ["docker", "run", *argv], False)],
            )
        finally:
            container.exec_docker = orig_exec_docker


if __name__ == "__main__":
    unittest.main()
