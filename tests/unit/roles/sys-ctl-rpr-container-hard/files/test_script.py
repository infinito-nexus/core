import sys
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from . import PROJECT_ROOT


def load_script_module():
    """
    Import the script under test from roles/sys-ctl-rpr-container-hard/files/script.py
    """
    script_path = (
        PROJECT_ROOT / "roles" / "sys-ctl-rpr-container-hard" / "files" / "script.py"
    )
    if not script_path.exists():
        raise FileNotFoundError(f"script.py not found at {script_path}")
    spec = spec_from_file_location("rpr_hard_script", str(script_path))
    mod = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


class TestRepairDockerHard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script_module()

    def test_hard_restart_uses_wrapper_and_cwd(self):
        s = self.script
        calls = []

        def fake_run(cmd, cwd=None, check=None):
            calls.append({"cmd": cmd, "cwd": cwd, "check": check})

            class R:
                pass

            return R()

        old_run = s.subprocess.run
        try:
            s.subprocess.run = fake_run

            s.hard_restart_docker_services("/X/APP")

            # Expect two calls: compose ... down / up -d
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["cwd"], "/X/APP")
            self.assertEqual(calls[1]["cwd"], "/X/APP")

            # down
            self.assertEqual(calls[0]["cmd"][0], "compose")
            self.assertIn("--chdir", calls[0]["cmd"])
            self.assertIn("/X/APP", calls[0]["cmd"])
            self.assertIn("--project", calls[0]["cmd"])
            self.assertIn("APP", calls[0]["cmd"])  # basename project
            self.assertIn("down", calls[0]["cmd"])

            # up -d
            self.assertEqual(calls[1]["cmd"][0], "compose")
            self.assertIn("--chdir", calls[1]["cmd"])
            self.assertIn("/X/APP", calls[1]["cmd"])
            self.assertIn("--project", calls[1]["cmd"])
            self.assertIn("APP", calls[1]["cmd"])
            self.assertIn("up", calls[1]["cmd"])
            self.assertIn("-d", calls[1]["cmd"])
        finally:
            s.subprocess.run = old_run

    def test_main_scans_parent_and_filters_only(self):
        s = self.script
        seen = {"scandir": [], "called": []}

        class FakeDirEntry:
            def __init__(self, path, is_dir=True):
                self.path = path
                self._is_dir = is_dir

            def is_dir(self):
                return self._is_dir

        def fake_scandir(parent):
            seen["scandir"].append(parent)
            return [
                FakeDirEntry(f"{parent}/app1"),
                FakeDirEntry(f"{parent}/app2"),
                FakeDirEntry(f"{parent}/notdir", is_dir=False),
            ]

        def fake_isdir(p):
            return p == "/PARENT"

        def fake_isfile(p):
            # Only app2 has compose.yml
            return p == "/PARENT/app2/compose.yml"

        def fake_hard_restart(dir_path):
            seen["called"].append(dir_path)

        old_scandir = s.os.scandir
        old_isdir = s.os.path.isdir
        old_isfile = s.os.path.isfile
        old_restart = s.hard_restart_docker_services
        try:
            s.os.scandir = fake_scandir
            s.os.path.isdir = fake_isdir
            s.os.path.isfile = fake_isfile
            s.hard_restart_docker_services = fake_hard_restart

            # With --only app2 -> only app2 is called
            sys_argv = sys.argv
            sys.argv = ["x", "/PARENT", "--only", "app2"]
            s.main()
            self.assertEqual(seen["called"], ["/PARENT/app2"])
        finally:
            s.os.scandir = old_scandir
            s.os.path.isdir = old_isdir
            s.os.path.isfile = old_isfile
            s.hard_restart_docker_services = old_restart
            sys.argv = sys_argv


if __name__ == "__main__":
    unittest.main()
