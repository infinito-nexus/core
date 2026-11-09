import contextlib
import importlib.util
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-confluence/files/python/build_guard.py"
_SPEC = importlib.util.spec_from_file_location("confluence_build_guard", SCRIPT)
guard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guard)

CONFIG = """<?xml version="1.0" encoding="UTF-8"?>
<confluence-configuration>
  <setupStep>complete</setupStep>
  <setupType>custom</setupType>
  <buildNumber>{build}</buildNumber>
  <properties>
    <property name="confluence.setup.server.id">ABCD-EFGH</property>
  </properties>
</confluence-configuration>
"""


class TestBuildGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "home"
        self.install = root / "install"
        self.home.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _image(self, build: int, version: str) -> None:
        lib = self.install / "confluence/WEB-INF/lib"
        lib.mkdir(parents=True)
        core = f"com.atlassian.confluence.confluence-{version}.jar"
        with zipfile.ZipFile(lib / core, "w") as jar:
            jar.writestr(
                guard.BUILD_PROPERTIES,
                f"# generated\nversion.number={version}\nbuild.number={build}\n",
            )
        sibling = f"com.atlassian.confluence.confluence-api-impl-{version}.jar"
        with zipfile.ZipFile(lib / sibling, "w") as other:
            other.writestr("README", "not the core jar")

    def _home(self, build: str) -> None:
        (self.home / guard.HOME_CONFIG).write_text(CONFIG.format(build=build))

    def _run(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = guard.main(
                [
                    str(self.home),
                    str(self.install),
                    "confluence_data",
                    "atlassian/confluence:10.2.18",
                ]
            )
        return code, out.getvalue(), err.getvalue()

    def test_home_build_reads_the_build_number_element(self) -> None:
        self._home("11000")
        self.assertEqual(guard.home_build(self.home), 11000)

    def test_home_without_config_records_no_build(self) -> None:
        self.assertEqual(guard.home_build(self.home), 0)

    def test_home_with_empty_build_number_records_no_build(self) -> None:
        self._home("")
        self.assertEqual(guard.home_build(self.home), 0)

    def test_parse_properties_skips_comments_and_blank_lines(self) -> None:
        self.assertEqual(
            guard.parse_properties("# c\n! c\n\nbuild.number = 10\nname=a=b\n"),
            {"build.number": "10", "name": "a=b"},
        )

    def test_image_build_reads_the_core_jar(self) -> None:
        self._image(9424, "10.2.18")
        self.assertEqual(guard.image_build(self.install), (9424, "10.2.18"))

    def test_image_without_core_jar_stops_with_its_path(self) -> None:
        self.install.mkdir()
        with self.assertRaises(SystemExit) as raised:
            guard.image_build(self.install)
        self.assertIn("found 0", str(raised.exception))

    def test_a_newer_home_stops_with_both_build_numbers(self) -> None:
        self._image(10218, "10.2.18")
        self._home("11000")

        code, out, _ = self._run()

        self.assertEqual(code, guard.DOWNGRADE_EXIT)
        self.assertIn("written by Confluence build 11000", out)
        self.assertIn(
            "atlassian/confluence:10.2.18 is Confluence 10.2.18 build 10218", out
        )

    def test_an_equal_home_passes(self) -> None:
        self._image(10218, "10.2.18")
        self._home("10218")

        code, out, _ = self._run()

        self.assertEqual(code, 0)
        self.assertIn("build 10218 <= atlassian/confluence:10.2.18 build 10218", out)

    def test_an_older_home_passes_for_the_upgrade(self) -> None:
        self._image(10218, "10.2.18")
        self._home("9012")

        code, _, _ = self._run()

        self.assertEqual(code, 0)

    def test_a_home_before_setup_passes(self) -> None:
        self._image(10218, "10.2.18")
        self._home("0")

        code, out, _ = self._run()

        self.assertEqual(code, 0)
        self.assertIn("build - <=", out)

    def test_wrong_argument_count_is_a_usage_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main([]), 2)


if __name__ == "__main__":
    unittest.main()
