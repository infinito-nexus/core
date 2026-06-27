import os
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import read_text


def load_script_module():
    """
    Import the script under test from roles/sys-svc-compose/files/compose.py
    """
    test_file = Path(__file__).resolve()
    repo_root = test_file.parents[
        5
    ]  # .../tests/unit/roles/sys-svc-compose/files -> repo root
    script_path = repo_root / "roles" / "sys-svc-compose" / "files" / "compose.py"
    if not script_path.exists():
        raise FileNotFoundError(f"compose.py not found at {script_path}")
    spec = spec_from_file_location("compose", str(script_path))
    mod = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


class TestInfinitoComposeWrapper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script_module()

    def setUp(self):
        # Disable the wrapper's cache-override branch; tests use mocked is_file.
        self._env_patch = patch.dict(
            os.environ, {"INFINITO_CACHE_PACKAGE_FRONTEND_IP": ""}, clear=False
        )
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_detect_env_file_priority(self):
        s = self.script
        base = Path("/proj")

        old_is_file = s.Path.is_file
        try:

            def fake_is_file(self: Path) -> bool:
                return str(self) == "/proj/.env"

            s.Path.is_file = fake_is_file  # type: ignore[assignment]
            self.assertEqual(s.detect_env_file(base), Path("/proj/.env"))

            def fake_is_file2(self: Path) -> bool:
                return str(self) == "/proj/.env/env"

            s.Path.is_file = fake_is_file2  # type: ignore[assignment]
            self.assertEqual(s.detect_env_file(base), Path("/proj/.env/env"))

            def fake_is_file3(self: Path) -> bool:
                return str(self) in ("/proj/.env", "/proj/.env/env")

            s.Path.is_file = fake_is_file3  # type: ignore[assignment]
            self.assertEqual(s.detect_env_file(base), Path("/proj/.env"))

            def fake_is_file4(self: Path) -> bool:
                return False

            s.Path.is_file = fake_is_file4  # type: ignore[assignment]
            self.assertIsNone(s.detect_env_file(base))
        finally:
            s.Path.is_file = old_is_file  # type: ignore[assignment]

    def test_detect_compose_files_includes_optional_in_order(self):
        s = self.script
        base = Path("/proj")

        old_is_file = s.Path.is_file
        try:

            def fake_is_file(self: Path) -> bool:
                if str(self) == "/proj/compose.yml":
                    return True
                if str(self) == "/proj/compose.override.yml":
                    return True
                return str(self) == "/proj/compose.ca.override.yml"

            s.Path.is_file = fake_is_file  # type: ignore[assignment]
            files = s.detect_compose_files(base)
            self.assertEqual(
                [str(p) for p in files],
                [
                    "/proj/compose.yml",
                    "/proj/compose.override.yml",
                    "/proj/compose.ca.override.yml",
                ],
            )
        finally:
            s.Path.is_file = old_is_file  # type: ignore[assignment]

    def test_build_cmd_contains_env_and_files(self):
        s = self.script
        base = Path("/proj")

        old_is_file = s.Path.is_file
        try:

            def fake_is_file(self: Path) -> bool:
                if str(self) == "/proj/compose.yml":
                    return True
                if str(self) == "/proj/compose.override.yml":
                    return True
                if str(self) == "/proj/compose.ca.override.yml":
                    return False
                if str(self) == "/proj/.env":
                    return True
                return str(self) == "/proj/.env/env"

            s.Path.is_file = fake_is_file  # type: ignore[assignment]
            # Signature changed to accept extra_files=None, but default keeps old call valid.
            cmd = s.build_cmd("myproj", base, ["up", "-d"])

            self.assertEqual(cmd[:4], ["docker", "compose", "-p", "myproj"])
            self.assertIn("-f", cmd)
            self.assertIn("/proj/compose.yml", cmd)
            self.assertIn("/proj/compose.override.yml", cmd)
            self.assertNotIn("/proj/compose.ca.override.yml", cmd)

            self.assertIn("--env-file", cmd)
            self.assertIn("/proj/.env", cmd)

            self.assertEqual(cmd[-2:], ["up", "-d"])
        finally:
            s.Path.is_file = old_is_file  # type: ignore[assignment]

    def test_build_cmd_appends_extra_files_after_autodetected(self):
        """-f/--file is appended after autodetection, not a replacement."""
        s = self.script
        base = Path("/proj")

        old_is_file = s.Path.is_file
        old_resolve_files = getattr(s, "resolve_files", None)

        try:

            def fake_is_file(self: Path) -> bool:
                if str(self) == "/proj/compose.yml":
                    return True
                if str(self) == "/proj/compose.override.yml":
                    return True
                if str(self) == "/proj/compose.ca.override.yml":
                    return False
                if str(self) == "/proj/.env":
                    return True
                if str(self) == "/proj/.env/env":
                    return False
                return False

            # Avoid touching real filesystem resolution
            def fake_resolve_files(project_dir: Path, files):
                out = []
                for f in files:
                    if str(f).startswith("/"):
                        out.append(Path(f))
                    else:
                        out.append(Path("/proj") / str(f))
                return out

            s.Path.is_file = fake_is_file  # type: ignore[assignment]
            if old_resolve_files is not None:
                s.resolve_files = fake_resolve_files  # type: ignore[assignment]

            cmd = s.build_cmd(
                "myproj",
                base,
                ["run", "--rm", "manager", "migrate", "--noinput"],
                extra_files=["compose-inits.yml"],
            )

            # Ensure order: autodetected files appear before extra file
            idx_base = cmd.index("/proj/compose.yml")
            idx_override = cmd.index("/proj/compose.override.yml")
            idx_extra = cmd.index("/proj/compose-inits.yml")
            self.assertLess(idx_base, idx_extra)
            self.assertLess(idx_override, idx_extra)

            # Basic sanity: env file still included
            self.assertIn("--env-file", cmd)
            self.assertIn("/proj/.env", cmd)

            # Passthrough still ends command
            self.assertEqual(
                cmd[-5:], ["run", "--rm", "manager", "migrate", "--noinput"]
            )
        finally:
            s.Path.is_file = old_is_file  # type: ignore[assignment]
            if old_resolve_files is not None:
                s.resolve_files = old_resolve_files  # type: ignore[assignment]

    def test_subcommand_is_first_passthrough_token(self):
        s = self.script
        self.assertEqual(s._subcommand(["build"]), "build")
        self.assertEqual(s._subcommand(["config", "-q"]), "config")
        self.assertEqual(s._subcommand(["up", "-d"]), "up")
        self.assertEqual(s._subcommand([]), "")

    def test_build_cmd_build_strips_env_files_and_drops_env_file_flag(self):
        """`build` runs against env_file-stripped copies with no --env-file.

        compose build parses every service env_file and rejects $-bearing
        secrets, so the build (which needs no runtime env) must not load it.
        """
        s = self.script
        base = Path("/proj")

        old_is_file = s.Path.is_file
        old_strip = s.strip_env_files
        try:

            def fake_is_file(self: Path) -> bool:
                return str(self) in (
                    "/proj/compose.yml",
                    "/proj/.env",
                    "/proj/.env/env",
                )

            def fake_strip(project_dir: Path, files):
                return [Path(f"{f}.noenv.yml") for f in files]

            s.Path.is_file = fake_is_file  # type: ignore[assignment]
            s.strip_env_files = fake_strip  # type: ignore[assignment]

            cmd = s.build_cmd("myproj", base, ["build"])

            self.assertNotIn("--env-file", cmd)
            self.assertIn("/proj/compose.yml.noenv.yml", cmd)
            self.assertNotIn("/proj/compose.yml", cmd)
            self.assertEqual(cmd[-1], "build")
        finally:
            s.Path.is_file = old_is_file  # type: ignore[assignment]
            s.strip_env_files = old_strip  # type: ignore[assignment]

    def test_strip_env_files_removes_env_file_key(self):
        s = self.script
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            src = project_dir / "compose.yml"
            src.write_text(
                "services:\n"
                "  app:\n"
                "    image: x\n"
                "    env_file:\n"
                '      - "/proj/.env/env"\n'
            )
            out = s.strip_env_files(project_dir, [src])
            self.assertEqual([p.name for p in out], ["compose.noenv.yml"])
            text = read_text(str(out[0]))
            self.assertNotIn("env_file", text)
            self.assertIn("image", text)

    def test_main_defaults_to_cwd_and_project_basename(self):
        s = self.script

        old_argv = s.sys.argv
        old_cwd = s.Path.cwd
        old_is_dir = s.Path.is_dir
        old_resolve = s.Path.resolve
        old_build_cmd = s.build_cmd
        old_execvp = s.os.execvp

        calls = {"build": None, "exec": None}

        try:
            # Simulate cwd = /work/matomo
            def fake_cwd() -> Path:
                return Path("/work/matomo")

            # Keep resolve deterministic and simple for tests
            def fake_resolve(self: Path) -> Path:
                return self

            def fake_is_dir(self: Path) -> bool:
                return str(self) == "/work/matomo"

            def fake_build_cmd(
                project: str, project_dir: Path, passthrough, extra_files=None
            ):
                calls["build"] = (
                    project,
                    str(project_dir),
                    list(passthrough),
                    extra_files,
                )
                return ["docker", "compose", "-p", project, "ps"]

            def fake_execvp(prog, argv):
                calls["exec"] = (prog, list(argv))
                raise RuntimeError("execvp called")  # stop execution

            s.Path.cwd = staticmethod(fake_cwd)  # type: ignore[assignment]
            s.Path.resolve = fake_resolve  # type: ignore[assignment]
            s.Path.is_dir = fake_is_dir  # type: ignore[assignment]
            s.build_cmd = fake_build_cmd  # type: ignore[assignment]
            s.os.execvp = fake_execvp  # type: ignore[assignment]

            s.sys.argv = ["compose.py", "ps"]

            with self.assertRaises(RuntimeError):
                s.main()

            self.assertEqual(calls["build"], ("matomo", "/work/matomo", ["ps"], None))
            self.assertEqual(calls["exec"][0], "docker")
            self.assertEqual(
                calls["exec"][1][:4], ["docker", "compose", "-p", "matomo"]
            )
        finally:
            s.sys.argv = old_argv
            s.Path.cwd = old_cwd  # type: ignore[assignment]
            s.Path.is_dir = old_is_dir  # type: ignore[assignment]
            s.Path.resolve = old_resolve  # type: ignore[assignment]
            s.build_cmd = old_build_cmd  # type: ignore[assignment]
            s.os.execvp = old_execvp  # type: ignore[assignment]

    def test_main_project_defaults_to_chdir_basename(self):
        s = self.script

        old_argv = s.sys.argv
        old_is_dir = s.Path.is_dir
        old_resolve = s.Path.resolve
        old_build_cmd = s.build_cmd
        old_execvp = s.os.execvp

        calls = {"build": None}

        try:

            def fake_resolve(self: Path) -> Path:
                return self

            def fake_is_dir(self: Path) -> bool:
                return str(self) == "/opt/compose/nextcloud"

            def fake_build_cmd(
                project: str, project_dir: Path, passthrough, extra_files=None
            ):
                calls["build"] = (
                    project,
                    str(project_dir),
                    list(passthrough),
                    extra_files,
                )
                return ["docker", "compose", "-p", project, "up", "-d"]

            def fake_execvp(prog, argv):
                raise RuntimeError("execvp called")

            s.Path.resolve = fake_resolve  # type: ignore[assignment]
            s.Path.is_dir = fake_is_dir  # type: ignore[assignment]
            s.build_cmd = fake_build_cmd  # type: ignore[assignment]
            s.os.execvp = fake_execvp  # type: ignore[assignment]

            s.sys.argv = ["compose.py", "--chdir", "/opt/compose/nextcloud", "up", "-d"]

            with self.assertRaises(RuntimeError):
                s.main()

            self.assertEqual(
                calls["build"],
                ("nextcloud", "/opt/compose/nextcloud", ["up", "-d"], None),
            )
        finally:
            s.sys.argv = old_argv
            s.Path.is_dir = old_is_dir  # type: ignore[assignment]
            s.Path.resolve = old_resolve  # type: ignore[assignment]
            s.build_cmd = old_build_cmd  # type: ignore[assignment]
            s.os.execvp = old_execvp  # type: ignore[assignment]

    def test_main_project_override_uses_given_project(self):
        s = self.script

        old_argv = s.sys.argv
        old_cwd = s.Path.cwd
        old_is_dir = s.Path.is_dir
        old_resolve = s.Path.resolve
        old_build_cmd = s.build_cmd
        old_execvp = s.os.execvp

        calls = {"build": None}

        try:

            def fake_cwd() -> Path:
                return Path("/work/anything")

            def fake_resolve(self: Path) -> Path:
                return self

            def fake_is_dir(self: Path) -> bool:
                return str(self) == "/work/anything"

            def fake_build_cmd(
                project: str, project_dir: Path, passthrough, extra_files=None
            ):
                calls["build"] = (
                    project,
                    str(project_dir),
                    list(passthrough),
                    extra_files,
                )
                return ["docker", "compose", "-p", project, "restart", "web"]

            def fake_execvp(prog, argv):
                raise RuntimeError("execvp called")

            s.Path.cwd = staticmethod(fake_cwd)  # type: ignore[assignment]
            s.Path.resolve = fake_resolve  # type: ignore[assignment]
            s.Path.is_dir = fake_is_dir  # type: ignore[assignment]
            s.build_cmd = fake_build_cmd  # type: ignore[assignment]
            s.os.execvp = fake_execvp  # type: ignore[assignment]

            s.sys.argv = ["compose.py", "--project", "customproj", "restart", "web"]

            with self.assertRaises(RuntimeError):
                s.main()

            self.assertEqual(
                calls["build"],
                ("customproj", "/work/anything", ["restart", "web"], None),
            )
        finally:
            s.sys.argv = old_argv
            s.Path.cwd = old_cwd  # type: ignore[assignment]
            s.Path.is_dir = old_is_dir  # type: ignore[assignment]
            s.Path.resolve = old_resolve  # type: ignore[assignment]
            s.build_cmd = old_build_cmd  # type: ignore[assignment]
            s.os.execvp = old_execvp  # type: ignore[assignment]

    def test_main_strips_double_dash_from_passthrough(self):
        s = self.script

        old_argv = s.sys.argv
        old_cwd = s.Path.cwd
        old_is_dir = s.Path.is_dir
        old_resolve = s.Path.resolve
        old_build_cmd = s.build_cmd
        old_execvp = s.os.execvp

        calls = {"build": None}

        try:

            def fake_cwd() -> Path:
                return Path("/work/app")

            def fake_resolve(self: Path) -> Path:
                return self

            def fake_is_dir(self: Path) -> bool:
                return str(self) == "/work/app"

            def fake_build_cmd(
                project: str, project_dir: Path, passthrough, extra_files=None
            ):
                calls["build"] = (
                    project,
                    str(project_dir),
                    list(passthrough),
                    extra_files,
                )
                return ["docker", "compose", "-p", project, *list(passthrough)]

            def fake_execvp(prog, argv):
                raise RuntimeError("execvp called")

            s.Path.cwd = staticmethod(fake_cwd)  # type: ignore[assignment]
            s.Path.resolve = fake_resolve  # type: ignore[assignment]
            s.Path.is_dir = fake_is_dir  # type: ignore[assignment]
            s.build_cmd = fake_build_cmd  # type: ignore[assignment]
            s.os.execvp = fake_execvp  # type: ignore[assignment]

            # Everything after "--" must be passed through to compose, with the "--" removed
            s.sys.argv = ["compose.py", "--", "ps", "--services"]

            with self.assertRaises(RuntimeError):
                s.main()

            self.assertEqual(
                calls["build"],
                ("app", "/work/app", ["ps", "--services"], None),
            )
        finally:
            s.sys.argv = old_argv
            s.Path.cwd = old_cwd  # type: ignore[assignment]
            s.Path.is_dir = old_is_dir  # type: ignore[assignment]
            s.Path.resolve = old_resolve  # type: ignore[assignment]
            s.build_cmd = old_build_cmd  # type: ignore[assignment]
            s.os.execvp = old_execvp  # type: ignore[assignment]

    def test_main_passes_file_args_to_build_cmd(self):
        """
        New CLI behavior: `compose -f X ...` should pass extra_files=["X"] to build_cmd
        and still work with passthrough args.
        """
        s = self.script

        old_argv = s.sys.argv
        old_cwd = s.Path.cwd
        old_is_dir = s.Path.is_dir
        old_resolve = s.Path.resolve
        old_build_cmd = s.build_cmd
        old_execvp = s.os.execvp

        calls = {"build": None}

        try:

            def fake_cwd() -> Path:
                return Path("/work/taiga")

            def fake_resolve(self: Path) -> Path:
                return self

            def fake_is_dir(self: Path) -> bool:
                return str(self) == "/work/taiga"

            def fake_build_cmd(
                project: str, project_dir: Path, passthrough, extra_files=None
            ):
                calls["build"] = (
                    project,
                    str(project_dir),
                    list(passthrough),
                    extra_files,
                )
                return ["docker", "compose", "-p", project, "ps"]

            def fake_execvp(prog, argv):
                raise RuntimeError("execvp called")

            s.Path.cwd = staticmethod(fake_cwd)  # type: ignore[assignment]
            s.Path.resolve = fake_resolve  # type: ignore[assignment]
            s.Path.is_dir = fake_is_dir  # type: ignore[assignment]
            s.build_cmd = fake_build_cmd  # type: ignore[assignment]
            s.os.execvp = fake_execvp  # type: ignore[assignment]

            s.sys.argv = [
                "compose.py",
                "-f",
                "compose-inits.yml",
                "run",
                "--rm",
                "manager",
                "migrate",
            ]

            with self.assertRaises(RuntimeError):
                s.main()

            self.assertEqual(
                calls["build"],
                (
                    "taiga",
                    "/work/taiga",
                    ["run", "--rm", "manager", "migrate"],
                    ["compose-inits.yml"],
                ),
            )
        finally:
            s.sys.argv = old_argv
            s.Path.cwd = old_cwd  # type: ignore[assignment]
            s.Path.is_dir = old_is_dir  # type: ignore[assignment]
            s.Path.resolve = old_resolve  # type: ignore[assignment]
            s.build_cmd = old_build_cmd  # type: ignore[assignment]
            s.os.execvp = old_execvp  # type: ignore[assignment]


class TestCaOverrideStaleDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script_module()

    def _write(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def _make_compose(self, tmpdir: Path, services: list[str]) -> Path:
        body = "services:\n" + "".join(
            f"  {name}:\n    image: example/{name}:latest\n" for name in services
        )
        path = tmpdir / "compose.yml"
        self._write(path, body)
        return path

    def _make_override(self, tmpdir: Path, services: list[str]) -> Path:
        body = "services:\n" + "".join(
            f"  {name}:\n    entrypoint: [/tmp/with-ca-trust.sh]\n" for name in services
        )
        path = tmpdir / "compose.ca.override.yml"
        self._write(path, body)
        return path

    def test_stale_when_override_has_extra_service(self):
        import tempfile

        s = self.script
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = self._make_compose(tmp, ["application", "redis"])
            override = self._make_override(tmp, ["application", "redis", "database"])
            self.assertTrue(s.ca_override_is_stale(base, override))

    def test_fresh_when_override_matches_compose(self):
        import tempfile

        s = self.script
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = self._make_compose(tmp, ["application", "redis", "database"])
            override = self._make_override(tmp, ["application", "redis", "database"])
            self.assertFalse(s.ca_override_is_stale(base, override))

    def test_fresh_when_override_is_strict_subset(self):
        # Override may legitimately wrap only a subset; subset MUST NOT be flagged.
        import tempfile

        s = self.script
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = self._make_compose(tmp, ["application", "redis", "database"])
            override = self._make_override(tmp, ["application"])
            self.assertFalse(s.ca_override_is_stale(base, override))

    def test_empty_base_treated_as_not_stale(self):
        import tempfile

        s = self.script
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = tmp / "compose.yml"
            self._write(base, "")
            override = self._make_override(tmp, ["application"])
            self.assertFalse(s.ca_override_is_stale(base, override))

    def test_empty_override_treated_as_not_stale(self):
        import tempfile

        s = self.script
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = self._make_compose(tmp, ["application"])
            override = tmp / "compose.ca.override.yml"
            self._write(override, "")
            self.assertFalse(s.ca_override_is_stale(base, override))

    def test_detect_compose_files_skips_stale_override(self):
        import io
        import tempfile
        from contextlib import redirect_stderr

        s = self.script
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = self._make_compose(tmp, ["application", "redis"])
            stale = self._make_override(tmp, ["application", "database"])

            buf = io.StringIO()
            with redirect_stderr(buf):
                files = s.detect_compose_files(tmp)
            self.assertIn(base, files)
            self.assertNotIn(stale, files)
            self.assertIn("skipping stale compose.ca.override.yml", buf.getvalue())

    def test_detect_compose_files_keeps_fresh_override(self):
        import tempfile

        s = self.script
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = self._make_compose(tmp, ["application", "redis"])
            fresh = self._make_override(tmp, ["application", "redis"])

            files = s.detect_compose_files(tmp)
            self.assertIn(base, files)
            self.assertIn(fresh, files)


if __name__ == "__main__":
    unittest.main()
