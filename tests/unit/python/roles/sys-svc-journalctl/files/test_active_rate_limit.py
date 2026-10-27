import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "sys-svc-journalctl"
    / "files"
    / "python"
    / "active_rate_limit.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("active_rate_limit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestActiveRateLimit(TestCase):
    def setUp(self):
        self.script = load_script()
        self.export_dir = Path(tempfile.mkdtemp())

    def output(self, exports):
        for name, target in exports.items():
            (self.export_dir / name).symlink_to(target)
        stdout = io.StringIO()
        with (
            mock.patch.object(self.script, "EXPORT_DIR", self.export_dir),
            mock.patch.object(sys, "argv", ["active_rate_limit.py", "docker.service"]),
            contextlib.redirect_stdout(stdout),
        ):
            self.script.main()
        return stdout.getvalue().strip()

    def test_exported_limit_is_read(self):
        self.assertEqual(
            self.output(
                {
                    "log-rate-limit-interval:docker.service": "30000000",
                    "log-rate-limit-burst:docker.service": "50000",
                }
            ),
            "30000000 50000",
        )

    def test_a_unit_without_its_own_limit_prints_dashes(self):
        self.assertEqual(self.output({}), "- -")

    def test_the_export_dir_is_systemds(self):
        self.assertEqual(self.script.EXPORT_DIR, Path("/run/systemd/units"))


if __name__ == "__main__":
    main()
